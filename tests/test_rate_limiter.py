import asyncio
import time
from app.rate_limiter import RollingWindowRateLimiter

def test_rate_limiter_allows_up_to_max():
    async def run_test():
        limiter = RollingWindowRateLimiter(max_requests=5, window_seconds=1.0)
        start = time.time()
        
        # 5 requests should acquire immediately
        for _ in range(5):
            await limiter.acquire()
            
        duration = time.time() - start
        assert duration < 0.2
        
        # 6th request should wait until 1.0s window passes
        await limiter.acquire()
        total_duration = time.time() - start
        assert total_duration >= 0.9

    asyncio.run(run_test())
