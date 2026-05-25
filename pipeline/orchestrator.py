"""
Pipeline orchestrator — enriches leads in the DB by running selected modules
(Instagram, LinkedIn) in sequence and recalculating lead scores.
Reports progress via SSE.
"""
import logging
import random
import time

_log = logging.getLogger("sigaway.pipeline")


def run_pipeline(
    cnpjs: list,
    modules: dict,
    stream_id: str,
    stop,
    campanha: str = "",
) -> None:
    """
    cnpjs     — list of CNPJ values for leads already saved in the DB
    modules   — {"instagram": bool, "linkedin": bool, "score": bool}
    stream_id — SSE channel id
    stop      — threading.Event to cancel
    campanha  — campaign name tag
    """
    from leads.db import init_db, upsert_lead, get_all_leads
    from pipeline.lead_scoring import calculate_score
    from web.sse import sse

    def _push_log(msg, level="INFO"):
        sse.push(stream_id, "log", {"msg": msg, "level": level})

    init_db()
    total = len(cnpjs)
    active = [k for k, v in modules.items() if v and k != "score"]
    _push_log(f"Pipeline iniciado — {total} leads | Módulos: {', '.join(active) if active else 'score only'}")

    # Index DB leads by cnpj for fast lookup
    db_leads = {r["cnpj"]: r for r in get_all_leads()}

    done = 0
    for cnpj in cnpjs:
        if stop.is_set():
            _push_log("Pipeline interrompido pelo usuário.", "WARN")
            break

        lead = db_leads.get(cnpj)
        if not lead:
            done += 1
            continue

        company_name = (lead.get("razao_social") or lead.get("nome_fantasia") or "").strip()
        website = lead.get("website", "")
        updates: dict = {}

        _push_log(f"[{done + 1}/{total}] {company_name or cnpj}", "DIM")

        # ── Instagram module ──────────────────────────────────────────────────
        if modules.get("instagram") and not (lead.get("instagram") or "").strip():
            try:
                from scraping.instagram_scraper import find_and_scrape as ig_scrape
                ig = ig_scrape(company_name, website)
                if ig.get("username"):
                    updates["instagram"]           = f"@{ig['username']}"
                    updates["instagram_followers"] = str(ig.get("seguidores", 0))
                    updates["instagram_bio"]       = (ig.get("bio") or "")[:300]
                    updates["instagram_verified"]  = 1 if ig.get("verificado") else 0
                    if ig.get("email") and not (lead.get("email") or "").strip():
                        updates["email"] = ig["email"]
                    _push_log(
                        f"  IG @{ig['username']} — {ig.get('seguidores', 0):,} seguidores",
                        "SUCCESS",
                    )
                else:
                    _push_log("  IG: não encontrado", "DIM")
            except Exception as exc:
                _push_log(f"  IG erro: {exc}", "ERROR")
                _log.exception("Instagram error for cnpj=%s", cnpj)

            time.sleep(random.uniform(3.0, 7.0))

        # ── LinkedIn module ───────────────────────────────────────────────────
        if modules.get("linkedin") and not (lead.get("linkedin") or "").strip():
            try:
                from scraping.linkedin_scraper import find_and_scrape as li_scrape
                li = li_scrape(company_name, website)
                if li.get("url"):
                    updates["linkedin"]                = li["url"]
                    updates["linkedin_descricao"]      = (li.get("descricao") or "")[:500]
                    updates["linkedin_setor"]          = li.get("setor", "")
                    updates["linkedin_tamanho"]        = li.get("tamanho", "")
                    updates["linkedin_funcionarios"]   = li.get("funcionarios", "")
                    updates["linkedin_especialidades"] = li.get("especialidades", "")
                    if li.get("website") and not (lead.get("website") or "").strip():
                        updates["website"] = li["website"]
                    _push_log(f"  LI: {li.get('setor') or 'encontrado'}", "SUCCESS")
                else:
                    _push_log("  LI: não encontrado", "DIM")
            except Exception as exc:
                _push_log(f"  LI erro: {exc}", "ERROR")
                _log.exception("LinkedIn error for cnpj=%s", cnpj)

            time.sleep(random.uniform(3.0, 7.0))

        # ── Lead scoring ──────────────────────────────────────────────────────
        if modules.get("score", True):
            merged = {**lead, **updates}
            sc = calculate_score(merged)
            updates["lead_score"] = sc["score"]
            updates["lead_tier"]  = sc["tier"]

        # Save enrichment back to DB
        if updates:
            merged = {**lead, **updates}
            upsert_lead(merged, campanha=campanha or lead.get("campanha", ""))

        done += 1
        pct = round(done / total * 100)
        sse.push(stream_id, "progress", {"pct": min(pct, 99), "done": done, "total": total})

    _push_log(f"Pipeline concluído — {done}/{total} leads processados.", "SUCCESS")
    sse.push(stream_id, "progress", {"pct": 100, "done": done, "total": total})
    sse.push(stream_id, "done", {})
