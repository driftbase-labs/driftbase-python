import os
import threading
import time
from functools import wraps

import requests

# Defaults to your local Next.js vault.
# Override this with DRIFTBASE_ENDPOINT in production.
DRIFTBASE_URL = os.getenv("DRIFTBASE_ENDPOINT", "http://localhost:3000/api/traces")


def _dispatch_telemetry(payload, api_key):
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        requests.post(DRIFTBASE_URL, json=payload, headers=headers, timeout=1.5)
    except Exception:
        # Silent fail. Never crash the customer's host application.
        pass


def track(model: str):
    """
    Decorator to automatically track LLM latency, token usage, and payloads.
    Fires telemetry to the designated Driftbase vault asynchronously.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            api_key = os.getenv("DRIFTBASE_API_KEY")

            # 1. Start execution timer
            start_time = time.time()

            # 2. Execute the user's actual LLM function
            response = func(*args, **kwargs)

            # 3. Calculate exact latency
            latency = int((time.time() - start_time) * 1000)

            if not api_key:
                print(
                    "[Driftbase] Warning: DRIFTBASE_API_KEY missing. Skipping telemetry."
                )
                return response

            # 4. Extract payload data
            messages = kwargs.get("messages", [])
            if not messages and args:
                messages = [{"role": "user", "content": str(args[0])}]

            # Safely extract OpenAI response properties
            try:
                content = response.choices[0].message.content
                prompt_tokens = response.usage.prompt_tokens
                completion_tokens = response.usage.completion_tokens
                total_tokens = response.usage.total_tokens
            except AttributeError:
                content = str(response)
                prompt_tokens = 0
                completion_tokens = 0
                total_tokens = 0

            payload = {
                "status": "success",
                "latency": latency,
                "payload": {
                    "model": model,
                    "messages": messages,
                    "response": content,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                },
            }

            # 5. Dispatch to the vault via background thread (non-blocking)
            threading.Thread(
                target=_dispatch_telemetry, args=(payload, api_key), daemon=True
            ).start()

            return response

        return wrapper

    return decorator
