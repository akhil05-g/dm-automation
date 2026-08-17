# Engage Flow

Event-driven backend for reliable, rate-limited social engagement automation.

---

## What I Built

I built **Engage Flow**, a resilient backend service that automates creator engagement workflows based on social media comments.

When users comment specific keywords (e.g. `PRICE`) on a creator's post, Engage Flow automatically ingests the webhook event, matches automation rules, and dispatches Direct Messages (DMs) to the commenter—even under high concurrency bursts, out-of-order delivery, transient server errors, and strict platform rate limits.

---

## Key Architectural Features

1. **Fast Webhook Ingestion (<20ms):** Validates HMAC-SHA256 signatures, persists events to disk immediately, and responds with `200 OK` in under 20ms to prevent dropped webhooks under burst load.
2. **Durable Outbox State Machine:** Every DM attempt is recorded as a job state in SQLite (`pending` $\rightarrow$ `sending` $\rightarrow$ `remote_queued` $\rightarrow$ `delivered` / `retry_wait` / `cancelled` / `failed`).
3. **Double-Layer Atomic Deduplication:** 
   - Event-level deduplication via `events.event_id` unique constraint.
   - User-rule deduplication via composite unique index `(user_id, rule_id)` preventing race conditions.
4. **Adaptive Rolling-Window Rate Limiter:** Strictly enforces a 10 requests per 60-second rolling window without deadlocking worker loops, while dynamically respecting `Retry-After` headers.
5. **Deletion Tombstones (`comment.deleted`):** Solves out-of-order deletion events by storing tombstones in `deleted_comments` to cancel pending DM jobs prior to dispatch.
6. **Delivery Reconciliation Engine:** Asynchronously polls the delivery status API to verify true terminal status (`delivered` or `failed`) instead of trusting transient acceptance responses.
7. **Crash-Proof Lease Recovery:** Jobs locked in `sending` status automatically revert to `pending` if a worker crashes before completion.

---

## API Endpoints

### 1. `POST /webhook`
Ingests comment events with HMAC-SHA256 signature verification (`X-PseudoGram-Signature`).

### 2. `POST /rules`
Registers a keyword automation rule.
```json
// Request
{ "keyword": "PRICE", "dm_message": "Here is the price list: https://example.com/prices" }

// Response (201 Created)
{ "rule_id": "rule_64ae4aa1afc5", "keyword": "PRICE", "dm_message": "..." }
```

### 3. `GET /stats`
Returns live metrics derived directly from database query aggregations:
```json
{
  "sent": 142,
  "failed": 3,
  "queued": 8,
  "duplicates_blocked": 57
}
```

---

## Tech Stack

- **Core:** Python 3.11+ | FastAPI | Uvicorn
- **HTTP Client:** `httpx` (async)
- **Database:** SQLite (WAL mode, `busy_timeout=5000`)
- **Testing:** `pytest`

---

## Getting Started

### 1. Installation
```bash
git clone https://github.com/akhil05-g/dm-automation.git
cd dm-automation
pip install -r requirements.txt
```

### 2. Environment Setup
Create a `.env` file in the root directory:
```env
PSEUDOGRAM_API_KEY=your_api_key_here
PSEUDOGRAM_BASE_URL=https://pseudogram-api.onrender.com
DATABASE_PATH=linkplease.db
```

### 3. Run Server
```bash
uvicorn app.main:app --reload --port 8000
```

### 4. Run Unit Tests
```bash
python -m pytest -v
```

---

## System Resilience & Failure Boundaries

For an explicit analysis of system boundaries, failure windows, and edge cases, see [FAILURES.md](FAILURES.md).