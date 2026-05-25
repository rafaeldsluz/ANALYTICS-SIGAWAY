"""
Persistência SQLite para campanhas de e-mail.
Rastreia status individual de cada envio + detecção de retornos via Graph API.
"""
import csv
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "email_campaign.db"
_lock = threading.Lock()

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

_NDR_SUBJECTS = (
    "undeliverable", "delivery", "mail delivery failed",
    "falha na entrega", "não foi possível entregar",
    "mensagem não entregue", "returned mail", "bounced",
)


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    # Network shares (UNC paths) can't create journal files on disk;
    # MEMORY mode keeps the journal in RAM, avoiding SQLITE_CANTOPEN on writes.
    c.execute("PRAGMA journal_mode=MEMORY")
    return c


def init_db() -> None:
    with _lock:
        with _conn() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS email_campaigns (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id  TEXT UNIQUE NOT NULL,
                    name         TEXT DEFAULT '',
                    excel_path   TEXT DEFAULT '',
                    total        INTEGER DEFAULT 0,
                    sent         INTEGER DEFAULT 0,
                    failed       INTEGER DEFAULT 0,
                    no_email     INTEGER DEFAULT 0,
                    bounced      INTEGER DEFAULT 0,
                    started_at   TEXT,
                    completed_at TEXT
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS email_sends (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id     TEXT NOT NULL,
                    cliente         TEXT DEFAULT '',
                    email           TEXT DEFAULT '',
                    status          TEXT DEFAULT 'pending',
                    error_msg       TEXT DEFAULT '',
                    sent_at         TEXT,
                    bounced         INTEGER DEFAULT 0,
                    tracking_token  TEXT DEFAULT '',
                    created_at      TEXT DEFAULT (datetime('now','localtime'))
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS email_opens (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    token      TEXT NOT NULL,
                    opened_at  TEXT NOT NULL,
                    user_agent TEXT DEFAULT '',
                    ip         TEXT DEFAULT ''
                )
            """)
            try:
                c.execute("ALTER TABLE email_sends ADD COLUMN tracking_token TEXT DEFAULT ''")
            except Exception:
                pass
            try:
                c.execute("ALTER TABLE email_campaigns ADD COLUMN name TEXT DEFAULT ''")
            except Exception:
                pass
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_ec_id ON email_campaigns(campaign_id)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_es_campaign ON email_sends(campaign_id)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_es_email ON email_sends(email)"
            )
            c.execute("""
                CREATE TABLE IF NOT EXISTS email_clicks (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    token      TEXT NOT NULL,
                    url        TEXT DEFAULT '',
                    clicked_at TEXT NOT NULL,
                    user_agent TEXT DEFAULT '',
                    ip         TEXT DEFAULT ''
                )
            """)
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_eo_token ON email_opens(token)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_ck_token ON email_clicks(token)"
            )


def start_campaign(campaign_id: str, excel_path: str, total: int, name: str = "") -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _lock:
        with _conn() as c:
            c.execute(
                "INSERT INTO email_campaigns (campaign_id, name, excel_path, total, started_at) "
                "VALUES (?,?,?,?,?)",
                (campaign_id, name[:120], excel_path, total, ts),
            )


def record_send(
    campaign_id: str,
    cliente: str,
    email: str,
    status: str,           # "sent" | "failed" | "no_email"
    error_msg: str = "",
    tracking_token: str = "",
) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if status == "sent" else None
    with _lock:
        with _conn() as c:
            c.execute(
                "INSERT INTO email_sends "
                "(campaign_id, cliente, email, status, error_msg, sent_at, tracking_token) "
                "VALUES (?,?,?,?,?,?,?)",
                (campaign_id, cliente, email, status, error_msg[:500], ts, tracking_token),
            )
            # Whitelist column names — prevents dynamic SQL injection
            _COL_MAP = {"sent": "sent", "failed": "failed", "no_email": "no_email"}
            col = _COL_MAP.get(status)
            if col in _COL_MAP.values():
                sql = {
                    "sent":     "UPDATE email_campaigns SET sent=sent+1 WHERE campaign_id=?",
                    "failed":   "UPDATE email_campaigns SET failed=failed+1 WHERE campaign_id=?",
                    "no_email": "UPDATE email_campaigns SET no_email=no_email+1 WHERE campaign_id=?",
                }[col]
                c.execute(sql, (campaign_id,))


def finish_campaign(campaign_id: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _lock:
        with _conn() as c:
            c.execute(
                "UPDATE email_campaigns SET completed_at=? WHERE campaign_id=?",
                (ts, campaign_id),
            )


def get_campaign_stats(campaign_id: str) -> dict:
    with _lock:
        with _conn() as c:
            row = c.execute(
                "SELECT * FROM email_campaigns WHERE campaign_id=?",
                (campaign_id,),
            ).fetchone()
    return dict(row) if row else {}


def get_recent_campaigns(n: int = 10) -> list[dict]:
    with _lock:
        with _conn() as c:
            rows = c.execute(
                "SELECT * FROM email_campaigns ORDER BY started_at DESC LIMIT ?",
                (n,),
            ).fetchall()
    return [dict(r) for r in rows]


def get_campaign_sends(campaign_id: str) -> list[dict]:
    with _lock:
        with _conn() as c:
            rows = c.execute(
                "SELECT * FROM email_sends WHERE campaign_id=? ORDER BY id",
                (campaign_id,),
            ).fetchall()
    return [dict(r) for r in rows]


def mark_bounced_email(campaign_id: str, email: str) -> None:
    with _lock:
        with _conn() as c:
            updated = c.execute(
                "UPDATE email_sends SET bounced=1 "
                "WHERE campaign_id=? AND LOWER(email)=LOWER(?) AND bounced=0",
                (campaign_id, email),
            ).rowcount
            if updated:
                c.execute(
                    "UPDATE email_campaigns SET bounced=bounced+? WHERE campaign_id=?",
                    (updated, campaign_id),
                )


def export_csv(campaign_id: str, output_path: str | None = None) -> str:
    """Exporta todos os envios de uma campanha para CSV. Retorna o caminho do arquivo."""
    sends = get_campaign_sends(campaign_id)
    if output_path is None:
        output_path = str(
            Path(__file__).parent.parent / f"relatorio_{campaign_id}.csv"
        )
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["cliente", "email", "status", "sent_at", "retorno", "erro"],
        )
        writer.writeheader()
        for s in sends:
            writer.writerow({
                "cliente":  s.get("cliente", ""),
                "email":    s.get("email", ""),
                "status":   s.get("status", ""),
                "sent_at":  s.get("sent_at", ""),
                "retorno":  "Sim" if s.get("bounced") else "Não",
                "erro":     s.get("error_msg", ""),
            })
    return output_path


def get_all_sent_emails() -> set[str]:
    """Retorna todos os e-mails enviados com sucesso em qualquer campanha (memória global)."""
    with _lock:
        with _conn() as c:
            rows = c.execute(
                "SELECT DISTINCT LOWER(email) FROM email_sends "
                "WHERE status='sent' AND email != ''"
            ).fetchall()
    return {r[0] for r in rows}


def clear_sent_history() -> int:
    """Apaga todo o histórico de campanhas e envios. Retorna quantidade de registros removidos."""
    with _lock:
        with _conn() as c:
            n = c.execute("DELETE FROM email_sends").rowcount
            c.execute("DELETE FROM email_campaigns")
    return n


def record_click(token: str, url: str = "", user_agent: str = "", ip: str = "") -> None:
    """Registra um clique em link rastreável."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _lock:
        with _conn() as c:
            c.execute(
                "INSERT INTO email_clicks (token, url, clicked_at, user_agent, ip) VALUES (?,?,?,?,?)",
                (token, url[:2048], ts, user_agent[:512], ip[:64]),
            )


def get_campaign_clicks(campaign_id: str) -> list[dict]:
    """Retorna lista de cliques de uma campanha."""
    with _lock:
        with _conn() as c:
            rows = c.execute(
                """
                SELECT es.cliente, es.email, ck.url, ck.clicked_at, ck.user_agent, ck.ip
                FROM email_clicks ck
                JOIN email_sends es ON es.tracking_token = ck.token
                WHERE es.campaign_id = ?
                ORDER BY ck.clicked_at DESC
                """,
                (campaign_id,),
            ).fetchall()
    return [dict(r) for r in rows]


def get_analytics_data(n: int = 20) -> list[dict]:
    """Retorna KPIs agregados por campanha, da mais recente para a mais antiga."""
    with _lock:
        with _conn() as c:
            rows = c.execute(
                """
                SELECT
                    ec.campaign_id,
                    ec.started_at,
                    ec.completed_at,
                    ec.total,
                    ec.sent,
                    ec.failed,
                    ec.bounced,
                    COUNT(DISTINCT CASE WHEN eo.id IS NOT NULL THEN es.id END) AS unique_opens,
                    COUNT(eo.id)                                               AS total_opens,
                    COUNT(DISTINCT CASE WHEN ck.id IS NOT NULL THEN ck.token END) AS unique_clicks,
                    COUNT(ck.id)                                               AS total_clicks
                FROM email_campaigns ec
                LEFT JOIN email_sends es
                    ON es.campaign_id = ec.campaign_id
                    AND es.status = 'sent'
                    AND es.tracking_token != ''
                LEFT JOIN email_opens  eo ON eo.token = es.tracking_token
                LEFT JOIN email_clicks ck ON ck.token = es.tracking_token
                GROUP BY ec.campaign_id
                ORDER BY ec.started_at DESC
                LIMIT ?
                """,
                (n,),
            ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        sent          = d.get("sent") or 0
        unique_opens  = d.get("unique_opens") or 0
        unique_clicks = d.get("unique_clicks") or 0
        total         = d.get("total") or 0
        d["open_rate"]     = round(unique_opens  / sent  * 100, 1) if sent  else 0.0
        d["ctr"]           = round(unique_clicks / sent  * 100, 1) if sent  else 0.0
        d["ctor"]          = round(unique_clicks / unique_opens * 100, 1) if unique_opens else 0.0
        d["delivery_rate"] = round(sent / total * 100, 1) if total else 0.0
        result.append(d)
    return result


def record_open(token: str, user_agent: str = "", ip: str = "") -> None:
    """Registra uma abertura de e-mail via pixel de rastreamento."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _lock:
        with _conn() as c:
            c.execute(
                "INSERT INTO email_opens (token, opened_at, user_agent, ip) VALUES (?,?,?,?)",
                (token, ts, user_agent[:512], ip[:64]),
            )


def get_campaign_opens(campaign_id: str) -> list[dict]:
    """Retorna lista de aberturas de uma campanha (join email_sends → email_opens)."""
    with _lock:
        with _conn() as c:
            rows = c.execute(
                """
                SELECT es.cliente, es.email, eo.opened_at, eo.user_agent, eo.ip
                FROM email_opens eo
                JOIN email_sends es ON es.tracking_token = eo.token
                WHERE es.campaign_id = ?
                ORDER BY eo.opened_at DESC
                """,
                (campaign_id,),
            ).fetchall()
    return [dict(r) for r in rows]


def check_bounces_graph(
    tenant_id: str,
    client_id: str,
    client_secret: str,
    sender_email: str,
    campaign_id: str,
) -> list[str]:
    """
    Consulta a caixa de entrada via Graph API em busca de NDRs (Non-Delivery Reports)
    recebidos após o início da campanha. Marca os e-mails identificados como retornados.
    Retorna lista de endereços bounced.
    """
    import requests
    from execution.email_sender import _graph_token

    stats = get_campaign_stats(campaign_id)
    if not stats:
        raise ValueError(f"Campanha '{campaign_id}' não encontrada no banco.")

    since_ts  = stats.get("started_at", "")
    since_iso = since_ts.replace(" ", "T") + "Z" if since_ts else ""

    token = _graph_token(tenant_id, client_id, client_secret)

    url = (
        f"https://graph.microsoft.com/v1.0/users/{sender_email}"
        f"/mailFolders/inbox/messages"
    )
    params: dict = {
        "$select": "subject,receivedDateTime,body",
        "$top": "100",
        "$orderby": "receivedDateTime desc",
    }
    if since_iso:
        params["$filter"] = f"receivedDateTime ge {since_iso}"

    resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=25,
    )
    if not resp.ok:
        raise RuntimeError(f"Graph API: HTTP {resp.status_code}: {resp.text[:200]}")

    sends        = get_campaign_sends(campaign_id)
    known_emails = {s["email"].lower() for s in sends if s.get("email")}
    bounced: list[str] = []

    for msg in resp.json().get("value", []):
        subject = msg.get("subject", "").lower()
        is_ndr  = any(kw in subject for kw in _NDR_SUBJECTS)
        if not is_ndr:
            continue
        body   = msg.get("body", {}).get("content", "")
        for em in _EMAIL_RE.findall(body):
            if em.lower() in known_emails:
                mark_bounced_email(campaign_id, em)
                bounced.append(em)

    return list(set(bounced))
