import json
import re


class PIIScrubber:
    PATTERNS = {
        "EMAIL": r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
        "IBAN": r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}",
        "BSN": r"\b\d{9}\b",
    }

    @classmethod
    def scrub(cls, data: dict) -> dict:
        payload_str = json.dumps(data)

        for pii_type, pattern in cls.PATTERNS.items():
            payload_str = re.sub(pattern, f"[REDACTED_{pii_type}]", payload_str)

        return json.loads(payload_str)
