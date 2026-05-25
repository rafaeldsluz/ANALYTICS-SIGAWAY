"""
Persistência SQLite para campanhas WhatsApp.
"""
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "whatsapp_campaign.db"
_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=MEMORY")
    return c


def init_db() -> None:
    with _lock:
        with _conn() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS wz_contacts (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id TEXT NOT NULL,
                    nome        TEXT DEFAULT '',
                    empresa     TEXT DEFAULT '',
                    phone       TEXT NOT NULL,
                    status      TEXT DEFAULT 'pending',
                    attempts    INTEGER DEFAULT 0,
                    sent_at     TEXT,
                    error_msg   TEXT,
                    created_at  TEXT DEFAULT (datetime('now','localtime'))
                )
            """)
            try:
                c.execute("ALTER TABLE wz_contacts ADD COLUMN empresa TEXT DEFAULT ''")
            except Exception:
                pass
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_wz_campaign ON wz_contacts(campaign_id)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_wz_status ON wz_contacts(campaign_id, status)"
            )


def get_all_sent_phones() -> set[str]:
    """Retorna todos os telefones já enviados com sucesso em qualquer campanha."""
    with _lock:
        with _conn() as c:
            rows = c.execute(
                "SELECT DISTINCT phone FROM wz_contacts WHERE status='sent'"
            ).fetchall()
    return {r["phone"] for r in rows}


def insert_contacts(campaign_id: str, contacts: list[dict]) -> tuple[int, int]:
    """
    Insere contatos na campanha.
    Contatos cujo telefone já foi enviado anteriormente entram como 'skipped'.
    Retorna (n_pending, n_skipped).
    """
    already_sent = get_all_sent_phones()
    pending_rows: list[tuple] = []
    skipped_rows: list[tuple] = []
    for r in contacts:
        phone   = r.get("phone", "")
        nome    = r.get("nome", "")
        empresa = r.get("empresa", "")
        if phone in already_sent:
            skipped_rows.append((campaign_id, nome, empresa, phone, "skipped"))
        else:
            pending_rows.append((campaign_id, nome, empresa, phone, "pending"))

    with _lock:
        with _conn() as c:
            c.executemany(
                "INSERT INTO wz_contacts (campaign_id, nome, empresa, phone, status) VALUES (?,?,?,?,?)",
                pending_rows + skipped_rows,
            )
    return len(pending_rows), len(skipped_rows)


def next_pending(campaign_id: str) -> dict | None:
    with _lock:
        with _conn() as c:
            row = c.execute(
                "SELECT * FROM wz_contacts "
                "WHERE campaign_id=? AND status='pending' "
                "ORDER BY id LIMIT 1",
                (campaign_id,),
            ).fetchone()
    return dict(row) if row else None


def mark_sent(contact_id: int) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _lock:
        with _conn() as c:
            c.execute(
                "UPDATE wz_contacts "
                "SET status='sent', sent_at=?, attempts=attempts+1 "
                "WHERE id=?",
                (ts, contact_id),
            )


def mark_failed(contact_id: int, error: str) -> None:
    with _lock:
        with _conn() as c:
            c.execute(
                "UPDATE wz_contacts "
                "SET status='failed', attempts=attempts+1, error_msg=? "
                "WHERE id=?",
                (error[:500], contact_id),
            )


def cancel_pending(campaign_id: str) -> None:
    with _lock:
        with _conn() as c:
            c.execute(
                "UPDATE wz_contacts SET status='cancelled' "
                "WHERE campaign_id=? AND status='pending'",
                (campaign_id,),
            )


def get_stats(campaign_id: str) -> dict:
    with _lock:
        with _conn() as c:
            rows = c.execute(
                "SELECT status, COUNT(*) as n FROM wz_contacts "
                "WHERE campaign_id=? GROUP BY status",
                (campaign_id,),
            ).fetchall()
    stats: dict[str, int] = {
        "total": 0, "pending": 0, "sent": 0, "failed": 0, "cancelled": 0, "skipped": 0
    }
    for r in rows:
        key = r["status"]
        if key in stats:
            stats[key] = r["n"]
        stats["total"] += r["n"]
    return stats
