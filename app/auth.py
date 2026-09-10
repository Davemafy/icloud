from __future__ import annotations

import hashlib
import hmac
import time
import base64
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from fastapi import Header, HTTPException, Request

from .config import SETTINGS
from .db import DB


_RATE = defaultdict(deque)


def _rate_limit(identity: str):
    now = time.time()
    q = _RATE[identity]
    while q and q[0] < now - 60:
        q.popleft()
    if len(q) >= SETTINGS.rate_limit_per_minute:
        raise HTTPException(429, "Rate limit exceeded")
    q.append(now)


def require_admin(x_admin_key: str = Header(default="", alias="X-Admin-Key")) -> str:
    if not hmac.compare_digest(x_admin_key, SETTINGS.admin_api_key):
        raise HTTPException(401, "Unauthorized")
    _rate_limit("admin")
    return "admin"


def require_ea(
    request: Request,
    x_api_key: str = Header(default="", alias="X-API-Key"),
    x_timestamp: str = Header(default="", alias="X-Timestamp"),
    x_nonce: str = Header(default="", alias="X-Nonce"),
) -> str:
    if not hmac.compare_digest(x_api_key, SETTINGS.cloud_ea_api_key):
        raise HTTPException(401, "Unauthorized")
    _rate_limit(f"ea:{x_api_key[:6]}")

    try:
        ts = datetime.fromtimestamp(int(x_timestamp), tz=timezone.utc)
    except Exception as exc:
        raise HTTPException(401, "Missing/invalid timestamp") from exc
    now = datetime.now(timezone.utc)
    if abs((now - ts).total_seconds()) > SETTINGS.nonce_ttl_seconds:
        raise HTTPException(401, "Stale request")
    if not x_nonce or len(x_nonce) < 8 or len(x_nonce) > 128:
        raise HTTPException(401, "Invalid nonce")
    if DB.nonce_seen(x_nonce):
        raise HTTPException(409, "Replay detected")
    DB.remember_nonce(x_nonce, now.isoformat())
    DB.cleanup_nonces((now - timedelta(seconds=SETTINGS.nonce_ttl_seconds * 2)).isoformat())
    return "ea"


def verify_optional_hmac(raw_body: bytes, timestamp: str, nonce: str, signature: str) -> bool:
    if not signature:
        return False
    canonical = timestamp.encode() + b"\n" + nonce.encode() + b"\n" + raw_body
    expected = hmac.new(SETTINGS.signing_secret.encode(), canonical, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def create_dashboard_session_token(ttl_seconds: int = 43200) -> str:
    """Create a short-lived signed token for browser SSE authentication.

    EventSource cannot send custom X-Admin-Key headers, so the dashboard first
    authenticates over fetch(), then receives this HttpOnly cookie token.
    """
    exp = int(time.time()) + max(300, ttl_seconds)
    payload = str(exp)
    sig = hmac.new(SETTINGS.signing_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_dashboard_session_token(token: str) -> bool:
    try:
        exp_text, sig = token.split('.', 1)
        exp = int(exp_text)
    except Exception:
        return False
    if exp < int(time.time()):
        return False
    expected = hmac.new(SETTINGS.signing_secret.encode(), exp_text.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)
