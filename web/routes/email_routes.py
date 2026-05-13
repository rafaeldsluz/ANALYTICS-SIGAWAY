"""
Rotas do módulo E-mail Agent.
"""
import os
import threading
import uuid
from pathlib import Path

from flask import (
    Blueprint, Response, render_template,
    request, jsonify, stream_with_context,
)

from web.sse import sse

bp = Blueprint("email", __name__)

UPLOAD_DIR = Path(__file__).parent.parent.parent / ".tmp" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_EXCEL = Path(__file__).parent.parent.parent / "disparo e-mkt.xlsx"

# Estado global da campanha de e-mail
_campaign: dict = {"id": None, "db_id": None, "stop": None, "running": None, "thread": None}


@bp.get("/")
def index():
    from execution.email_db import init_db, get_recent_campaigns
    from execution.excel_reader import load_recipients
    init_db()
    history = get_recent_campaigns(8)

    excel_count = 0
    excel_error = ""
    if DEFAULT_EXCEL.exists():
        try:
            excel_count = len(load_recipients(str(DEFAULT_EXCEL)))
        except Exception as e:
            excel_error = str(e)
    else:
        excel_error = "Arquivo não encontrado."

    return render_template(
        "email.html",
        active="email",
        sigaway_url=os.getenv("SIGAWAY_URL", "https://app.sigaway.com.br"),
        sigaway_user=os.getenv("SIGAWAY_USER", ""),
        sigaway_pass=os.getenv("SIGAWAY_PASS", "Rafa2205!"),
        smtp_user=os.getenv("SMTP_USER", "rafael.luz@sigaway.com.br"),
        smtp_pass=os.getenv("SMTP_PASS", ""),
        default_excel=str(DEFAULT_EXCEL),
        excel_count=excel_count,
        excel_error=excel_error,
        history=history,
    )


@bp.post("/start")
def start():
    global _campaign
    if _campaign["thread"] and _campaign["thread"].is_alive():
        return jsonify({"error": "Campanha já em execução."}), 409

    data = request.json or {}
    stream_id = str(uuid.uuid4())

    stop    = threading.Event()
    running = threading.Event()
    running.set()

    _campaign = {
        "id":      stream_id,
        "stop":    stop,
        "running": running,
        "thread":  None,
    }

    t = threading.Thread(
        target=_run_email_campaign,
        args=(data, stream_id, stop, running),
        daemon=True,
    )
    _campaign["thread"] = t
    t.start()

    return jsonify({"stream_id": stream_id, "db_id": None})


@bp.get("/status")
def status():
    t = _campaign.get("thread")
    running = bool(t and t.is_alive())
    return jsonify({
        "running": running,
        "stream_id": _campaign.get("id"),
        "db_id": _campaign.get("db_id"),
    })


@bp.post("/finish/<campaign_id>")
def finish_campaign_route(campaign_id: str):
    from execution.email_db import init_db, finish_campaign
    init_db()
    finish_campaign(campaign_id)
    return jsonify({"ok": True})


@bp.post("/stop")
def stop():
    if _campaign["stop"]:
        _campaign["stop"].set()
        if _campaign["running"]:
            _campaign["running"].set()
    return jsonify({"ok": True})


@bp.post("/pause")
def pause():
    r = _campaign.get("running")
    if not r:
        return jsonify({"ok": False})
    if r.is_set():
        r.clear()
        return jsonify({"paused": True})
    else:
        r.set()
        return jsonify({"paused": False})


@bp.get("/stream/<stream_id>")
def stream(stream_id):
    return Response(
        stream_with_context(sse.listen(stream_id)),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@bp.get("/history")
def history():
    from execution.email_db import init_db, get_recent_campaigns
    init_db()
    rows = get_recent_campaigns(10)
    return jsonify(rows)


@bp.get("/history/<campaign_id>")
def history_sends(campaign_id: str):
    from execution.email_db import init_db, get_campaign_sends
    init_db()
    rows = get_campaign_sends(campaign_id)
    return jsonify(rows)


@bp.post("/upload-excel")
def upload_excel():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "Nenhum arquivo enviado."}), 400
    safe = Path(f.filename).name
    dest = UPLOAD_DIR / safe
    f.save(str(dest))
    return jsonify({"path": str(dest), "name": safe})


@bp.post("/test-email")
def test_email():
    data = request.json or {}
    email   = data.get("email", "").strip()
    subject = data.get("subject", "Teste — Sigaway Agent")
    body    = data.get("body", "")
    smtp_user = data.get("smtp_user", "")
    smtp_pass = data.get("smtp_pass", "")

    if not email or "@" not in email:
        return jsonify({"error": "E-mail inválido."}), 400

    def _run():
        from enviar_email import send_email
        try:
            send_email(
                to_email=email,
                subject=f"[TESTE] {subject}",
                corpo=body,
                smtp_user=smtp_user,
                smtp_password=smtp_pass,
            )
        except Exception as e:
            pass  # Resultado via SSE não aplicável aqui; retornar no response

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "msg": f"Enviando teste para {email}..."})


# ── Runner ─────────────────────────────────────────────────────────────────────

def _run_email_campaign(cfg: dict, stream_id: str, stop, running):
    import random
    import time
    import uuid as _uuid
    from datetime import datetime as _dt
    from execution.excel_reader import load_recipients
    from execution.screenshot   import run_capture
    from execution.email_db import (
        init_db, start_campaign, record_send,
        finish_campaign, get_campaign_stats, get_all_sent_emails,
    )
    from enviar_email import send_email

    def _push(msg, level="INFO", **extra):
        sse.push(stream_id, "log", {"msg": msg, "level": level, **extra})

    def _progress(i, total, sent, errors, skipped, no_email):
        pct = round(i / total * 100) if total else 0
        sse.push(stream_id, "progress", {
            "i": i, "total": total, "sent": sent,
            "errors": errors, "skipped": skipped,
            "no_email": no_email, "pct": pct,
        })

    init_db()
    campaign_id = f"em_{_dt.now().strftime('%Y%m%d_%H%M%S')}_{_uuid.uuid4().hex[:6]}"
    _campaign["db_id"] = campaign_id

    skip_sent = cfg.get("skip_sent", True)
    already_sent = get_all_sent_emails() if skip_sent else set()

    sent = errors = no_email = skipped = total = 0
    try:
        _push("Carregando destinatários do Excel...")
        recs  = load_recipients(cfg.get("excel_path", ""))
        total = len(recs)
        _push(f"{total} destinatários carregados.")

        start_campaign(campaign_id, cfg.get("excel_path", ""), total)

        for i, rec in enumerate(recs, 1):
            while not running.is_set():
                if stop.is_set():
                    break
                time.sleep(0.3)

            if stop.is_set():
                _push("Campanha interrompida.", "WARNING")
                break

            cliente = rec["cliente"]
            email   = rec["email"]
            cc_list = rec.get("cc_list", [])
            global_cc = cfg.get("cc", "").strip()
            if global_cc and global_cc not in cc_list:
                cc_list = [global_cc] + cc_list
            cc = ", ".join(cc_list)

            _push(f"[{i}/{total}]  {cliente}")

            if not email:
                _push(f"  Sem e-mail para '{cliente}'.", "WARNING")
                no_email += 1
                errors   += 1
                record_send(campaign_id, cliente, "", "no_email")
                _progress(i, total, sent, errors, skipped, no_email)
                continue

            if skip_sent and email.lower() in already_sent:
                skipped += 1
                _push(f"  Pulado — já enviado: {email}", "WARNING")
                record_send(campaign_id, cliente, email, "skipped")
                _progress(i, total, sent, errors, skipped, no_email)
                continue

            try:
                _push("  Capturando screenshot...")
                shot = run_capture(
                    cfg["url"], cfg["username"], cfg["password"], cliente,
                    period_type=cfg.get("period_type", "PREV_MONTH"),
                    date_start=cfg.get("date_start", ""),
                    date_end=cfg.get("date_end", ""),
                )

                _push(f"  Enviando para {email}" + (f"  CC: {cc}" if cc else "") + "...")
                send_email(
                    to_email=email, subject=cfg["subject"],
                    corpo=cfg["email_body"], cc_email=cc,
                    screenshot_path=shot,
                    smtp_user=cfg["smtp_user"],
                    smtp_password=cfg["smtp_pass"],
                )
                sent += 1
                already_sent.add(email.lower())
                record_send(campaign_id, cliente, email, "sent")
                _push("  ✓ Enviado.", "SUCCESS")
                try:
                    Path(shot).unlink(missing_ok=True)
                except Exception:
                    pass
            except Exception as e:
                errors += 1
                record_send(campaign_id, cliente, email, "failed", str(e))
                _push(f"  Erro: {e}", "ERROR")

            _progress(i, total, sent, errors, skipped, no_email)

            if i < total and not stop.is_set():
                delay = random.randint(
                    int(cfg.get("interval_min", 30)),
                    int(cfg.get("interval_max", 90)),
                )
                _push(f"  ⏱  Aguardando {delay}s...")
                for _ in range(delay):
                    if stop.is_set():
                        break
                    running.wait()
                    time.sleep(1)

        finish_campaign(campaign_id)
        _push(
            f"Concluído — Enviados: {sent}  Pulados: {skipped}  "
            f"Falhas: {errors - no_email}  Sem e-mail: {no_email}",
            "SUCCESS",
        )

    except Exception as e:
        _push(f"Erro crítico: {e}", "ERROR")

    finally:
        sse.push(stream_id, "done", {
            "sent": sent, "errors": errors,
            "skipped": skipped, "no_email": no_email, "total": total,
        })
