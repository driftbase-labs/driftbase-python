import uuid
from pathlib import Path

import requests


def is_telemetry_enabled():
    """Enterprise kill switch for GDPR/DORA compliance."""
    return False  # Disabled until driftbase-platform is live


def get_machine_id():
    """Retrieve or generate a persistent anonymous ID for this machine."""
    config_dir = Path.home() / ".driftbase"
    id_file = config_dir / "telemetry_id"

    if id_file.exists():
        return id_file.read_text().strip()

    config_dir.mkdir(parents=True, exist_ok=True)
    new_id = str(uuid.uuid4())
    id_file.write_text(new_id)
    return new_id


def push_trace(
    api_key: str,
    latency: int,
    tokens: dict,
    status: str = "success",
    endpoint: str = "http://localhost:3000/api/traces",
):
    """
    Push LLM execution metadata directly to the customer's secure vault.
    Strictly isolated from general product analytics.
    """
    if not is_telemetry_enabled():
        return

    try:
        requests.post(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"latency": latency, "status": status, "payload": tokens},
            timeout=1.5,  # Critical: Never block the host application if the vault is unreachable.
        )
    except requests.exceptions.RequestException:
        # Silent fail. The observability tool must never crash the client's production app.
        pass
