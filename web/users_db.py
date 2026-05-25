"""
web/users_db.py — Gerenciamento de usuários do sistema.

Schema preparado para expansão futura:
  - reset_token / reset_expiry : recuperação de senha por e-mail
  - totp_secret                : autenticação 2FA (TOTP)
  - role                       : níveis de permissão (user, admin, master)
  - allowed_domains            : aprovação automática por domínio
"""
import sqlite3
import threading
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

_DB   = Path(__file__).parent.parent / "users.db"
_LOCK = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    UNIQUE NOT NULL COLLATE NOCASE,
    email         TEXT    UNIQUE NOT NULL COLLATE NOCASE,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'user',
    status        TEXT    NOT NULL DEFAULT 'pending',
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    approved_at   DATETIME,
    approved_by   TEXT,
    last_login    DATETIME,
    notes         TEXT    DEFAULT '',
    reset_token   TEXT    DEFAULT NULL,
    reset_expiry  DATETIME DEFAULT NULL,
    totp_secret   TEXT    DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_email    ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_status   ON users(status);
"""


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(_DB), timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db():
    with _LOCK:
        with _conn() as c:
            c.executescript(_SCHEMA)


# ── Criação ───────────────────────────────────────────────────────────────────

def create_user(username: str, email: str, password: str) -> dict:
    """Cria usuário com status 'pending'. Retorna {'ok': True} ou {'error': str}."""
    pw_hash = generate_password_hash(password, method="pbkdf2:sha256")
    try:
        with _LOCK:
            with _conn() as c:
                c.execute(
                    "INSERT INTO users (username, email, password_hash) VALUES (?,?,?)",
                    (username.strip(), email.strip().lower(), pw_hash),
                )
                c.commit()
        return {"ok": True}
    except sqlite3.IntegrityError as e:
        err = str(e).lower()
        if "username" in err:
            return {"error": "Nome de usuário já cadastrado."}
        if "email" in err:
            return {"error": "E-mail já cadastrado."}
        return {"error": "Dados já existentes."}


def create_invited_user(username: str, email: str) -> dict:
    """
    Cria usuário convidado pelo admin (status='invited', sem senha definida).
    Retorna {'ok': True, 'user_id': int, 'token': str} ou {'error': str}.
    """
    import secrets
    from datetime import datetime, timedelta

    placeholder = generate_password_hash(secrets.token_hex(32), method="pbkdf2:sha256")
    try:
        with _LOCK:
            with _conn() as c:
                c.execute(
                    "INSERT INTO users (username, email, password_hash, status) VALUES (?,?,?,?)",
                    (username.strip(), email.strip().lower(), placeholder, "invited"),
                )
                user_id = c.lastrowid
                c.commit()
    except sqlite3.IntegrityError as e:
        err = str(e).lower()
        if "username" in err:
            return {"error": "Nome de usuário já cadastrado."}
        if "email" in err:
            return {"error": "E-mail já cadastrado."}
        return {"error": "Dados já existentes."}

    token  = secrets.token_urlsafe(32)
    expiry = (datetime.utcnow() + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    set_reset_token(user_id, token, expiry)
    return {"ok": True, "user_id": user_id, "token": token}


# ── Consultas ─────────────────────────────────────────────────────────────────

def get_by_username(username: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM users WHERE username=?", (username.strip(),)
        ).fetchone()
    return dict(row) if row else None


def get_by_id(user_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_all(status: str | None = None) -> list[dict]:
    with _conn() as c:
        if status:
            rows = c.execute(
                "SELECT * FROM users WHERE status=? ORDER BY created_at DESC", (status,)
            ).fetchall()
        else:
            rows = c.execute(
                """SELECT * FROM users
                   ORDER BY CASE status
                     WHEN 'pending'  THEN 0
                     WHEN 'approved' THEN 1
                     ELSE 2 END,
                   created_at DESC"""
            ).fetchall()
    return [dict(r) for r in rows]


def get_stats() -> dict:
    with _conn() as c:
        total    = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        pending  = c.execute("SELECT COUNT(*) FROM users WHERE status='pending'").fetchone()[0]
        approved = c.execute("SELECT COUNT(*) FROM users WHERE status='approved'").fetchone()[0]
        rejected = c.execute("SELECT COUNT(*) FROM users WHERE status='rejected'").fetchone()[0]
    return {"total": total, "pending": pending, "approved": approved, "rejected": rejected}


# ── Ações de aprovação ────────────────────────────────────────────────────────

def approve_user(user_id: int, by: str) -> bool:
    with _LOCK:
        with _conn() as c:
            n = c.execute(
                "UPDATE users SET status='approved', approved_at=CURRENT_TIMESTAMP,"
                " approved_by=? WHERE id=?",
                (by, user_id),
            ).rowcount
            c.commit()
    return n > 0


def reject_user(user_id: int, by: str, notes: str = "") -> bool:
    with _LOCK:
        with _conn() as c:
            n = c.execute(
                "UPDATE users SET status='rejected', approved_by=?, notes=? WHERE id=?",
                (by, notes[:500], user_id),
            ).rowcount
            c.commit()
    return n > 0


def delete_user(user_id: int) -> bool:
    with _LOCK:
        with _conn() as c:
            n = c.execute("DELETE FROM users WHERE id=?", (user_id,)).rowcount
            c.commit()
    return n > 0


def promote_user(user_id: int, role: str) -> bool:
    if role not in ("user", "admin"):
        return False
    with _LOCK:
        with _conn() as c:
            n = c.execute(
                "UPDATE users SET role=? WHERE id=?", (role, user_id)
            ).rowcount
            c.commit()
    return n > 0


# ── Reset de senha ────────────────────────────────────────────────────────────

def set_reset_token(user_id: int, token: str, expiry: str) -> None:
    with _LOCK:
        with _conn() as c:
            c.execute(
                "UPDATE users SET reset_token=?, reset_expiry=? WHERE id=?",
                (token, expiry, user_id),
            )
            c.commit()


def get_by_reset_token(token: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM users WHERE reset_token=?", (token,)
        ).fetchone()
    return dict(row) if row else None


def clear_reset_token(user_id: int) -> None:
    with _LOCK:
        with _conn() as c:
            c.execute(
                "UPDATE users SET reset_token=NULL, reset_expiry=NULL WHERE id=?",
                (user_id,),
            )
            c.commit()


def update_password(user_id: int, new_password: str) -> None:
    from werkzeug.security import generate_password_hash
    pw_hash = generate_password_hash(new_password, method="pbkdf2:sha256")
    with _LOCK:
        with _conn() as c:
            c.execute(
                "UPDATE users SET password_hash=? WHERE id=?", (pw_hash, user_id)
            )
            c.commit()


# ── Login ─────────────────────────────────────────────────────────────────────

def verify_password(user: dict, password: str) -> bool:
    return check_password_hash(user["password_hash"], password)


def record_login(user_id: int):
    with _LOCK:
        with _conn() as c:
            c.execute(
                "UPDATE users SET last_login=CURRENT_TIMESTAMP WHERE id=?", (user_id,)
            )
            c.commit()
