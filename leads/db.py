"""
SQLite para persistência de leads entre sessões.
Garante deduplicação por CNPJ (ou pseudo-CNPJ para fontes sem CNPJ).
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "leads.db"

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS leads (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cnpj            TEXT    UNIQUE,
    razao_social    TEXT    DEFAULT '',
    nome_fantasia   TEXT    DEFAULT '',
    email           TEXT    DEFAULT '',
    telefone        TEXT    DEFAULT '',
    municipio       TEXT    DEFAULT '',
    uf              TEXT    DEFAULT '',
    cep             TEXT    DEFAULT '',
    logradouro      TEXT    DEFAULT '',
    numero          TEXT    DEFAULT '',
    bairro          TEXT    DEFAULT '',
    cnae_principal  TEXT    DEFAULT '',
    cnae_descricao  TEXT    DEFAULT '',
    situacao        TEXT    DEFAULT '',
    porte           TEXT    DEFAULT '',
    capital_social  TEXT    DEFAULT '',
    data_inicio     TEXT    DEFAULT '',
    socio_principal TEXT    DEFAULT '',
    website         TEXT    DEFAULT '',
    fonte           TEXT    DEFAULT '',
    campanha        TEXT    DEFAULT '',
    instagram       TEXT    DEFAULT '',
    linkedin        TEXT    DEFAULT '',
    google_rating   TEXT    DEFAULT '',
    google_reviews  TEXT    DEFAULT '',
    categoria       TEXT    DEFAULT '',
    latitude        TEXT    DEFAULT '',
    longitude       TEXT    DEFAULT '',
    source_type     TEXT    DEFAULT '',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""

_NEW_COLUMNS = [
    ("instagram",     "TEXT DEFAULT ''"),
    ("linkedin",      "TEXT DEFAULT ''"),
    ("google_rating", "TEXT DEFAULT ''"),
    ("google_reviews","TEXT DEFAULT ''"),
    ("categoria",     "TEXT DEFAULT ''"),
    ("latitude",      "TEXT DEFAULT ''"),
    ("longitude",     "TEXT DEFAULT ''"),
    ("source_type",   "TEXT DEFAULT ''"),
]

_UPSERT_SQL = """
INSERT INTO leads (
    cnpj, razao_social, nome_fantasia, email, telefone,
    municipio, uf, cep, logradouro, numero, bairro,
    cnae_principal, cnae_descricao, situacao, porte,
    capital_social, data_inicio, socio_principal, website,
    fonte, campanha,
    instagram, linkedin, google_rating, google_reviews,
    categoria, latitude, longitude, source_type
) VALUES (
    :cnpj, :razao_social, :nome_fantasia, :email, :telefone,
    :municipio, :uf, :cep, :logradouro, :numero, :bairro,
    :cnae_principal, :cnae_descricao, :situacao, :porte,
    :capital_social, :data_inicio, :socio_principal, :website,
    :fonte, :campanha,
    :instagram, :linkedin, :google_rating, :google_reviews,
    :categoria, :latitude, :longitude, :source_type
)
ON CONFLICT(cnpj) DO UPDATE SET
    email           = CASE WHEN excluded.email != '' THEN excluded.email ELSE email END,
    telefone        = CASE WHEN excluded.telefone != '' THEN excluded.telefone ELSE telefone END,
    razao_social    = CASE WHEN excluded.razao_social != '' THEN excluded.razao_social ELSE razao_social END,
    cnae_descricao  = CASE WHEN excluded.cnae_descricao != '' THEN excluded.cnae_descricao ELSE cnae_descricao END,
    website         = CASE WHEN excluded.website != '' THEN excluded.website ELSE website END,
    instagram       = CASE WHEN excluded.instagram != '' THEN excluded.instagram ELSE instagram END,
    linkedin        = CASE WHEN excluded.linkedin != '' THEN excluded.linkedin ELSE linkedin END,
    google_rating   = CASE WHEN excluded.google_rating != '' THEN excluded.google_rating ELSE google_rating END,
    google_reviews  = CASE WHEN excluded.google_reviews != '' THEN excluded.google_reviews ELSE google_reviews END,
    categoria       = CASE WHEN excluded.categoria != '' THEN excluded.categoria ELSE categoria END,
    campanha        = excluded.campanha
"""


def _conn():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db():
    with _conn() as c:
        c.execute(_CREATE_SQL)
        # migrate: add new columns if they don't exist yet
        existing = {row[1] for row in c.execute("PRAGMA table_info(leads)")}
        for col, typedef in _NEW_COLUMNS:
            if col not in existing:
                c.execute(f"ALTER TABLE leads ADD COLUMN {col} {typedef}")
        c.commit()


def upsert_lead(lead: dict, campanha: str = ""):
    row = {k: lead.get(k, "") for k in [
        "cnpj", "razao_social", "nome_fantasia", "email", "telefone",
        "municipio", "uf", "cep", "logradouro", "numero", "bairro",
        "cnae_principal", "cnae_descricao", "situacao", "porte",
        "capital_social", "data_inicio", "socio_principal", "website", "fonte",
        "instagram", "linkedin", "google_rating", "google_reviews",
        "categoria", "latitude", "longitude", "source_type",
    ]}
    row["campanha"] = campanha
    with _conn() as c:
        c.execute(_UPSERT_SQL, row)
        c.commit()


def get_all_leads(campanha: str = "") -> list[dict]:
    with _conn() as c:
        if campanha:
            rows = c.execute(
                "SELECT * FROM leads WHERE campanha = ? ORDER BY id DESC", (campanha,)
            ).fetchall()
        else:
            rows = c.execute("SELECT * FROM leads ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


def get_stats() -> dict:
    with _conn() as c:
        total        = c.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        with_email   = c.execute("SELECT COUNT(*) FROM leads WHERE email != ''").fetchone()[0]
        with_phone   = c.execute("SELECT COUNT(*) FROM leads WHERE telefone != ''").fetchone()[0]
        with_website = c.execute("SELECT COUNT(*) FROM leads WHERE website != ''").fetchone()[0]
        from_maps    = c.execute("SELECT COUNT(*) FROM leads WHERE source_type='maps'").fetchone()[0]
        from_cnae    = c.execute("SELECT COUNT(*) FROM leads WHERE source_type='cnae' OR source_type=''").fetchone()[0]
    return {
        "total":        total,
        "with_email":   with_email,
        "with_phone":   with_phone,
        "with_website": with_website,
        "from_maps":    from_maps,
        "from_cnae":    from_cnae,
    }


def clear_leads(campanha: str = "") -> int:
    with _conn() as c:
        if campanha:
            n = c.execute("DELETE FROM leads WHERE campanha = ?", (campanha,)).rowcount
        else:
            n = c.execute("DELETE FROM leads").rowcount
        c.commit()
    return n
