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
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _lock:
        with _conn() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS email_campaigns (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id  TEXT UNIQUE NOT NULL,
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
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id TEXT NOT NULL,
                    cliente     TEXT DEFAULT '',
                    email       TEXT DEFAULT '',
                    status      TEXT DEFAULT 'pending',
                    error_msg   TEXT DEFAULT '',
                    sent_at     TEXT,
                    bounced     INTEGER DEFAULT 0,
                    created_at  TEXT DEFAULT (datetime('now','localtime'))
                )
            """)
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_ec_id ON email_campaigns(campaign_id)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_es_campaign ON email_sends(campaign_id)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_es_email ON email_sends(email)"
            )


def start_campaign(campaign_id: str, excel_path: str, total: int) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _lock:
        with _conn() as c:
            c.execute(
                "INSERT INTO email_campaigns (campaign_id, excel_path, total, started_at) "
                "VALUES (?,?,?,?)",
                (campaign_id, excel_path, total, ts),
            )


def record_send(
    campaign_id: str,
    cliente: str,
    email: str,
    status: str,           # "sent" | "failed" | "no_email"
    error_msg: str = "",
) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if status == "sent" else None
    with _lock:
        with _conn() as c:
            c.execute(
                "INSERT INTO email_sends "
                "(campaign_id, cliente, email, status, error_msg, sent_at) "
                "VALUES (?,?,?,?,?,?)",
                (campaign_id, cliente, email, status, error_msg[:500], ts),
            )
            col = {"sent": "sent", "failed": "failed", "no_email": "no_email"}.get(status)
            if col:
                c.execute(
                    f"UPDATE email_campaigns SET {col}={col}+1 WHERE campaign_id=?",
                    (campaign_id,),
                )


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
