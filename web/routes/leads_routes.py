"""
Rotas do módulo Leads / CNAE.
"""
import os
import threading
import time
import uuid

from flask import (
    Blueprint, Response, render_template,
    request, jsonify, stream_with_context, send_file,
)

from web.sse import sse

bp = Blueprint("leads", __name__)

_extraction: dict = {"stop": None, "thread": None}


@bp.get("/")
def index():
    from leads.db import init_db, get_stats
    init_db()
    stats = get_stats()
    return render_template(
        "leads.html",
        active="leads",
        stats=stats,
        brasilio_token=os.getenv("BRASILIO_TOKEN", ""),
    )


@bp.post("/start")
def start():
    global _extraction
    if _extraction["thread"] and _extraction["thread"].is_alive():
        return jsonify({"error": "Extração já em andamento."}), 409

    data = request.json or {}
    stream_id = str(uuid.uuid4())
    stop = threading.Event()

    _extraction = {"stop": stop, "thread": None}

    t = threading.Thread(
        target=_run_extraction,
        args=(data, stream_id, stop),
        daemon=True,
    )
    _extraction["thread"] = t
    t.start()

    return jsonify({"stream_id": stream_id})


@bp.post("/stop")
def stop():
    if _extraction.get("stop"):
        _extraction["stop"].set()
    return jsonify({"ok": True})


@bp.get("/stream/<stream_id>")
def stream(stream_id):
    return Response(
        stream_with_context(sse.listen(stream_id)),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@bp.get("/stats")
def stats():
    from leads.db import init_db, get_stats
    init_db()
    return jsonify(get_stats())


@bp.post("/clear")
def clear():
    from leads.db import init_db, clear_leads
    init_db()
    n = clear_leads()
    return jsonify({"deleted": n})


@bp.get("/export")
def export():
    import pandas as pd
    from leads.db import init_db, get_all_leads
    init_db()
    leads = get_all_leads()
    if not leads:
        return jsonify({"error": "Nenhum lead na base."}), 404

    fmt        = request.args.get("fmt", "emkt")
    only_email = request.args.get("only_email") == "1"
    only_phone = request.args.get("only_phone") == "1"

    df = pd.DataFrame(leads)
    df["email"]    = df["email"].fillna("").astype(str)
    df["telefone"] = df["telefone"].fillna("").astype(str)

    if only_email:
        df = df[df["email"].str.strip() != ""]
    if only_phone:
        df = df[df["telefone"].str.strip() != ""]

    if fmt == "emkt":
        out = pd.DataFrame({
            "REPRESENTANTE": df.get("cnae_descricao", "").fillna(""),
            "CLIENTE":       df["razao_social"].where(
                                 df["razao_social"].str.strip() != "",
                                 df.get("nome_fantasia", "")
                             ).fillna(""),
            "EMAIL":         df["email"],
            "TELEFONE":      df["telefone"],
            "CNPJ":          df["cnpj"].fillna(""),
            "MUNICIPIO":     df["municipio"].fillna(""),
            "UF":            df["uf"].fillna(""),
        })
    else:
        out = df.drop(columns=["id", "created_at"], errors="ignore")

    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".xlsx", prefix=f"leads_export_{uuid.uuid4().hex[:8]}_")
    import os as _os
    _os.close(fd)
    out.to_excel(tmp, index=False)
    return send_file(tmp, as_attachment=True, download_name="leads_cnae.xlsx")


# ── Runner ─────────────────────────────────────────────────────────────────────

def _run_extraction(cfg: dict, stream_id: str, stop):
    from leads.brasilio import search_by_cnae
    from leads.cnpjws   import enrich as cnpjws_enrich, normalize as cnpjws_norm
    from leads.db       import init_db, upsert_lead, get_stats

    def _log(msg, level="INFO"):
        sse.push(stream_id, "log", {"msg": msg, "level": level})

    def _update_stats():
        s = get_stats()
        sse.push(stream_id, "stats", s)

    init_db()
    cnaes       = cfg.get("cnaes", [])
    uf          = cfg.get("uf", "")
    municipio   = cfg.get("municipio", "")
    max_r       = int(cfg.get("max_r", 200))
    enrich      = cfg.get("enrich", True)
    token       = cfg.get("token", "")

    _log(f"Iniciando — {len(cnaes)} CNAE(s) | UF: {uf or 'Todas'} | "
         f"Município: {municipio or 'Todos'} | Enriquecimento: {'Sim' if enrich else 'Não'}")

    try:
        total_cnaes = len(cnaes)
        for ci, cnae in enumerate(cnaes):
            if stop.is_set():
                break

            _log(f"Buscando CNAE {cnae}...")

            def _prog(found, total_est, c=cnae):
                sse.push(stream_id, "progress", {
                    "cnae": c, "found": found, "total_est": total_est or 0,
                    "pct": round((ci * max_r + found) / (total_cnaes * max_r) * 100)
                })

            try:
                companies = search_by_cnae(
                    cnae=cnae, token=token, uf=uf, municipio=municipio,
                    max_results=max_r, on_progress=_prog, stop_event=stop,
                )
            except ValueError as e:
                _log(str(e), "ERROR")
                break

            _log(f"  CNAE {cnae}: {len(companies)} empresas encontradas.")

            for i, company in enumerate(companies):
                if stop.is_set():
                    break

                cnpj = company.get("cnpj", "")
                if not cnpj:
                    continue

                if enrich:
                    raw  = cnpjws_enrich(cnpj)
                    lead = cnpjws_norm(raw) if raw else _fallback(company, cnae)
                    time.sleep(0.8)
                else:
                    lead = _fallback(company, cnae)

                upsert_lead(lead)

                if i % 5 == 0:
                    _update_stats()
                    pct = round(((ci * max_r) + i) / (total_cnaes * max_r) * 100)
                    sse.push(stream_id, "progress", {"pct": min(pct, 99)})

            _log(f"✓ CNAE {cnae} concluído.", "SUCCESS")

        s = get_stats()
        _log(
            f"Extração finalizada — Total: {s['total']}  |  "
            f"Com e-mail: {s['with_email']}  |  Com telefone: {s['with_phone']}",
            "SUCCESS",
        )
        sse.push(stream_id, "stats", s)

    except Exception as e:
        _log(f"Erro crítico: {e}", "ERROR")
    finally:
        sse.push(stream_id, "done", {})


def _fallback(company: dict, cnae: str) -> dict:
    def _s(v):
        s = str(v or "").strip()
        return "" if s in ("nan", "None") else s

    ddd1 = _s(company.get("ddd1"))
    tel1 = _s(company.get("telefone1"))
    return {
        "razao_social": _s(company.get("nome_fantasia")),
        "nome_fantasia": _s(company.get("nome_fantasia")),
        "cnpj": _s(company.get("cnpj")),
        "email": _s(company.get("email")).lower(),
        "telefone": f"({ddd1}) {tel1}" if ddd1 and tel1 else tel1,
        "municipio": _s(company.get("municipio")),
        "uf": _s(company.get("uf")),
        "cep": _s(company.get("cep")),
        "logradouro": _s(company.get("logradouro")),
        "numero": _s(company.get("numero")),
        "bairro": _s(company.get("bairro")),
        "cnae_principal": cnae, "cnae_descricao": "",
        "situacao": "ATIVA" if company.get("situacao_cadastral") == "02" else _s(company.get("situacao_cadastral")),
        "porte": "", "capital_social": "", "data_inicio": _s(company.get("data_inicio_atividade")),
        "socio_principal": "", "website": "", "fonte": "Brasil.io",
    }
