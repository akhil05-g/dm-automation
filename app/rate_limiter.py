import asyncio
import time
from collections import deque
from app.config import RATE_LIMIT_MAX_REQUESTS, RATE_LIMIT_WINDOW_SECONDS

class RollingWindowRateLimiter:
    def __init__(self, max_requests: int = RATE_LIMIT_MAX_REQUESTS, window_seconds: float = RATE_LIMIT_WINDOW_SECONDS):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.timestamps: deque[float] = deque()
        self.retry_after_until: float = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """
        Wait until a slot is available under the rolling window constraint.
        Releases the lock during sleep so other coroutines aren't blocked.
        """
        while True:
            wait_time = 0.0
            async with self._lock:
                now = time.time()

                # Check 429 Retry-After cooldown
                if now < self.retry_after_until:
                    wait_time = self.retry_after_until - now + 0.1
                else:
                    # Evict timestamps outside the rolling window
                    while self.timestamps and (now - self.timestamps[0]) >= self.window_seconds:
                        self.timestamps.popleft()

                    if len(self.timestamps) < self.max_requests:
                        self.timestamps.append(now)
                        return  # slot acquired

                    # Window full, calculate how long until a slot opens
                    oldest = self.timestamps[0]
                    wait_time = (oldest + self.window_seconds) - now + 0.1

            # Sleep OUTSIDE the lock so other coroutines can proceed
            if wait_time > 0:
                await asyncio.sleep(wait_time)

    async def report_rate_limited(self, retry_after_seconds: float = 60.0) -> None:
        """Called when we receive a 429. Pauses all sends for the given duration."""
        async with self._lock:
            now = time.time()
            self.retry_after_until = max(self.retry_after_until, now + retry_after_seconds)

rate_limiter = RollingWindowRateLimiter()

# Rolling window rate limiter verified
