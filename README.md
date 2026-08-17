# LinkPlease Tech Intern — Assignment

**Stack:** Anything. We use Python and React internally, but we do not care what you use. We use python, flask/fastAPI

**AI tools:** Use all of them. We use them every day. The only rule is that you can explain every line you shipped.

---

## What you're building

LinkPlease automates Instagram for creators. Someone comments `PRICE` on a creator's post, and we DM them the price list. Millions of times a month.

You're building a small version of that, on top of a mock Instagram API we've built for this assignment.

The mock API is deliberately hostile. It fails, it rate-limits, it delivers events out of order and sometimes twice, and it occasionally reports success on a DM that never got delivered. That is not us being clever — that is a lightly toned-down version of what a real platform API is like. Handling it is the assignment.

---

## Scope

**Part A — required.**
- A user can create a rule: when a comment contains a keyword, DM that commenter a message.
- Incoming comments get matched against rules and the right person gets the right DM.
- The same user never gets DMed twice for the same rule, no matter how many times they comment.
- No DM is silently lost when the API fails.

**Part B — do this if you have time.**
- Verify webhook signatures and reject forged requests.
- `GET /stats` reports accurate live numbers under load.

**Part C — if you want to show off.**
- Reconcile delivery status. A DM the API accepted may still fail later. Catch those and retry them.
- Handle `comment.deleted` events sensibly.
- 500 comments arriving in 10 seconds, nothing lost, rate limit never breached.

If you only finish Part A, submit Part A. A clean Part A beats a broken Part C.

---

## Non-negotiable: your API contract

We grade submissions with an automated script that hits your deployed URL. If these three routes don't exist at these exact paths with these exact shapes, the script scores you zero and no human ever sees your work. Please re-read this section before you submit.

### `POST /webhook`

Receives comment events from us. Must return `200` within 5 seconds. (Do the real work in the background — if you block here, you will start dropping events.)

### `POST /rules`

```json
// Request
{ "keyword": "PRICE", "dm_message": "Here's the price list: ..." }

// Response 201
{ "rule_id": "any-string-you-like", "keyword": "PRICE", "dm_message": "..." }
```

Keyword matching is case-insensitive and matches anywhere in the comment text.

### `GET /stats`

```json
{
  "sent": 142,
  "failed": 3,
  "queued": 8,
  "duplicates_blocked": 57
}
```

- `sent` — DMs the mock API confirmed as delivered
- `failed` — you gave up after retries
- `queued` — waiting to send or waiting on a retry
- `duplicates_blocked` — DMs you correctly chose not to send

We compare these against our server-side logs. Inflated numbers are worse than honest low numbers.

---

## The mock API

**Base URL:** `https://pseudogram-api.onrender.com`

### Getting your API key

Two steps, both quick:

1. **Apply** — POST this to `https://pseudogram-api.onrender.com/v1/apply`:
   ```json
   {
     "name": "your name",
     "email": "you@example.com",
     "phone": "+91...",
     "whatsapp": "+91...",
     "linkedin_url": "https://linkedin.com/in/you"
   }
   ```
   `whatsapp` is optional if it's the same as your phone number. Everything else is required.
2. **Get your key** — once you've applied, `POST /v1/keygen` on the base URL above with the same email:
   ```json
   { "email": "you@example.com" }
   // Response: { "api_key": "...", "email": "you@example.com" }
   ```
   If step 1 hasn't gone through yet, this returns a `403`. Just means you haven't applied — do step 1 first.

Send your key as `X-API-Key` on every request below. Everything is scoped to your key. Nobody else's traffic affects yours, and your rate limit is yours alone.

### Webhook payload

We POST this to your `/webhook`:

```json
{
  "event_id": "evt_01J8ZQ4K2N7RXA",
  "event_type": "comment.created",
  "sent_at": "2026-08-10T09:14:22.481Z",
  "data": {
    "comment_id": "cmt_9f2a7c",
    "post_id": "post_44de1b",
    "text": "PRICE please 🙏",
    "created_at": "2026-08-10T09:14:21.900Z",
    "from": {
      "user_id": "usr_3b91fe",
      "username": "arjun.shoots"
    }
  }
}
```

Header: `X-PseudoGram-Signature: sha256=<hex>` — HMAC-SHA256 of the **raw request body** using your API key as the secret.

Four things that are true about this stream, and are not bugs:

1. **`event_id` can repeat.** We redeliver roughly 8% of events. Same `event_id`, sometimes seconds apart, sometimes minutes.
2. **Order is not guaranteed.** `sent_at` will not always match arrival order.
3. **`user_id` is the identity, not `username`.** Usernames change.
4. **`comment.deleted` events exist.** Payload is the same shape with `event_type: "comment.deleted"` and only `comment_id` populated in `data`. Think about what should happen if it arrives before you've sent the DM.

### `POST /v1/dm/send`

```json
// Request
{
  "recipient_user_id": "usr_3b91fe",
  "message": "Here's the price list: ...",
  "comment_id": "cmt_9f2a7c"
}

// 202 Accepted
{ "dm_id": "dm_7c1f0a", "status": "queued" }
```

Note the status. `202` means **accepted**, not **delivered**. Roughly 15% of accepted DMs end up as `failed`. You only find out by checking.

Other responses:

| Code | Body | Meaning |
|---|---|---|
| `429` | `{"error": "rate_limited"}` | 10 requests per rolling 60s exceeded. `Retry-After` header gives seconds. |
| `500` | `{"error": "internal_error"}` | Random, ~20% of calls. Safe to retry. |
| `400` | `{"error": "invalid_request", "detail": "..."}` | Your payload is malformed. Retrying will not help. |

Optional header: `Idempotency-Key`. If you send the same key twice we return the original `dm_id` instead of sending again. You may find this useful.

### `GET /v1/dm/{dm_id}`

```json
{
  "dm_id": "dm_7c1f0a",
  "status": "delivered",
  "recipient_user_id": "usr_3b91fe",
  "updated_at": "2026-08-10T09:14:31.002Z"
}
```

`status` is one of `queued`, `delivered`, `failed`. Terminal statuses are `delivered` and `failed`. Reads do not count against your rate limit.

### `POST /v1/simulate/start` — test yourself

```json
{ "webhook_url": "https://your-app.example.com/webhook", "count": 500, "duration_seconds": 10 }
```

Fires `count` comment events at your URL over `duration_seconds`. Use it as much as you want. Returns a `run_id`.

### `GET /v1/simulate/{run_id}/truth`

Returns exactly what we sent — every event, which were duplicates, which users matched which keywords. Check your own work against it before submitting. We use the same data.

---

## What to submit

POST to `https://pseudogram-api.onrender.com/v1/submit`:

```json
{
  "email": "you@example.com",
  "github_repo": "https://github.com/you/repo",
  "working_url": "https://your-app.example.com",
  "loom_url": "https://loom.com/share/...",
  "parts_completed": "A+B",
  "start_date": "2026-08-25"
}
```

- **`email`** — same one you applied with. (If you only kept your API key, send `api_key` instead of `email` — we can identify you from it.)
- **`github_repo`** — public repo. Must contain `FAILURES.md` in the root (see below).
- **`working_url`** — your deployed base URL. **Must stay live for 7 days after the deadline.** A dead link is a zero and we won't chase you.
- **`loom_url`** — 3 minutes, see below.
- **`parts_completed`** — `A`, `A+B`, or `A+B+C`.
- **`start_date`** — your honest start date, assuming 5 days a week.

You can submit more than once — resubmitting with the same email overwrites your previous submission, so send an early draft link if you want, then the real one later.

### `FAILURES.md` — the part that actually matters

List every way your system can still lose a DM, send a duplicate, or report a wrong number. Be specific about the conditions under which it happens.

Something like:

> If the process restarts while a retry is scheduled in memory, that DM is lost. Nothing on disk knows it was pending.

> Two events with the same `event_id` arriving within ~50ms can both pass the duplicate check before either writes, so both send. I know this because I saw it twice during a 500-event run.

Write four honest bullets. "Handles all edge cases with robust error handling" tells us you didn't test it, and we will find out in about ninety seconds.

There is no penalty for a long list. There is a real penalty for a dishonest short one.

### The Loom

Three minutes, screen + voice, no editing needed. Answer two questions:

1. One tradeoff you made, and what you gave up by making it.
2. What you'd do differently with one more week.

Talk normally. We're not looking for polish, we're looking for whether you understand the thing you built.

---

## How we grade

| Stage | What happens |
|---|---|
| 1 | Automated script runs 500 events at your URL, checks `/stats` against our server-side truth |
| 2 | We read `FAILURES.md` |
| 3 | We watch the Loom |
| 4 | We call you |

We ignore your choice of stack, your UI, your commit count, and your college. We care that it works, that you know where it doesn't, and that you can explain it.

---

## Deadline

**17th Aug 2026, 11:59 PM IST.**


Questions: comment on the LinkedIn post rather than DMing. If one person is confused, ten are, and the answer helps everyone.

— Ayush