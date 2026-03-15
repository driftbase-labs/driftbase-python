import time
from functools import wraps

import requests


class Driftbase:
    def __init__(
        self, api_key: str, endpoint: str = "http://localhost:3000/api/traces"
    ):
        self.api_key = api_key
        self.endpoint = endpoint

    def observe(self, func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()

            # 1. Execute the actual LLM call
            response = func(*args, **kwargs)

            # 2. Calculate latency in milliseconds
            latency = int((time.time() - start_time) * 1000)

            # 3. Safely extract token usage (Assuming OpenAI object structure)
            try:
                usage = getattr(response, "usage", None)
                tokens = {
                    "total_tokens": getattr(usage, "total_tokens", 0),
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(usage, "completion_tokens", 0),
                }
            except Exception:
                tokens = {"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0}

            # 4. Fire-and-forget telemetry
            self._send_telemetry(latency, tokens)

            return response

        return wrapper

    def _send_telemetry(self, latency: int, tokens: dict):
        try:
            requests.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"latency": latency, "status": "success", "payload": tokens},
                timeout=1.5,  # Critical: Never block the client's application
            )
        except requests.exceptions.RequestException:
            # Silent fail. The observability tool must never crash the host app.
            pass
