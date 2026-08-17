# FAILURES.md

Known ways this system can still lose a DM, send a duplicate, or report wrong numbers.

---

### 1. Process crash during in-flight DM send

If the server is killed (`SIGKILL`, OOM, power loss) right after PseudoGram accepts a `POST /v1/dm/send` but before we commit `status = 'remote_queued'` to SQLite, the job stays as `pending` in the database.

On restart, the worker picks it up again and retries with the same `Idempotency-Key`. If PseudoGram's idempotency window has expired by then, they'll treat it as a new request and the user gets the DM twice.

We rely on PseudoGram honouring idempotency keys indefinitely, which we can't guarantee.

---

### 2. Rate limiter state lost on restart

The rolling-window rate limiter tracks the last 10 send timestamps in memory. If the process restarts while we've recently sent 8 DMs in the last 30 seconds, the new process has no memory of those calls. It will immediately fire up to 10 more sends, which combined with PseudoGram's server-side tracking means we'll hit `429` errors.

The system recovers (it reads `Retry-After` and backs off), but there's a brief burst of wasted requests right after every restart.

---

### 3. Single-instance architecture can't scale horizontally

SQLite is a file-level database. If we deployed two instances behind a load balancer, each would have its own copy of the `(user_id, rule_id)` unique constraint and its own rate limiter state. Both could send a DM to the same user for the same rule, and both could independently exceed the rate limit.

This is an intentional architecture decision — for the assignment scope, single-instance with SQLite keeps things simple and durable. Scaling out would require migrating to PostgreSQL and a shared rate limiter (e.g. Redis).

---

### 4. Permanently failed DMs after 5 retries

If PseudoGram accepts a DM (`202`) but then reports `status: failed` on the polling endpoint, we re-queue it for retry. After 5 total attempts all ending in remote failure, we mark the job as permanently `failed` and stop trying.

That DM is lost. This cap exists to prevent infinite retry loops against broken recipient accounts or systemic PseudoGram issues, but it means a legitimately deliverable DM could be abandoned if we were just unlucky 5 times in a row.

---

### 5. Late `comment.deleted` can't unsend a delivered DM

If `comment.created` arrives, the DM gets sent and confirmed as `delivered`, and then `comment.deleted` arrives 10 minutes later — the DM is already in the user's inbox. We record the tombstone but there's no API to recall a delivered message.

---

### 6. Duplicate event_id arriving within the same SQLite transaction

Two webhook requests carrying the same `event_id` hitting the server within a few milliseconds could theoretically both read `events` before either commits. SQLite's WAL mode and `busy_timeout` make this window extremely small, but under extreme burst load it's not impossible that both pass the dedup check. In practice during 500-event testing this never happened, but we can't rule it out.
