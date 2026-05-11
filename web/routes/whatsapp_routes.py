"""
Rotas do módulo WhatsApp.
"""
import os
import threading
import uuid

from flask import (
    Blueprint, Response, render_template,
    request, jsonify, stream_with_context,
)

from web.sse import sse

bp = Blueprint("whatsapp", __name__)
_campaign: dict = {"id": None, "stop": None, "thread": None, "queue": None}


@bp.get("/")
def index():
    return render_template(
        "whatsapp.html",
        active="whatsapp",
        wz_base_url=os.getenv("WZ_BASE_URL", ""),
        wz_instance=os.getenv("WZ_INSTANCE", ""),
    )


@bp.post("/start")
def start():
    global _campaign
    if _campaign["thread"] and _campaign["thread"].is_alive():
        return jsonify({"error": "Disparo já em andamento."}), 409

    data = request.json or {}
    stream_id = str(uuid.uuid4())
    stop = threading.Event()

    _campaign = {"id": stream_id, "stop": stop, "thread": None, "queue": None}

    t = threading.Thread(
        target=_run_whatsapp, args=(data, stream_id, stop), daemon=True
    )
    _campaign["thread"] = t
    t.start()

    return jsonify({"stream_id": stream_id})


@bp.get("/status")
def status():
    t = _campaign.get("thread")
    running = bool(t and t.is_alive())
    return jsonify({"running": running, "stream_id": _campaign.get("id")})


@bp.post("/stop")
def stop():
    if _campaign.get("stop"):
        _campaign["stop"].set()
        if _campaign.get("queue"):
            _campaign["queue"].stop()
    return jsonify({"ok": True})


@bp.post("/pause")
def pause():
    q = _campaign.get("queue")
    if not q:
        return jsonify({"error": "Nenhum disparo em andamento."}), 400
    if q.is_paused:
        q.resume()
        return jsonify({"paused": False})
    else:
        q.pause()
        return jsonify({"paused": True})


@bp.post("/test-connection")
def test_connection():
    data = request.json or {}
    base_url = data.get("base_url", "")
    api_key  = data.get("api_key", "")
    instance = data.get("instance", "")

    if not all([base_url, api_key, instance]):
        return jsonify({"error": "Preencha URL, API Key e Instância."}), 400

    try:
        from execution.whatsapp_sender import check_instance
        state = check_instance(base_url, api_key, instance)
        return jsonify({"state": state})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.get("/stream/<stream_id>")
def stream(stream_id):
    return Response(
        stream_with_context(sse.listen(stream_id)),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Runner ─────────────────────────────────────────────────────────────────────

def _run_whatsapp(cfg: dict, stream_id: str, stop):
    from execution.excel_reader import load_whatsapp_contacts
    from execution.whatsapp_queue import WhatsAppQueue

    def _log(msg, level="INFO"):
        sse.push(stream_id, "log", {"msg": msg, "level": level})

    try:
        _log("Carregando contatos do Excel...")
        contacts = load_whatsapp_contacts(cfg.get("excel_path", ""))
        if not contacts:
            _log("Nenhum contato válido encontrado.", "ERROR")
            return

        count = len(contacts)
        _log(f"{count} contatos carregados.")

        wz_cfg = {
            "base_url":     cfg.get("base_url", ""),
            "api_key":      cfg.get("api_key", ""),
            "instance":     cfg.get("instance", ""),
            "message":      cfg.get("message", ""),
            "interval_min": int(cfg.get("interval_min", 0)),
            "interval_max": int(cfg.get("interval_max", 0)),
        }

        def _on_stats(s):
            sse.push(stream_id, "stats", s)

        def _on_log(msg, level):
            _log(msg, level)

        def _on_done(err):
            sse.push(stream_id, "done", {"error": err})

        def _on_tick(remaining):
            sse.push(stream_id, "tick", {"remaining": remaining})

        q = WhatsAppQueue(
            on_stats=_on_stats, on_log=_on_log,
            on_done=_on_done, on_tick=_on_tick,
        )
        _campaign["queue"] = q
        q.start(contacts, wz_cfg)

        sse.push(stream_id, "started", {"total": count})

    except Exception as e:
        _log(f"Erro: {e}", "ERROR")
        sse.push(stream_id, "done", {"error": True})
