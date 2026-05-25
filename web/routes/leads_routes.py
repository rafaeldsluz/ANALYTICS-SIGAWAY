"""
Rotas do módulo Leads / CNAE + Google Maps.
"""
import logging
import os
import threading
import time
import uuid

from flask import (
    Blueprint, Response, render_template,
    request, jsonify, stream_with_context, send_file,
)

from web.auth     import csrf_protect, login_required
from web.security import audit, rate_limit, sanitize_int, sanitize_str
from web.sse import sse

_log = logging.getLogger("sigaway.leads")
bp   = Blueprint("leads", __name__)

_extraction:   dict = {"stop": None, "thread": None}
_maps_job:     dict = {"stop": None, "thread": None}
_pipeline_job: dict = {"stop": None, "thread": None}


@bp.get("/")
@login_required
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


# ── CNAE extraction ────────────────────────────────────────────────────────────

@bp.post("/start")
@login_required
@csrf_protect
@rate_limit(max_requests=5, window_s=60, scope="leads_start")
def start():
    global _extraction
    if _extraction["thread"] and _extraction["thread"].is_alive():
        return jsonify({"error": "Extração já em andamento."}), 409

    data      = request.json or {}
    stream_id = str(uuid.uuid4())
    stop      = threading.Event()
    _extraction = {"stop": stop, "thread": None}

    audit("INFO", "LEADS_EXTRACTION_START", f"ip={request.remote_addr}")
    t = threading.Thread(target=_run_extraction, args=(data, stream_id, stop), daemon=True)
    _extraction["thread"] = t
    t.start()
    return jsonify({"stream_id": stream_id})


@bp.post("/stop")
@login_required
@csrf_protect
def stop():
    if _extraction.get("stop"):
        _extraction["stop"].set()
    return jsonify({"ok": True})


@bp.get("/stream/<stream_id>")
@login_required
def stream(stream_id):
    return Response(
        stream_with_context(sse.listen(stream_id)),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Google Maps extraction ─────────────────────────────────────────────────────

@bp.post("/maps-start")
@login_required
@csrf_protect
@rate_limit(max_requests=5, window_s=60, scope="maps_start")
def maps_start():
    global _maps_job
    if _maps_job["thread"] and _maps_job["thread"].is_alive():
        return jsonify({"error": "Busca no Maps já em andamento."}), 409

    data      = request.json or {}
    stream_id = str(uuid.uuid4())
    stop      = threading.Event()
    _maps_job = {"stop": stop, "thread": None}

    audit("INFO", "MAPS_SCRAPE_START", f"ip={request.remote_addr}")
    t = threading.Thread(target=_run_maps, args=(data, stream_id, stop), daemon=True)
    _maps_job["thread"] = t
    t.start()
    return jsonify({"stream_id": stream_id})


@bp.post("/maps-stop")
@login_required
@csrf_protect
def maps_stop():
    if _maps_job.get("stop"):
        _maps_job["stop"].set()
    return jsonify({"ok": True})


@bp.get("/maps-stream/<stream_id>")
@login_required
def maps_stream(stream_id):
    return Response(
        stream_with_context(sse.listen(stream_id)),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Pipeline enrichment ───────────────────────────────────────────────────────

@bp.post("/pipeline/start")
@login_required
@csrf_protect
@rate_limit(max_requests=3, window_s=60, scope="pipeline_start")
def pipeline_start():
    global _pipeline_job
    if _pipeline_job["thread"] and _pipeline_job["thread"].is_alive():
        return jsonify({"error": "Pipeline já em andamento."}), 409

    data      = request.json or {}
    stream_id = str(uuid.uuid4())
    stop      = threading.Event()
    _pipeline_job = {"stop": stop, "thread": None}

    modules = {
        "instagram": bool(data.get("instagram")),
        "linkedin":  bool(data.get("linkedin")),
        "score":     bool(data.get("score", True)),
    }
    tier     = sanitize_str(data.get("tier", ""), max_len=20)
    campanha = sanitize_str(data.get("campanha", ""), max_len=100)

    audit("INFO", "PIPELINE_START", f"modules={modules} tier={tier or 'all'} ip={request.remote_addr}")

    t = threading.Thread(
        target=_run_pipeline,
        args=(modules, tier, campanha, stream_id, stop),
        daemon=True,
    )
    _pipeline_job["thread"] = t
    t.start()
    return jsonify({"stream_id": stream_id})


@bp.post("/pipeline/stop")
@login_required
@csrf_protect
def pipeline_stop():
    if _pipeline_job.get("stop"):
        _pipeline_job["stop"].set()
    return jsonify({"ok": True})


@bp.get("/pipeline/stream/<stream_id>")
@login_required
def pipeline_stream(stream_id):
    return Response(
        stream_with_context(sse.listen(stream_id)),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@bp.get("/leads-data")
@login_required
def leads_data():
    from leads.db import init_db, get_leads_page
    init_db()
    page     = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 50)), 200)
    tier     = request.args.get("tier", "")
    return jsonify(get_leads_page(page, per_page, tier))


# ── Shared endpoints ───────────────────────────────────────────────────────────

@bp.get("/stats")
@login_required
def stats():
    from leads.db import init_db, get_stats
    init_db()
    return jsonify(get_stats())


@bp.post("/clear")
@login_required
@csrf_protect
def clear():
    from leads.db import init_db, clear_leads
    init_db()
    audit("WARNING", "LEADS_CLEAR_ALL", f"ip={request.remote_addr}")
    n = clear_leads()
    return jsonify({"deleted": n})


@bp.get("/export")
@login_required
def export():
    import pandas as pd
    from leads.db import init_db, get_all_leads
    init_db()
    leads = get_all_leads()
    if not leads:
        return jsonify({"error": "Nenhum lead na base."}), 404

    fmt        = request.args.get("fmt", "full")
    only_email = request.args.get("only_email") == "1"
    only_phone = request.args.get("only_phone") == "1"
    file_fmt   = request.args.get("file", "xlsx")

    if file_fmt == "json":
        import json as _json
        result = [dict(r) for r in leads]
        import tempfile
        fd, tmp = tempfile.mkstemp(suffix=".json", prefix="leads_export_")
        os.close(fd)
        with open(tmp, "w", encoding="utf-8") as f:
            _json.dump(result, f, ensure_ascii=False, indent=2)
        return send_file(tmp, as_attachment=True, download_name="leads_export.json")

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
    suffix   = ".csv" if file_fmt == "csv" else ".xlsx"
    prefix   = f"leads_export_{uuid.uuid4().hex[:8]}_"
    fd, tmp  = tempfile.mkstemp(suffix=suffix, prefix=prefix)
    os.close(fd)

    if file_fmt == "csv":
        out.to_csv(tmp, index=False, encoding="utf-8-sig")
        return send_file(tmp, as_attachment=True, download_name=f"leads_export.csv")
    else:
        out.to_excel(tmp, index=False)
        return send_file(tmp, as_attachment=True, download_name=f"leads_export.xlsx")


# ── Runners ────────────────────────────────────────────────────────────────────

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
    cnaes     = cfg.get("cnaes", [])
    uf        = cfg.get("uf", "")
    municipio = cfg.get("municipio", "")
    max_r     = int(cfg.get("max_r", 200))
    enrich    = cfg.get("enrich", True)
    token     = cfg.get("token", "")

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

                lead["source_type"] = "cnae"
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


def _run_maps(cfg: dict, stream_id: str, stop):
    from execution.maps_scraper import scrape_maps
    from execution.web_enricher import enrich_website
    from leads.db import init_db, upsert_lead, get_stats

    def _log(msg, level="INFO"):
        sse.push(stream_id, "log", {"msg": msg, "level": level})

    def _update_stats():
        s = get_stats()
        sse.push(stream_id, "stats", s)

    init_db()
    keyword   = cfg.get("keyword", "").strip()
    location  = cfg.get("location", "").strip()
    max_r     = int(cfg.get("max_r", 50))
    do_enrich = cfg.get("enrich_web", False)

    if not keyword:
        _log("Palavra-chave não informada.", "ERROR")
        sse.push(stream_id, "done", {})
        return

    _log(f"Buscando no Google Maps: '{keyword}' em '{location or 'Brasil'}'...")
    _log("Iniciando navegador (pode levar alguns segundos)...", "DIM")

    count = [0]

    def _on_result(biz):
        count[0] += 1
        name = biz.get("razao_social", "?")
        phone = biz.get("telefone", "")
        _log(f"  [{count[0]}] {name}" + (f"  |  {phone}" if phone else ""), "INFO")

    def _on_progress(found, total_est):
        pct = round(found / total_est * 100) if total_est else 0
        sse.push(stream_id, "progress", {"pct": min(pct, 99)})

    try:
        leads = scrape_maps(
            keyword=keyword,
            location=location,
            max_results=max_r,
            on_result=_on_result,
            on_progress=_on_progress,
            stop_event=stop,
        )

        _log(f"{len(leads)} empresas encontradas. Salvando...", "SUCCESS")

        enriched = 0
        for i, lead in enumerate(leads):
            if stop.is_set():
                break

            if do_enrich and lead.get("website"):
                _log(f"  Enriquecendo site: {lead['website'][:60]}...", "DIM")
                extra = enrich_website(lead["website"])
                if extra.get("email") and not lead.get("email"):
                    lead["email"] = extra["email"]
                if extra.get("instagram") and not lead.get("instagram"):
                    lead["instagram"] = extra["instagram"]
                if extra.get("linkedin") and not lead.get("linkedin"):
                    lead["linkedin"] = extra["linkedin"]
                enriched += 1
                time.sleep(0.5)

            upsert_lead(lead)

            if i % 5 == 0:
                _update_stats()

        s = get_stats()
        enrich_msg = f"  |  Sites enriquecidos: {enriched}" if do_enrich else ""
        _log(
            f"Concluído — {len(leads)} leads do Maps{enrich_msg}  |  "
            f"Total na base: {s['total']}",
            "SUCCESS",
        )
        sse.push(stream_id, "stats", s)
        sse.push(stream_id, "progress", {"pct": 100})

    except Exception as e:
        _log(f"Erro no Maps: {e}", "ERROR")
    finally:
        sse.push(stream_id, "done", {})


def _run_pipeline(modules: dict, tier: str, campanha: str, stream_id: str, stop):
    from leads.db import init_db, get_all_leads
    from pipeline.orchestrator import run_pipeline

    init_db()
    if tier:
        leads = [r for r in get_all_leads() if r.get("lead_tier") == tier]
    else:
        leads = get_all_leads()

    cnpjs = [r["cnpj"] for r in leads if r.get("cnpj")]
    if not cnpjs:
        sse.push(stream_id, "log", {"msg": "Nenhum lead na base para enriquecer.", "level": "WARN"})
        sse.push(stream_id, "done", {})
        return

    run_pipeline(cnpjs, modules, stream_id, stop, campanha)


def _fallback(company: dict, cnae: str) -> dict:
    def _s(v):
        s = str(v or "").strip()
        return "" if s in ("nan", "None") else s

    ddd1 = _s(company.get("ddd1"))
    tel1 = _s(company.get("telefone1"))
    return {
        "razao_social":   _s(company.get("nome_fantasia")),
        "nome_fantasia":  _s(company.get("nome_fantasia")),
        "cnpj":           _s(company.get("cnpj")),
        "email":          _s(company.get("email")).lower(),
        "telefone":       f"({ddd1}) {tel1}" if ddd1 and tel1 else tel1,
        "municipio":      _s(company.get("municipio")),
        "uf":             _s(company.get("uf")),
        "cep":            _s(company.get("cep")),
        "logradouro":     _s(company.get("logradouro")),
        "numero":         _s(company.get("numero")),
        "bairro":         _s(company.get("bairro")),
        "cnae_principal": cnae,
        "cnae_descricao": "",
        "situacao":       "ATIVA" if company.get("situacao_cadastral") == "02" else _s(company.get("situacao_cadastral")),
        "porte":          "",
        "capital_social": "",
        "data_inicio":    _s(company.get("data_inicio_atividade")),
        "socio_principal":"",
        "website":        "",
        "fonte":          "Brasil.io",
        "source_type":    "cnae",
        "instagram":      "",
        "linkedin":       "",
        "google_rating":  "",
        "google_reviews": "",
        "categoria":      "",
        "latitude":       "",
        "longitude":      "",
    }
