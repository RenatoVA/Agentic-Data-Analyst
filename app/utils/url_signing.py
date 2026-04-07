from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from urllib.parse import urlencode


def _compute_signature(secret: str, user_id: str, file_path: str, expires: int) -> str:
    message = f"{user_id}:{file_path}:{expires}"
    return hmac.new(
        secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def generate_signed_url(
    *,
    secret: str,
    user_id: str,
    file_path: str,
    expires_in: int = 3600,
) -> str:
    """Return a signed URL path: /files/{user_id}/{file_path}?token=...&expires=..."""
    expires = int(time.time()) + expires_in
    url_file_path = file_path.replace("\\", "/")
    token = _compute_signature(secret, user_id, url_file_path, expires)
    query = urlencode({"token": token, "expires": str(expires)})
    return f"/files/{user_id}/{url_file_path}?{query}"


def verify_signed_url(
    *,
    secret: str,
    user_id: str,
    file_path: str,
    token: str,
    expires: int,
) -> bool:
    """Return True if the token is valid and not expired."""
    if int(time.time()) > expires:
        return False
    expected = _compute_signature(secret, user_id, file_path, expires)
    return hmac.compare_digest(token, expected)


def generate_secret() -> str:
    return secrets.token_hex(32)
