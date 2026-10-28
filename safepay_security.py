"""Small, dependency-free helpers for Safepay webhook verification."""
from __future__ import annotations

import hashlib
import hmac
from typing import Optional


def verify_webhook_signature(raw_body: bytes, supplied_signature: Optional[str], secret: str) -> bool:
    """Verify a hex SHA-256 HMAC over the exact raw webhook body."""
    if not supplied_signature or not secret:
        return False
    signature = supplied_signature.strip()
    if signature.lower().startswith("sha256="):
        signature = signature[7:]
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.lower())
