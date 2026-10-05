"""
Admin access without a shared secret typed into a page.

An authorised person messages "admin" to the bot from their own WhatsApp number
and receives a single-use login link, which is exchanged for a signed HttpOnly
session cookie. Scripts may still send ADMIN_SECRET in the X-Admin-Token header.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Dict, Optional, Set, Tuple

from fastapi import HTTPException, Request

from config import Config

COOKIE_NAME = "ewas_admin"
LOGIN_LINK_TTL_S = 10 * 60
SESSION_TTL_S = 12 * 60 * 60
LINK_COOLDOWN_S = 60
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "admin-ui"

# In memory, one replica: a restart voids unused links and the admin asks for a new one.
_login_links: Dict[str, Tuple[str, float]] = {}
_last_link_at: Dict[str, float] = {}


def _digits(value: str) -> str:
    return "".join(c for c in value if c.isdigit())


def _admin_numbers() -> Set[str]:
    return {d for d in (_digits(n) for n in Config.ADMIN_PHONE_NUMBERS.split(",")) if d}


def is_admin_phone(phone: str) -> bool:
    return _digits(phone) in _admin_numbers()


def _key() -> bytes:
    return Config.ADMIN_SESSION_KEY.encode()


def _sign(text: str) -> str:
    return hmac.new(_key(), text.encode(), hashlib.sha256).hexdigest()


def _subject(phone: str) -> str:
    """Stable pseudonym for an admin; the phone number itself is never stored or logged."""
    return _sign("sub:" + _digits(phone))[:16]


def _prune(now: float) -> None:
    for k in [k for k, (_, exp) in _login_links.items() if exp < now]:
        del _login_links[k]


def create_login_link(phone: str, now: Optional[float] = None) -> Tuple[str, str]:
    """Return (status, url): status is "ok", "cooldown" or "disabled" (not an admin / not configured)."""
    now = time.time() if now is None else now
    if not (is_admin_phone(phone) and _key()):
        return "disabled", ""
    sub = _subject(phone)
    if now - _last_link_at.get(sub, 0.0) < LINK_COOLDOWN_S:
        return "cooldown", ""
    _prune(now)
    token = secrets.token_urlsafe(32)
    _login_links[hashlib.sha256(token.encode()).hexdigest()] = (sub, now + LOGIN_LINK_TTL_S)
    _last_link_at[sub] = now
    return "ok", f"{Config.ADMIN_PUBLIC_URL.rstrip('/')}/admin/login?t={token}"


def peek_login_token(token: str, now: Optional[float] = None) -> bool:
    entry = _login_links.get(hashlib.sha256(token.encode()).hexdigest())
    return bool(entry) and entry[1] >= (time.time() if now is None else now)


def consume_login_token(token: str, now: Optional[float] = None) -> Optional[str]:
    """Single use: returns the admin subject and invalidates the link."""
    entry = _login_links.pop(hashlib.sha256(token.encode()).hexdigest(), None)
    if not entry or entry[1] < (time.time() if now is None else now):
        return None
    return entry[0]


def make_session(sub: str, now: Optional[float] = None) -> str:
    now = time.time() if now is None else now
    payload = base64.urlsafe_b64encode(json.dumps({"sub": sub, "exp": int(now + SESSION_TTL_S)}).encode()).decode().rstrip("=")
    return payload + "." + _sign(payload)


def read_session(cookie: str, now: Optional[float] = None) -> Optional[str]:
    if not cookie or "." not in cookie or not _key():
        return None
    payload, _, signature = cookie.partition(".")
    if not hmac.compare_digest(signature.encode(), _sign(payload).encode()):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except ValueError:
        return None
    return data["sub"] if data.get("exp", 0) >= (time.time() if now is None else now) else None


def require_admin(request: Request) -> str:
    """Return the actor ("token" for the script header, else the admin's subject) or raise 401/403."""
    token = request.headers.get("X-Admin-Token", "")
    if Config.ADMIN_SECRET and token and hmac.compare_digest(token.encode(), Config.ADMIN_SECRET.encode()):
        return "token"
    sub = read_session(request.cookies.get(COOKIE_NAME, ""))
    if not sub:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if request.method not in ("GET", "HEAD") and request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise HTTPException(status_code=403, detail="Missing X-Requested-With header")
    return sub
