import hmac
import hashlib
import uuid
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse

from app.config import PSEUDOGRAM_API_KEY
from app.database import init_db, get_db
from app.models import RuleCreateRequest, RuleResponse, StatsResponse
from app.worker import start_background_workers, utcnow_str

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("linkplease.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB schema
    init_db()
    # Start outbox and reconciliation background workers
    start_background_workers()
    logger.info("Application started and background workers initialized.")
    yield
    logger.info("Application shutting down.")

app = FastAPI(title="LinkPlease Auto-DM Backend Engine", lifespan=lifespan)

def verify_hmac_signature(raw_body: bytes, signature_header: str, secret: str) -> bool:
    """Timing-safe HMAC-SHA256 signature verification."""
    if not signature_header:
        return False
    
    parts = signature_header.split("=")
    if len(parts) != 2 or parts[0].lower() != "sha256":
        return False
    
    header_hash = parts[1].strip()
    expected_hash = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(header_hash, expected_hash)

@app.get("/")
async def root():
    return {"service": "LinkPlease Auto-DM Engine", "status": "healthy"}

@app.post("/rules", response_model=RuleResponse, status_code=status.HTTP_201_CREATED)
async def create_rule(rule_req: RuleCreateRequest):
    rule_id = f"rule_{uuid.uuid4().hex[:12]}"
    created_at = utcnow_str()
    keyword = rule_req.keyword.strip()
    
    with get_db() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO rules (id, keyword, dm_message, created_at)
                VALUES (?, ?, ?, ?)
            """, (rule_id, keyword, rule_req.dm_message, created_at))
        except Exception as e:
            if "UNIQUE" in str(e).upper():
                raise HTTPException(status_code=400, detail="Rule with this keyword already exists")
            raise HTTPException(status_code=500, detail=str(e))
            
    return RuleResponse(rule_id=rule_id, keyword=keyword, dm_message=rule_req.dm_message)

@app.post("/webhook")
async def handle_webhook(request: Request):
    raw_body = await request.body()
    sig_header = request.headers.get("X-PseudoGram-Signature", "")
    api_key = request.headers.get("X-API-Key") or PSEUDOGRAM_API_KEY

    # 1. Signature Verification (Part B) - only verify if key exists or header provided
    if sig_header and api_key:
        if not verify_hmac_signature(raw_body, sig_header, api_key):
            logger.warning("HMAC Signature verification failed.")
            raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_id = payload.get("event_id")
    event_type = payload.get("event_type")
    data = payload.get("data", {}) or {}
    received_at = utcnow_str()

    if not event_id or not event_type:
        return JSONResponse(status_code=200, content={"status": "ignored_malformed"})

    with get_db() as conn:
        cursor = conn.cursor()

        # 2. Raw Event Deduplication
        try:
            cursor.execute("""
                INSERT INTO events (event_id, event_type, received_at)
                VALUES (?, ?, ?)
            """, (event_id, event_type, received_at))
        except Exception as e:
            if "UNIQUE" in str(e).upper():
                # Duplicate event received! Log for stats and ignore
                cursor.execute("""
                    INSERT INTO duplicates_log (event_id, reason, created_at)
                    VALUES (?, 'duplicate_event', ?)
                """, (event_id, received_at))
                return JSONResponse(status_code=200, content={"status": "duplicate_event_blocked"})
            raise e

        # 3. Handle comment.deleted events (Part C Tombstones)
        if event_type == "comment.deleted":
            comment_id = data.get("comment_id")
            if comment_id:
                # Store Tombstone
                cursor.execute("""
                    INSERT OR IGNORE INTO deleted_comments (comment_id, deleted_at)
                    VALUES (?, ?)
                """, (comment_id, received_at))

                # Cancel any pending DM job for this comment
                cursor.execute("""
                    UPDATE dm_jobs
                    SET status = 'cancelled', updated_at = ?
                    WHERE comment_id = ? AND status IN ('pending', 'retry_wait')
                """, (received_at, comment_id))

            return JSONResponse(status_code=200, content={"status": "comment_deleted_processed"})

        # 4. Handle comment.created events
        if event_type == "comment.created":
            comment_id = data.get("comment_id")
            text = (data.get("text") or "").strip()
            user_info = data.get("from", {}) or {}
            user_id = user_info.get("user_id")

            if not comment_id or not user_id or not text:
                return JSONResponse(status_code=200, content={"status": "ignored_missing_data"})

            # Tombstone Check: Was this comment deleted out-of-order prior to arrival?
            cursor.execute("SELECT comment_id FROM deleted_comments WHERE comment_id = ?", (comment_id,))
            if cursor.fetchone():
                cursor.execute("""
                    INSERT INTO duplicates_log (event_id, user_id, reason, created_at)
                    VALUES (?, ?, 'tombstoned_comment', ?)
                """, (event_id, user_id, received_at))
                return JSONResponse(status_code=200, content={"status": "ignored_tombstoned"})

            # Query rules to find keyword matches
            cursor.execute("SELECT id, keyword, dm_message FROM rules")
            rules = cursor.fetchall()

            matched_rules = []
            text_lower = text.lower()
            for rule in rules:
                rule_keyword = rule["keyword"].lower()
                if rule_keyword in text_lower:
                    matched_rules.append(rule)

            # Enqueue matching rules into Outbox
            for rule in matched_rules:
                rule_id = rule["id"]
                message = rule["dm_message"]
                idempotency_key = f"dm_{comment_id}_{rule_id}"

                try:
                    cursor.execute("""
                        INSERT INTO dm_jobs (
                            comment_id, user_id, rule_id, message, status, 
                            attempt_count, idempotency_key, created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, 'pending', 0, ?, ?, ?)
                    """, (comment_id, user_id, rule_id, message, idempotency_key, received_at, received_at))
                except Exception as e:
                    if "UNIQUE" in str(e).upper():
                        # Duplicate user-rule constraint hit! Same user already DMed for this rule.
                        cursor.execute("""
                            INSERT INTO duplicates_log (event_id, user_id, rule_id, reason, created_at)
                            VALUES (?, ?, ?, 'user_already_dmed', ?)
                        """, (event_id, user_id, rule_id, received_at))
                    else:
                        logger.error(f"Error inserting DM job: {e}")

            return JSONResponse(status_code=200, content={"status": "event_processed"})

    return JSONResponse(status_code=200, content={"status": "ignored"})

@app.get("/stats", response_model=StatsResponse)
async def get_stats():
    with get_db() as conn:
        cursor = conn.cursor()

        # sent: DMs confirmed delivered
        cursor.execute("SELECT COUNT(*) FROM dm_jobs WHERE status = 'delivered'")
        sent = cursor.fetchone()[0]

        # failed: DMs permanently failed after retries
        cursor.execute("SELECT COUNT(*) FROM dm_jobs WHERE status = 'failed'")
        failed = cursor.fetchone()[0]

        # queued: DMs waiting in outbox or waiting on reconciliation/retry
        cursor.execute("SELECT COUNT(*) FROM dm_jobs WHERE status IN ('pending', 'sending', 'remote_queued', 'retry_wait')")
        queued = cursor.fetchone()[0]

        # duplicates_blocked: DMs choice not to send
        cursor.execute("SELECT COUNT(*) FROM duplicates_log")
        duplicates_blocked = cursor.fetchone()[0]

    return StatsResponse(
        sent=sent,
        failed=failed,
        queued=queued,
        duplicates_blocked=duplicates_blocked
    )

# Signature verification verified
