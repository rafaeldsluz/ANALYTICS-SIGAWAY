"""
Rotas do módulo E-mail Agent.
"""
import logging
import os
import threading
import uuid
from pathlib import Path

from flask import (
    Blueprint, Response, redirect, render_template,
    request, jsonify, stream_with_context,
)

from web.auth     import csrf_protect, login_required
from web.security import (
    audit, rate_limit,
    sanitize_email, sanitize_int, sanitize_str,
    validate_file_upload, validate_redirect_url,
)

_log = logging.getLogger("sigaway.email")

# GIF transparente 1×1 — resposta ao pixel de rastreamento
_PIXEL_GIF = bytes([
    0x47,0x49,0x46,0x38,0x39,0x61,0x01,0x00,0x01,0x00,
    0x80,0x00,0x00,0xff,0xff,0xff,0x00,0x00,0x00,0x21,
    0xf9,0x04,0x00,0x00,0x00,0x00,0x00,0x2c,0x00,0x00,
    0x00,0x00,0x01,0x00,0x01,0x00,0x00,0x02,0x02,0x44,
    0x01,0x00,0x3b,
])

from web.sse import sse

bp = Blueprint("email", __name__)

UPLOAD_DIR = Path(__file__).parent.parent.parent / ".tmp" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_EXCEL = Path(__file__).parent.parent.parent / "disparo e-mkt.xlsx"

# Estado global da campanha de e-mail
_campaign: dict = {"id": None, "db_id": None, "stop": None, "running": None, "thread": None}


@bp.get("/")
@login_required
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
        sigaway_pass="",       # nunca expõe senha padrão ao template
        smtp_user=os.getenv("SMTP_USER", ""),
        smtp_pass="",          # nunca expõe senha ao template
        default_excel=str(DEFAULT_EXCEL),
        excel_count=excel_count,
        excel_error=excel_error,
        history=history,
    )


@bp.post("/start")
@login_required
@csrf_protect
@rate_limit(max_requests=5, window_s=60, scope="email_start")
def start():
    global _campaign
    if _campaign["thread"] and _campaign["thread"].is_alive():
        return jsonify({"error": "Campanha já em execução."}), 409

    data = request.json or {}
    audit("INFO", "CAMPAIGN_START", f"ip={request.remote_addr}")
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
@login_required
def status():
    t = _campaign.get("thread")
    running = bool(t and t.is_alive())
    return jsonify({
        "running": running,
        "stream_id": _campaign.get("id"),
        "db_id": _campaign.get("db_id"),
    })


@bp.post("/finish/<campaign_id>")
@login_required
@csrf_protect
def finish_campaign_route(campaign_id: str):
    from execution.email_db import init_db, finish_campaign
    init_db()
    finish_campaign(campaign_id)
    return jsonify({"ok": True})


@bp.post("/resume/<campaign_id>")
@login_required
@csrf_protect
@rate_limit(max_requests=5, window_s=60, scope="email_resume")
def resume_campaign(campaign_id: str):
    global _campaign
    if _campaign["thread"] and _campaign["thread"].is_alive():
        return jsonify({"error": "Outra campanha já está em execução."}), 409

    data = request.json or {}
    stream_id = str(uuid.uuid4())

    stop    = threading.Event()
    running = threading.Event()
    running.set()

    _campaign = {
        "id":      stream_id,
        "db_id":   campaign_id,
        "stop":    stop,
        "running": running,
        "thread":  None,
    }

    t = threading.Thread(
        target=_run_email_campaign_resume,
        args=(data, stream_id, campaign_id, stop, running),
        daemon=True,
    )
    _campaign["thread"] = t
    t.start()

    return jsonify({"stream_id": stream_id})


@bp.post("/stop")
@login_required
@csrf_protect
def stop():
    if _campaign["stop"]:
        _campaign["stop"].set()
        if _campaign["running"]:
            _campaign["running"].set()
    return jsonify({"ok": True})


@bp.post("/pause")
@login_required
@csrf_protect
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
@login_required
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
@login_required
def history():
    from execution.email_db import init_db, get_recent_campaigns
    init_db()
    rows = get_recent_campaigns(10)
    return jsonify(rows)


@bp.get("/history/<campaign_id>")
@login_required
def history_sends(campaign_id: str):
    from execution.email_db import init_db, get_campaign_sends
    init_db()
    rows = get_campaign_sends(campaign_id)
    return jsonify(rows)


@bp.get("/track/open/<token>")
def track_open(token: str):
    from execution.email_db import record_open
    record_open(
        token,
        request.headers.get("User-Agent", ""),
        request.remote_addr or "",
    )
    return Response(
        _PIXEL_GIF,
        mimetype="image/gif",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"},
    )


@bp.get("/track/click/<token>")
@rate_limit(max_requests=60, window_s=60, scope="track_click")
def track_click(token: str):
    from execution.email_db import record_click
    from urllib.parse import unquote
    raw = request.args.get("u", "")
    if len(raw) > 2048:
        return Response("URL inválida", status=400)
    url = unquote(raw)
    if not validate_redirect_url(url):
        audit("WARNING", "INVALID_REDIRECT", f"token={token} url={url[:100]}")
        return Response("Destino não permitido", status=403)
    record_click(token, url, request.headers.get("User-Agent", ""), request.remote_addr or "")
    return redirect(url, code=302)


@bp.get("/analytics-data")
@login_required
def analytics_data():
    from execution.email_db import init_db, get_analytics_data
    init_db()
    return jsonify(get_analytics_data(30))


@bp.get("/analytics-detail/<campaign_id>")
@login_required
def analytics_detail(campaign_id: str):
    from execution.email_db import init_db, get_campaign_opens, get_campaign_clicks
    init_db()
    return jsonify({
        "opens":  get_campaign_opens(campaign_id),
        "clicks": get_campaign_clicks(campaign_id),
    })


@bp.post("/upload-excel")
@login_required
@csrf_protect
@rate_limit(max_requests=10, window_s=60, scope="upload_excel")
def upload_excel():
    f = request.files.get("file")
    valid, err = validate_file_upload(f)
    if not valid:
        audit("WARNING", "UPLOAD_REJECTED", err)
        return jsonify({"error": err}), 400
    # Nome gerado por UUID — evita path traversal e colisões
    safe_name = f"{uuid.uuid4().hex}.xlsx"
    dest = UPLOAD_DIR / safe_name
    f.save(str(dest))
    audit("INFO", "UPLOAD_OK", f"original={f.filename} saved={safe_name}")
    return jsonify({"path": str(dest), "name": safe_name, "original": f.filename})


@bp.post("/test-email")
@login_required
@csrf_protect
@rate_limit(max_requests=3, window_s=60, scope="test_email")
def test_email():
    data      = request.json or {}
    email     = sanitize_email(data.get("email", ""))
    subject   = sanitize_str(data.get("subject", "Teste — Sigaway Agent"), max_len=200)
    body      = sanitize_str(data.get("body", ""), max_len=5000)
    smtp_user = sanitize_str(data.get("smtp_user", ""), max_len=254)
    smtp_pass = data.get("smtp_pass", "")   # senha não deve sofrer escape HTML

    if not email:
        return jsonify({"error": "E-mail inválido."}), 400

    audit("INFO", "TEST_EMAIL_SENT", f"to={email}")

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
        except Exception as exc:
            _log.error("Erro ao enviar e-mail de teste: %s", exc)

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

    _tracking_base = os.getenv("TRACKING_BASE_URL", "").rstrip("/")

    skip_sent = cfg.get("skip_sent", True)
    already_sent = get_all_sent_emails() if skip_sent else set()

    sent = errors = no_email = skipped = total = 0
    try:
        _push("Carregando destinatários do Excel...")
        recs  = load_recipients(cfg.get("excel_path", ""))
        total = len(recs)
        _push(f"{total} destinatários carregados.")

        start_campaign(campaign_id, cfg.get("excel_path", ""), total, name=(cfg.get("name") or cfg.get("subject", ""))[:120])

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

                token = _uuid.uuid4().hex

                _push(f"  Enviando para {email}" + (f"  CC: {cc}" if cc else "") + "...")
                send_email(
                    to_email=email, subject=cfg["subject"],
                    corpo=cfg["email_body"], cc_email=cc,
                    screenshot_path=shot,
                    smtp_user=cfg["smtp_user"],
                    smtp_password=cfg["smtp_pass"],
                    tracking_base=_tracking_base,
                    tracking_token=token,
                )
                sent += 1
                already_sent.add(email.lower())
                record_send(campaign_id, cliente, email, "sent", tracking_token=token)
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


def _run_email_campaign_resume(cfg: dict, stream_id: str, campaign_id: str, stop, running):
    import random
    import time
    from pathlib import Path as _Path
    from execution.excel_reader import load_recipients
    from execution.screenshot   import run_capture
    from execution.email_db import (
        init_db, record_send, finish_campaign,
        get_campaign_sends, get_campaign_stats,
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

    _tracking_base = os.getenv("TRACKING_BASE_URL", "").rstrip("/")

    already_done  = get_campaign_sends(campaign_id)
    done_emails   = {s["email"].lower() for s in already_done if s.get("email")}
    done_clientes = {s["cliente"] for s in already_done if not s.get("email")}

    stats      = get_campaign_stats(campaign_id)
    excel_path = cfg.get("excel_path") or stats.get("excel_path", "")

    sent = errors = no_email = skipped = total = 0
    try:
        _push(f"Retomando campanha {campaign_id[-20:]}...")
        _push("Carregando destinatários do Excel...")
        all_recs = load_recipients(excel_path)

        recs = []
        for r in all_recs:
            em = (r.get("email") or "").lower()
            cl = r.get("cliente", "")
            if em and em in done_emails:
                skipped += 1
            elif not em and cl in done_clientes:
                skipped += 1
            else:
                recs.append(r)

        total = len(recs)
        _push(f"{len(all_recs)} no Excel — {skipped} já processados, {total} restantes.")

        if total == 0:
            _push("Todos os destinatários já foram processados.", "WARNING")
            finish_campaign(campaign_id)
            sse.push(stream_id, "done", {
                "sent": 0, "errors": 0, "skipped": skipped, "no_email": 0, "total": 0,
            })
            return

        global_cc = cfg.get("cc", "").strip()

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
            cc_list = list(rec.get("cc_list", []))
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

            try:
                _push("  Capturando screenshot...")
                shot = run_capture(
                    cfg["url"], cfg["username"], cfg["password"], cliente,
                    period_type=cfg.get("period_type", "PREV_MONTH"),
                    date_start=cfg.get("date_start", ""),
                    date_end=cfg.get("date_end", ""),
                )
                import uuid as _uuid_mod
                token = _uuid_mod.uuid4().hex

                _push(f"  Enviando para {email}" + (f"  CC: {cc}" if cc else "") + "...")
                send_email(
                    to_email=email, subject=cfg["subject"],
                    corpo=cfg["email_body"], cc_email=cc,
                    screenshot_path=shot,
                    smtp_user=cfg["smtp_user"],
                    smtp_password=cfg["smtp_pass"],
                    tracking_base=_tracking_base,
                    tracking_token=token,
                )
                sent += 1
                done_emails.add(email.lower())
                record_send(campaign_id, cliente, email, "sent", tracking_token=token)
                _push("  ✓ Enviado.", "SUCCESS")
                try:
                    _Path(shot).unlink(missing_ok=True)
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
