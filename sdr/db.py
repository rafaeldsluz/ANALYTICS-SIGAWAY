"""
SDR — Banco de dados SQLite local para conversas e métricas.
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / ".tmp" / "sdr.db"


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT    NOT NULL UNIQUE,
                nome       TEXT    DEFAULT '',
                status     TEXT    DEFAULT 'active',
                converted  INTEGER DEFAULT 0,
                keyword    TEXT    DEFAULT '',
                created_at TEXT    DEFAULT (datetime('now','localtime')),
                updated_at TEXT    DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS messages (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id    TEXT    NOT NULL,
                direction     TEXT    DEFAULT 'in',
                content       TEXT    DEFAULT '',
                msg_type      TEXT    DEFAULT 'text',
                keyword_match TEXT    DEFAULT '',
                created_at    TEXT    DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS exec_errors (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_id  TEXT    DEFAULT '',
                execution_id TEXT    DEFAULT '',
                node_name    TEXT    DEFAULT '',
                error_msg    TEXT    DEFAULT '',
                created_at   TEXT    DEFAULT (datetime('now','localtime'))
            );
        """)


def upsert_conversation(session_id: str, nome: str = "") -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO conversations (session_id, nome) VALUES (?, ?)",
            (session_id, nome),
        )
        if nome:
            c.execute(
                "UPDATE conversations SET nome = ?, updated_at = datetime('now','localtime')"
                " WHERE session_id = ? AND (nome = '' OR nome IS NULL)",
                (nome, session_id),
            )


def record_message(
    session_id: str,
    direction: str,
    content: str,
    msg_type: str = "text",
    keyword_match: str = "",
) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO messages (session_id, direction, content, msg_type, keyword_match)"
            " VALUES (?, ?, ?, ?, ?)",
            (session_id, direction, content, msg_type, keyword_match),
        )
        if keyword_match:
            c.execute(
                "UPDATE conversations SET converted = 1, keyword = ?,"
                " updated_at = datetime('now','localtime') WHERE session_id = ?",
                (keyword_match, session_id),
            )


def record_error(
    workflow_id: str, execution_id: str, node_name: str, error_msg: str
) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO exec_errors (workflow_id, execution_id, node_name, error_msg)"
            " VALUES (?, ?, ?, ?)",
            (workflow_id, execution_id, node_name, error_msg),
        )


def get_stats() -> dict:
    with _conn() as c:
        conversations = c.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        meetings      = c.execute("SELECT COUNT(*) FROM conversations WHERE converted = 1").fetchone()[0]
        errors        = c.execute("SELECT COUNT(*) FROM exec_errors").fetchone()[0]
    return {"conversations": conversations, "meetings": meetings, "errors": errors}


def get_dashboard_data(days: int = 30) -> dict:
    with _conn() as c:
        # Série diária
        daily = c.execute("""
            SELECT date(created_at) AS day,
                   COUNT(*)         AS conversations,
                   SUM(converted)   AS meetings
            FROM   conversations
            WHERE  created_at >= date('now', ?||' days', 'localtime')
            GROUP  BY date(created_at)
            ORDER  BY day
        """, (f"-{days}",)).fetchall()

        # Funil
        total     = c.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        responded = c.execute(
            "SELECT COUNT(DISTINCT session_id) FROM messages WHERE direction='in'"
        ).fetchone()[0]
        qualified = c.execute(
            "SELECT COUNT(*) FROM conversations WHERE converted=1"
        ).fetchone()[0]

        # Reuniões agendadas — conta conversas com link de reunião no conteúdo
        # (busca no conteúdo real pois o keyword pode ser sobrescrito por _AGENT_TAGS)
        meetings_scheduled = c.execute("""
            SELECT COUNT(DISTINCT session_id) FROM messages
            WHERE content LIKE '%meet.google%'
               OR content LIKE '%zoom.us%'
               OR content LIKE '%teams.microsoft%'
               OR content LIKE '%calendly.com%'
               OR content LIKE '%reunião confirmada%'
               OR content LIKE '%reunião agendada%'
               OR content LIKE '%agendamento confirmado%'
               OR content LIKE '%horário confirmado%'
        """).fetchone()[0]

        # Distribuição por hora do dia
        hourly = c.execute("""
            SELECT CAST(strftime('%H', created_at) AS INTEGER) AS hour,
                   COUNT(*) AS cnt
            FROM   conversations
            GROUP  BY hour
            ORDER  BY hour
        """).fetchall()

        # Tipos de mensagem
        msg_types = c.execute("""
            SELECT COALESCE(NULLIF(msg_type,''),'text') AS msg_type,
                   COUNT(*) AS cnt
            FROM   messages
            GROUP  BY msg_type
            ORDER  BY cnt DESC
            LIMIT  8
        """).fetchall()

        # Total de mensagens
        total_msgs = c.execute("SELECT COUNT(*) FROM messages").fetchone()[0]

        # Últimas qualificações
        qualified_list = c.execute("""
            SELECT COALESCE(NULLIF(nome,''), session_id) AS nome,
                   session_id, keyword, updated_at
            FROM   conversations
            WHERE  converted = 1
            ORDER  BY updated_at DESC
            LIMIT  25
        """).fetchall()

    conv_rate = round(qualified / total * 100, 1) if total else 0.0
    return {
        "kpi": {
            "conversations":      total,
            "qualified":          qualified,
            "meetings_scheduled": meetings_scheduled,
            "conv_rate":          conv_rate,
            "total_msgs":         total_msgs,
        },
        "funnel":         {"total": total, "responded": responded, "qualified": qualified},
        "daily":          [dict(r) for r in daily],
        "hourly":         [dict(r) for r in hourly],
        "msg_types":      [dict(r) for r in msg_types],
        "qualified_list": [dict(r) for r in qualified_list],
    }


def get_recent_messages(limit: int = 300) -> list[dict]:
    with _conn() as c:
        rows = c.execute("""
            SELECT m.created_at, COALESCE(c.nome, m.session_id) AS nome,
                   m.direction, m.msg_type, m.content, m.keyword_match
            FROM   messages m
            LEFT JOIN conversations c ON c.session_id = m.session_id
            ORDER  BY m.id DESC
            LIMIT  ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_recent_errors(limit: int = 100) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM exec_errors ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def clear_all() -> None:
    with _conn() as c:
        c.executescript(
            "DELETE FROM messages; DELETE FROM conversations; DELETE FROM exec_errors;"
        )
