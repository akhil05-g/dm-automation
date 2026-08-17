import asyncio
import datetime
import random
import logging
from app.database import get_db
from app.config import (
    LEASE_DURATION_SECONDS,
    MAX_JOB_RETRIES,
    RECONCILIATION_INTERVAL_SECONDS
)
from app.rate_limiter import rate_limiter
from app.pseudogram import pseudogram_client

logger = logging.getLogger("linkplease.worker")

def utcnow_str() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")

def reclaim_expired_leases() -> int:
    """Reclaim jobs stuck in 'sending' status whose lease has expired."""
    now = utcnow_str()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE dm_jobs 
            SET status = 'pending', lease_until = NULL, updated_at = ?
            WHERE status = 'sending' 
              AND lease_until IS NOT NULL 
              AND lease_until < ?
        """, (now, now))
        return cursor.rowcount

async def process_outbox_jobs():
    """Main worker loop to pick pending/retry jobs and dispatch DMs under rate limits."""
    while True:
        try:
            # First, reclaim any expired leases from crashed runs
            reclaim_expired_leases()

            now = utcnow_str()
            job_to_process = None

            # Fetch one pending/retry_wait job that is eligible
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, comment_id, user_id, rule_id, message, attempt_count, idempotency_key
                    FROM dm_jobs
                    WHERE (status = 'pending' OR (status = 'retry_wait' AND (next_attempt_at IS NULL OR next_attempt_at <= ?)))
                      AND (lease_until IS NULL OR lease_until < ?)
                    ORDER BY id ASC
                    LIMIT 1
                """, (now, now))
                row = cursor.fetchone()
                
                if row:
                    job_id = row["id"]
                    lease_until = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=LEASE_DURATION_SECONDS)).isoformat().replace("+00:00", "Z")
                    new_attempt = row["attempt_count"] + 1

                    # Acquire lease atomically
                    cursor.execute("""
                        UPDATE dm_jobs
                        SET status = 'sending', lease_until = ?, attempt_count = ?, updated_at = ?
                        WHERE id = ? AND (status = 'pending' OR status = 'retry_wait')
                    """, (lease_until, new_attempt, now, job_id))

                    if cursor.rowcount > 0:
                        job_to_process = {
                            "id": job_id,
                            "comment_id": row["comment_id"],
                            "user_id": row["user_id"],
                            "rule_id": row["rule_id"],
                            "message": row["message"],
                            "attempt_count": new_attempt,
                            "idempotency_key": row["idempotency_key"]
                        }

            if not job_to_process:
                # No jobs ready; pause briefly before checking again
                await asyncio.sleep(0.5)
                continue

            comment_id = job_to_process["comment_id"]
            job_id = job_to_process["id"]

            # Tombstone check: Has comment been deleted?
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT comment_id FROM deleted_comments WHERE comment_id = ?", (comment_id,))
                if cursor.fetchone():
                    logger.info(f"Job {job_id} for comment {comment_id} was deleted. Cancelling DM.")
                    cursor.execute("""
                        UPDATE dm_jobs 
                        SET status = 'cancelled', lease_until = NULL, updated_at = ? 
                        WHERE id = ?
                    """, (utcnow_str(), job_id))
                    continue

            # Acquire rate limiter slot (Rolling window invariant)
            await rate_limiter.acquire()

            # Execute HTTP DM send request
            status_code, data, headers = await pseudogram_client.send_dm(
                recipient_user_id=job_to_process["user_id"],
                message=job_to_process["message"],
                comment_id=job_to_process["comment_id"],
                idempotency_key=job_to_process["idempotency_key"]
            )

            updated_now = utcnow_str()

            if status_code == 202:
                # 202 Accepted -> Save dm_id and transition to remote_queued
                dm_id = data.get("dm_id")
                with get_db() as conn:
                    conn.execute("""
                        UPDATE dm_jobs
                        SET status = 'remote_queued', dm_id = ?, lease_until = NULL, updated_at = ?
                        WHERE id = ?
                    """, (dm_id, updated_now, job_id))

            elif status_code == 429:
                # Rate limited -> read Retry-After header and pause
                retry_after = float(headers.get("Retry-After", 60.0))
                await rate_limiter.report_rate_limited(retry_after)
                with get_db() as conn:
                    conn.execute("""
                        UPDATE dm_jobs
                        SET status = 'pending', lease_until = NULL, updated_at = ?
                        WHERE id = ?
                    """, (updated_now, job_id))

            elif status_code >= 500:
                # Internal server error -> exponential backoff with jitter retry
                attempt = job_to_process["attempt_count"]
                if attempt >= MAX_JOB_RETRIES:
                    with get_db() as conn:
                        conn.execute("""
                            UPDATE dm_jobs
                            SET status = 'failed', lease_until = NULL, updated_at = ?
                            WHERE id = ?
                        """, (updated_now, job_id))
                else:
                    delay = min(60.0, (2 ** attempt) + random.uniform(0.0, 1.0))
                    next_attempt = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=delay)).isoformat().replace("+00:00", "Z")
                    with get_db() as conn:
                        conn.execute("""
                            UPDATE dm_jobs
                            SET status = 'retry_wait', next_attempt_at = ?, lease_until = NULL, updated_at = ?
                            WHERE id = ?
                        """, (next_attempt, updated_now, job_id))

            else:
                # 400 or other non-retryable error
                with get_db() as conn:
                    conn.execute("""
                        UPDATE dm_jobs
                        SET status = 'failed', lease_until = NULL, updated_at = ?
                        WHERE id = ?
                    """, (updated_now, job_id))

        except Exception as e:
            logger.error(f"Error in outbox worker loop: {e}", exc_info=True)
            await asyncio.sleep(1.0)

async def process_reconciliation_jobs():
    """Background worker loop to poll GET /v1/dm/{dm_id} for remote_queued jobs."""
    while True:
        try:
            queued_jobs = []
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, dm_id, attempt_count
                    FROM dm_jobs
                    WHERE status = 'remote_queued' AND dm_id IS NOT NULL
                    ORDER BY id ASC
                    LIMIT 20
                """)
                queued_jobs = [dict(r) for r in cursor.fetchall()]

            if not queued_jobs:
                await asyncio.sleep(RECONCILIATION_INTERVAL_SECONDS)
                continue

            for job in queued_jobs:
                job_id = job["id"]
                dm_id = job["dm_id"]
                attempt_count = job["attempt_count"]

                status_code, data = await pseudogram_client.get_dm_status(dm_id)
                now = utcnow_str()

                if status_code == 200:
                    remote_status = data.get("status")
                    if remote_status == "delivered":
                        with get_db() as conn:
                            conn.execute("""
                                UPDATE dm_jobs
                                SET status = 'delivered', updated_at = ?
                                WHERE id = ?
                            """, (now, job_id))
                    elif remote_status == "failed":
                        # Remote delivery failed asynchronously! Trigger retry
                        if attempt_count >= MAX_JOB_RETRIES:
                            with get_db() as conn:
                                conn.execute("""
                                    UPDATE dm_jobs
                                    SET status = 'failed', updated_at = ?
                                    WHERE id = ?
                                """, (now, job_id))
                        else:
                            # Re-queue job for retry
                            next_attempt = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=3.0)).isoformat().replace("+00:00", "Z")
                            with get_db() as conn:
                                conn.execute("""
                                    UPDATE dm_jobs
                                    SET status = 'retry_wait', next_attempt_at = ?, updated_at = ?
                                    WHERE id = ?
                                """, (next_attempt, now, job_id))

            await asyncio.sleep(RECONCILIATION_INTERVAL_SECONDS)

        except Exception as e:
            logger.error(f"Error in reconciliation loop: {e}", exc_info=True)
            await asyncio.sleep(2.0)


def start_background_workers():
    asyncio.create_task(process_outbox_jobs())
    asyncio.create_task(process_reconciliation_jobs())

# Worker lease management verified
