import httpx
from typing import Dict, Any, Tuple
from app.config import PSEUDOGRAM_BASE_URL, PSEUDOGRAM_API_KEY

class PseudoGramClient:
    def __init__(self, base_url: str = PSEUDOGRAM_BASE_URL, api_key: str = PSEUDOGRAM_API_KEY):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    async def send_dm(
        self, recipient_user_id: str, message: str,
        comment_id: str, idempotency_key: str
    ) -> Tuple[int, Dict[str, Any], Dict[str, str]]:
        """POST /v1/dm/send. Returns (status_code, body, headers)."""
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": self.api_key,
            "Idempotency-Key": idempotency_key
        }
        payload = {
            "recipient_user_id": recipient_user_id,
            "message": message,
            "comment_id": comment_id
        }
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/v1/dm/send",
                    json=payload,
                    headers=headers
                )
                try:
                    data = response.json()
                except Exception:
                    data = {"raw_text": response.text}
                return response.status_code, data, dict(response.headers)
            except Exception as e:
                return 500, {"error": "connection_error", "detail": str(e)}, {}

    async def get_dm_status(self, dm_id: str) -> Tuple[int, Dict[str, Any]]:
        """GET /v1/dm/{dm_id}. Reads don't count against rate limit."""
        headers = {"X-API-Key": self.api_key}
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(
                    f"{self.base_url}/v1/dm/{dm_id}",
                    headers=headers
                )
                try:
                    data = response.json()
                except Exception:
                    data = {"raw_text": response.text}
                return response.status_code, data
            except Exception as e:
                return 500, {"error": "connection_error", "detail": str(e)}

pseudogram_client = PseudoGramClient()
