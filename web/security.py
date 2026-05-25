"""
web/security.py — Central security module
OWASP-aligned middleware: headers, rate limiting, input validation,
audit logging, SSRF/redirect prevention, upload validation.
"""
import html
import ipaddress
import logging
import re
import sqlite3
import threading
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Optional
from functools import wraps

from flask import Flask, Response, g, jsonify, request

_logger = logging.getLogger("sigaway.security")

# ──────────────────────────────────────────────────────────────────────────────
# Audit log (SQLite)
# ──────────────────────────────────────────────────────────────────────────────
_AUDIT_DB   = Path(__file__).parent.parent / "security_audit.db"
_AUDIT_LOCK = threading.Lock()

_AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         DATETIME DEFAULT CURRENT_TIMESTAMP,
    level      TEXT NOT NULL,
    event      TEXT NOT NULL,
    ip         TEXT DEFAULT '',
    path       TEXT DEFAULT '',
    method     TEXT DEFAULT '',
    user_agent TEXT DEFAULT '',
    detail     TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_audit_ts    ON audit_events(ts DESC);
CREATE INDEX IF NOT EXISTS idx_audit_level ON audit_events(level);
CREATE INDEX IF NOT EXISTS idx_audit_event ON audit_events(event);
"""


def _audit_conn():
    c = sqlite3.connect(str(_AUDIT_DB), timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _init_audit():
    with _AUDIT_LOCK:
        with _audit_conn() as c:
            c.executescript(_AUDIT_SCHEMA)
            c.commit()


def audit(level: str, event: str, detail: str = ""):
    """Persist a security event. Thread-safe. Safe to call outside request context."""
    ip = method = path = ua = ""
    try:
        ip     = request.remote_addr or ""
        path   = request.path or ""
        method = request.method or ""
        ua     = (request.headers.get("User-Agent") or "")[:200]
    except RuntimeError:
        pass  # outside request context

    with _AUDIT_LOCK:
        try:
            with _audit_conn() as c:
                c.execute(
                    "INSERT INTO audit_events "
                    "(level,event,ip,path,method,user_agent,detail) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (level, event, ip, path, method, ua, str(detail)[:500]),
                )
                c.commit()
        except Exception as e:
            _logger.error("Audit write failed: %s", e)

    lvl = {"INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}.get(level, 20)
    _logger.log(lvl, "[AUDIT] %s %s ip=%s path=%s %s", level, event, ip, path, detail)


def get_audit_events(limit: int = 300, level: Optional[str] = None) -> list[dict]:
    with _audit_conn() as c:
        if level:
            rows = c.execute(
                "SELECT * FROM audit_events WHERE level=? ORDER BY id DESC LIMIT ?",
                (level, limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM audit_events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
    return [dict(r) for r in rows]


def get_audit_stats() -> dict:
    with _audit_conn() as c:
        total     = c.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        warnings  = c.execute(
            "SELECT COUNT(*) FROM audit_events WHERE level IN ('WARNING','ERROR','CRITICAL')"
        ).fetchone()[0]
        blocked   = c.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event='RATE_LIMIT_EXCEEDED'"
        ).fetchone()[0]
        last24h   = c.execute(
            "SELECT COUNT(*) FROM audit_events "
            "WHERE ts >= datetime('now','-24 hours')"
        ).fetchone()[0]
        top_events = c.execute(
            "SELECT event, COUNT(*) AS cnt FROM audit_events "
            "GROUP BY event ORDER BY cnt DESC LIMIT 10"
        ).fetchall()
    return {
        "total":      total,
        "warnings":   warnings,
        "blocked":    blocked,
        "last24h":    last24h,
        "top_events": [dict(r) for r in top_events],
    }


# ──────────────────────────────────────────────────────────────────────────────
# Rate limiter
# ──────────────────────────────────────────────────────────────────────────────
class _RateLimiter:
    """Sliding-window in-memory rate limiter keyed by (ip, scope)."""

    def __init__(self):
        self._windows:  dict[str, list[float]] = defaultdict(list)
        self._blocked:  dict[str, float]        = {}
        self._violations: dict[str, int]        = defaultdict(int)
        self._lock = threading.Lock()

    def check(self, key: str, max_requests: int, window_s: int) -> tuple[bool, int]:
        """Returns (allowed, remaining_capacity)."""
        now = time.monotonic()
        with self._lock:
            if key in self._blocked:
                if now < self._blocked[key]:
                    return False, 0
                del self._blocked[key]
                self._violations[key] = 0

            cutoff = now - window_s
            w = self._windows[key]
            # Remove expired timestamps
            while w and w[0] < cutoff:
                w.pop(0)

            if len(w) >= max_requests:
                self._violations[key] += 1
                return False, 0

            w.append(now)
            return True, max_requests - len(w)

    def block(self, key: str, duration_s: int = 300):
        with self._lock:
            self._blocked[key] = time.monotonic() + duration_s
        audit("WARNING", "IP_BLOCKED", f"key={key} duration={duration_s}s")

    def violations(self, key: str) -> int:
        with self._lock:
            return self._violations.get(key, 0)

    def cleanup(self):
        now = time.monotonic()
        with self._lock:
            expired = [k for k, v in self._blocked.items() if now > v]
            for k in expired:
                del self._blocked[k]


_limiter = _RateLimiter()


def rate_limit(
    max_requests: int,
    window_s: int = 60,
    scope: str = "",
    auto_block_after: int = 5,
    block_duration_s: int = 600,
):
    """
    Decorator: limit requests to max_requests per window_s seconds per IP.
    After auto_block_after violations, IP is blocked for block_duration_s.
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            ip  = request.remote_addr or "0.0.0.0"
            key = f"{ip}:{scope or f.__name__}"
            allowed, _ = _limiter.check(key, max_requests, window_s)
            if not allowed:
                audit("WARNING", "RATE_LIMIT_EXCEEDED",
                      f"endpoint={f.__name__} ip={ip}")
                viol = _limiter.violations(key)
                if auto_block_after and viol >= auto_block_after:
                    _limiter.block(key, block_duration_s)
                return (
                    jsonify({"error": "Muitas requisições. Tente novamente mais tarde."}),
                    429,
                    {"Retry-After": str(window_s)},
                )
            return f(*args, **kwargs)
        return wrapper
    return decorator


# ──────────────────────────────────────────────────────────────────────────────
# Input sanitization and validation
# ──────────────────────────────────────────────────────────────────────────────
_RE_SAFE_STR = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')  # control chars


def sanitize_str(value, max_len: int = 500) -> str:
    """Escape HTML, strip control characters, truncate."""
    if value is None:
        return ""
    s = str(value).strip()
    s = _RE_SAFE_STR.sub("", s)
    s = html.escape(s, quote=True)
    return s[:max_len]


def sanitize_int(value, default: int = 0, min_v: int = 0, max_v: int = 100_000) -> int:
    """Parse integer with bounds. Returns default on error."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    return max(min_v, min(max_v, v))


def sanitize_email(value: str) -> str:
    """Basic email normalization + length guard."""
    s = str(value or "").strip().lower()
    if len(s) > 254 or "@" not in s:
        return ""
    # RFC 5321: local part max 64 chars
    local, _, domain = s.partition("@")
    if len(local) > 64 or len(domain) > 253 or "." not in domain:
        return ""
    return s


def sanitize_cnpj(value: str) -> str:
    """Keep only digits (or MAPS_ prefix) from a CNPJ-ish string."""
    s = str(value or "").strip()
    if s.startswith("MAPS_"):
        return s[:25]
    digits = re.sub(r"\D", "", s)
    return digits[:18]


# ──────────────────────────────────────────────────────────────────────────────
# Redirect / SSRF URL validation
# ──────────────────────────────────────────────────────────────────────────────
_PRIVATE_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
]
_BLOCKED_HOSTS = frozenset({"localhost", "metadata.google.internal", "169.254.169.254"})


def validate_redirect_url(url: str) -> bool:
    """
    Return True only for safe public http(s) URLs.
    Blocks: localhost, private IPs, metadata services, non-http schemes.
    """
    if not url:
        return False
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return False
    try:
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or "").lower()
        if not host or host in _BLOCKED_HOSTS:
            return False
        try:
            addr = ipaddress.ip_address(host)
            if any(addr in net for net in _PRIVATE_RANGES):
                return False
            if addr.is_loopback or addr.is_private or addr.is_link_local:
                return False
        except ValueError:
            pass  # hostname, not raw IP — fine
        return True
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────────────────────
# File upload validation
# ──────────────────────────────────────────────────────────────────────────────
_ALLOWED_EXTENSIONS = {".xlsx", ".xls"}
_MAX_UPLOAD_BYTES   = 10 * 1024 * 1024  # 10 MB

# Excel magic bytes (PK header for xlsx; D0CF11E0 for xls)
_MAGIC = {
    b"\x50\x4b\x03\x04": ".xlsx",  # ZIP/OOXML
    b"\xd0\xcf\x11\xe0": ".xls",   # OLE2 compound
}


def validate_file_upload(file_storage, max_bytes: int = _MAX_UPLOAD_BYTES) -> tuple[bool, str]:
    """
    Validate Excel upload: extension, size, and magic bytes.
    Returns (valid, error_message).
    """
    if not file_storage or not file_storage.filename:
        return False, "Nenhum arquivo enviado."

    ext = Path(file_storage.filename).suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        return False, f"Extensão '{ext}' não permitida. Use .xlsx ou .xls."

    # Size check
    file_storage.seek(0, 2)
    size = file_storage.tell()
    file_storage.seek(0)
    if size == 0:
        return False, "Arquivo vazio."
    if size > max_bytes:
        return False, f"Arquivo muito grande (máx {max_bytes // (1024*1024)} MB)."

    # Magic bytes check
    magic = file_storage.read(4)
    file_storage.seek(0)
    if magic not in _MAGIC:
        audit("WARNING", "UPLOAD_INVALID_MAGIC",
              f"file={file_storage.filename} magic={magic.hex()}")
        return False, "Arquivo inválido (assinatura de bytes inesperada)."

    return True, ""


# ──────────────────────────────────────────────────────────────────────────────
# HTTP Security headers
# ──────────────────────────────────────────────────────────────────────────────
_CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline' cdn.jsdelivr.net",
    "style-src 'self' 'unsafe-inline' fonts.googleapis.com fonts.gstatic.com",
    "font-src 'self' fonts.gstatic.com data:",
    "img-src 'self' data: blob:",
    "connect-src 'self'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
])


def _apply_security_headers(response: Response) -> Response:
    h = response.headers
    h["X-Frame-Options"]          = "DENY"
    h["X-Content-Type-Options"]   = "nosniff"
    h["X-XSS-Protection"]         = "1; mode=block"
    h["Referrer-Policy"]          = "strict-origin-when-cross-origin"
    h["Content-Security-Policy"]  = _CSP
    h["Permissions-Policy"]       = "geolocation=(), microphone=(), camera=(), payment=()"
    h["X-Request-ID"]             = getattr(g, "_req_id", "")
    # Remove server fingerprinting
    h.remove("Server")
    h.remove("X-Powered-By")
    return response


# ──────────────────────────────────────────────────────────────────────────────
# Request lifecycle hooks
# ──────────────────────────────────────────────────────────────────────────────
def _before_request():
    g._req_id    = uuid.uuid4().hex[:12]
    g._req_start = time.monotonic()

    # Log sensitive operations
    _SENSITIVE = (
        "/email/start", "/email/upload-excel", "/email/test-email",
        "/leads/start", "/leads/maps-start",
        "/whatsapp/start",
        "/sdr/webhook",
    )
    if any(request.path.startswith(p) for p in _SENSITIVE):
        audit("INFO", "SENSITIVE_ACCESS")


def _after_request(response: Response) -> Response:
    _apply_security_headers(response)

    # Log errors
    if response.status_code >= 400:
        elapsed = int((time.monotonic() - getattr(g, "_req_start", time.monotonic())) * 1000)
        lvl = "ERROR" if response.status_code >= 500 else "WARNING"
        audit(lvl, f"HTTP_{response.status_code}", f"elapsed_ms={elapsed}")

    return response


# ──────────────────────────────────────────────────────────────────────────────
# Flask integration
# ──────────────────────────────────────────────────────────────────────────────
def init_security(app: Flask):
    """Register all security middleware on the Flask application."""
    _init_audit()

    # Hard limit on request body size (protects all endpoints)
    app.config.setdefault("MAX_CONTENT_LENGTH", 10 * 1024 * 1024)

    app.before_request(_before_request)
    app.after_request(_after_request)

    # Periodic limiter cleanup
    def _cleanup():
        while True:
            time.sleep(1800)
            _limiter.cleanup()

    threading.Thread(target=_cleanup, daemon=True, name="sec-cleanup").start()

    audit("INFO", "SECURITY_INIT", "Middleware registered")
    _logger.info("Security module initialized.")
