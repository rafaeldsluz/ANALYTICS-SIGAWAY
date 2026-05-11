"""
SDR — Servidor Flask: webhook receptor + proxy para a API REST do n8n.
Roda em thread daemon ao lado da UI Tkinter.
"""
import logging
import os
import socket
import threading
from typing import Callable

logger = logging.getLogger(__name__)

_update_cb: Callable | None = None
_flask_port: int = 5050


def set_update_callback(cb: Callable) -> None:
    global _update_cb
    _update_cb = cb


def _notify() -> None:
    if _update_cb:
        try:
            _update_cb()
        except Exception:
            pass


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def get_webhook_url(port: int | None = None) -> str:
    p = port or _flask_port
    return f"http://{get_local_ip()}:{p}/sdr/webhook"


# ── Flask app ─────────────────────────────────────────────────────────────────

def _make_flask_app():
    from flask import Flask, request, jsonify
    from sdr.db import upsert_conversation, record_message, record_error
    from sdr.analyzer import detect_conversion

    app = Flask(__name__)

    @app.route("/sdr/webhook", methods=["POST"])
    def sdr_webhook():
        data = request.get_json(force=True, silent=True) or {}

        # Campos compatíveis com o payload do n8n (Edit Fields node)
        session_id = (
            data.get("session_id")
            or data.get("telefone")
            or data.get("phone", "")
        )
        nome      = data.get("nome") or data.get("name", "")
        direction = "out" if data.get("from_me") else "in"
        content   = (
            data.get("mensagem")
            or data.get("message")
            or data.get("text", "")
        )
        msg_type  = data.get("tipo") or data.get("type", "text")

        if not session_id:
            return jsonify({"ok": False, "error": "session_id required"}), 400

        upsert_conversation(session_id, nome)
        kw = detect_conversion(content)
        record_message(session_id, direction, content, msg_type, kw)

        if kw:
            logger.info(f"[SDR] Conversão detectada ({session_id}): '{kw}'")

        _notify()
        return jsonify({"ok": True, "converted": bool(kw), "keyword": kw})

    @app.route("/sdr/error", methods=["POST"])
    def sdr_error():
        data = request.get_json(force=True, silent=True) or {}
        record_error(
            workflow_id  = data.get("workflow_id", ""),
            execution_id = data.get("execution_id", ""),
            node_name    = data.get("node_name", ""),
            error_msg    = data.get("error", ""),
        )
        _notify()
        return jsonify({"ok": True})

    @app.route("/sdr/health")
    def health():
        return jsonify({"status": "ok", "webhook": get_webhook_url()})

    return app


# ── n8n REST API ──────────────────────────────────────────────────────────────

def _headers(api_key: str) -> dict:
    return {"X-N8N-API-KEY": api_key, "Content-Type": "application/json"}


def get_workflow_status(n8n_url: str, workflow_id: str, api_key: str) -> dict:
    import requests as _req
    r = _req.get(
        f"{n8n_url.rstrip('/')}/api/v1/workflows/{workflow_id}",
        headers=_headers(api_key),
        timeout=10,
    )
    r.raise_for_status()
    d = r.json()
    return {"active": d.get("active", False), "name": d.get("name", workflow_id)}


def set_workflow_active(
    n8n_url: str, workflow_id: str, api_key: str, active: bool
) -> bool:
    import requests as _req
    action = "activate" if active else "deactivate"
    r = _req.post(
        f"{n8n_url.rstrip('/')}/api/v1/workflows/{workflow_id}/{action}",
        headers=_headers(api_key),
        timeout=10,
    )
    r.raise_for_status()
    return r.json().get("active", active)


def get_execution_errors(
    n8n_url: str, workflow_id: str, api_key: str, limit: int = 20
) -> list[dict]:
    import requests as _req
    r = _req.get(
        f"{n8n_url.rstrip('/')}/api/v1/executions",
        params={"workflowId": workflow_id, "status": "error", "limit": limit},
        headers=_headers(api_key),
        timeout=10,
    )
    r.raise_for_status()
    return r.json().get("data", [])


def import_workflow(n8n_url: str, api_key: str, workflow_data: dict) -> dict:
    import requests as _req
    _STRIP = {"id", "createdAt", "updatedAt", "versionId"}
    payload = {k: v for k, v in workflow_data.items() if k not in _STRIP}
    r = _req.post(
        f"{n8n_url.rstrip('/')}/api/v1/workflows",
        headers=_headers(api_key),
        json=payload,
        timeout=30,
    )
    r.raise_for_status()
    d = r.json()
    return {"id": str(d.get("id", "")), "name": d.get("name", "")}


# ── Server thread ─────────────────────────────────────────────────────────────

def start_server_thread(port: int = 5050) -> None:
    global _flask_port
    _flask_port = port

    def _run():
        from sdr.db import init_db
        init_db()

        flask_app = _make_flask_app()
        # Silence werkzeug
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        flask_app.run(
            host="0.0.0.0",
            port=port,
            debug=False,
            use_reloader=False,
        )

    t = threading.Thread(target=_run, daemon=True, name="sdr-webhook")
    t.start()
    logger.info(f"[SDR] Webhook server → {get_webhook_url(port)}")
