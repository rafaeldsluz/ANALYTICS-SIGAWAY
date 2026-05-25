"""
Rotas do módulo SDR Agent.
Inclui o webhook receptor (que o n8n chama) com validação HMAC,
e a interface de controle do n8n.
"""
import hmac
import hashlib
import json
import logging
import os
from pathlib import Path

from flask import (
    Blueprint, Response, render_template,
    request, jsonify, stream_with_context, send_file,
)

from web.auth     import admin_required, csrf_protect
from web.security import audit, rate_limit, sanitize_int, sanitize_str
from web.sse import sse

_log = logging.getLogger("sigaway.sdr")
bp   = Blueprint("sdr", __name__)

ROOT = Path(__file__).parent.parent.parent
_FLOW_PATH = ROOT / "n8n" / "SDR (Otimizado Tokens) (26).json"

SDR_STREAM = "sdr-live"

# Segredo compartilhado com o n8n para validar webhooks (HMAC-SHA256)
_WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")


def _verify_webhook_hmac(body: bytes, signature: str) -> bool:
    """Valida assinatura HMAC-SHA256 do webhook do n8n."""
    if not _WEBHOOK_SECRET:
        return True   # sem segredo configurado: permite (com aviso no startup)
    expected = hmac.new(
        _WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    if not signature:
        return False
    return hmac.compare_digest(signature, expected)


# ── Página principal ──────────────────────────────────────────────────────────

@bp.get("/")
@admin_required
def index():
    from sdr.db import init_db, get_stats, get_recent_messages
    init_db()
    stats    = get_stats()
    messages = get_recent_messages(100)
    webhook_url = _webhook_url()
    return render_template(
        "sdr.html",
        active="sdr",
        stats=stats,
        messages=messages,
        webhook_url=webhook_url,
        n8n_url=os.getenv("N8N_URL", ""),
        n8n_workflow_id=os.getenv("N8N_WORKFLOW_ID", ""),
        webhook_secret_set=bool(_WEBHOOK_SECRET),
    )


# ── SSE feed em tempo real ────────────────────────────────────────────────────

@bp.get("/stream")
@admin_required
def stream():
    return Response(
        stream_with_context(_sdr_stream()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sdr_stream():
    import queue as _q
    q = sse.create(SDR_STREAM)
    try:
        while True:
            try:
                payload = q.get(timeout=25)
                yield f"data: {json.dumps(payload)}\n\n"
            except _q.Empty:
                yield ": keepalive\n\n"
    finally:
        pass


# ── Webhook receptor (recebe dados do n8n) ────────────────────────────────────

@bp.post("/webhook")
@rate_limit(max_requests=300, window_s=60, scope="sdr_webhook")
def webhook():
    """Endpoint que o n8n chama para registrar cada mensagem da conversa."""
    body      = request.get_data()
    signature = request.headers.get("X-Webhook-Signature", "")

    if not _verify_webhook_hmac(body, signature):
        audit("WARNING", "WEBHOOK_INVALID_SIGNATURE",
              f"ip={request.remote_addr}")
        return jsonify({"ok": False, "error": "Assinatura inválida"}), 401

    from sdr.db import init_db, upsert_conversation, record_message
    from sdr.analyzer import detect_conversion
    init_db()

    data = json.loads(body) if body else {}

    session_id = sanitize_str(
        data.get("session_id") or data.get("telefone") or data.get("phone", ""),
        max_len=64
    )
    nome      = sanitize_str(data.get("nome") or data.get("name", ""), max_len=120)
    direction = "out" if data.get("from_me") else "in"
    content   = sanitize_str(
        data.get("mensagem") or data.get("message") or data.get("text", ""),
        max_len=2000
    )
    msg_type  = sanitize_str(data.get("tipo") or data.get("type", "text"), max_len=32)

    if not session_id:
        return jsonify({"ok": False, "error": "session_id required"}), 400

    upsert_conversation(session_id, nome)
    kw = detect_conversion(content)
    record_message(session_id, direction, content, msg_type, kw)

    from sdr.db import get_stats
    stats = get_stats()
    sse.push(SDR_STREAM, "message", {
        "hora":      _now_str(),
        "nome":      nome or session_id,
        "direction": direction,
        "msg_type":  msg_type,
        "content":   content[:160],
        "keyword":   kw,
        "stats":     stats,
    })

    return jsonify({"ok": True, "converted": bool(kw), "keyword": kw})


@bp.post("/error")
@rate_limit(max_requests=60, window_s=60, scope="sdr_error")
def error():
    """Endpoint que o n8n chama em caso de erro de execução."""
    body      = request.get_data()
    signature = request.headers.get("X-Webhook-Signature", "")

    if not _verify_webhook_hmac(body, signature):
        audit("WARNING", "WEBHOOK_ERROR_INVALID_SIG", f"ip={request.remote_addr}")
        return jsonify({"ok": False, "error": "Assinatura inválida"}), 401

    from sdr.db import init_db, record_error, get_stats
    init_db()

    data = json.loads(body) if body else {}
    record_error(
        workflow_id  = sanitize_str(data.get("workflow_id", ""),  max_len=64),
        execution_id = sanitize_str(data.get("execution_id", ""), max_len=64),
        node_name    = sanitize_str(data.get("node_name", ""),    max_len=128),
        error_msg    = sanitize_str(data.get("error", ""),        max_len=500),
    )

    stats = get_stats()
    sse.push(SDR_STREAM, "error_update", {"stats": stats})
    return jsonify({"ok": True})


@bp.get("/health")
def health():
    return jsonify({"status": "ok", "webhook": _webhook_url()})


# ── API de controle ───────────────────────────────────────────────────────────

@bp.get("/stats")
@admin_required
def stats():
    from sdr.db import init_db, get_stats
    init_db()
    return jsonify(get_stats())


@bp.get("/messages")
@admin_required
def messages():
    from sdr.db import init_db, get_recent_messages
    init_db()
    limit = sanitize_int(request.args.get("limit", 100), default=100, min_v=1, max_v=5000)
    return jsonify(get_recent_messages(limit))


@bp.post("/check-status")
@admin_required
@csrf_protect
@rate_limit(max_requests=15, window_s=60, scope="sdr_check")
def check_status():
    data    = request.json or {}
    n8n_url = sanitize_str(data.get("n8n_url", ""),      max_len=256).strip()
    wf_id   = sanitize_str(data.get("workflow_id", ""),  max_len=64).strip()
    api_key = sanitize_str(data.get("api_key", ""),      max_len=128).strip()

    if not n8n_url or not wf_id:
        return jsonify({"error": "n8n_url e workflow_id são obrigatórios."}), 400

    try:
        from sdr.server import get_workflow_status
        info = get_workflow_status(n8n_url, wf_id, api_key)
        return jsonify(info)
    except Exception as e:
        _log.error("check-status error: %s", e)
        return jsonify({"error": "Falha ao consultar status."}), 500


@bp.post("/toggle")
@admin_required
@csrf_protect
@rate_limit(max_requests=10, window_s=60, scope="sdr_toggle")
def toggle():
    data    = request.json or {}
    n8n_url = sanitize_str(data.get("n8n_url", ""),     max_len=256).strip()
    wf_id   = sanitize_str(data.get("workflow_id", ""), max_len=64).strip()
    api_key = sanitize_str(data.get("api_key", ""),     max_len=128).strip()
    active  = bool(data.get("active", True))

    if not n8n_url or not wf_id:
        return jsonify({"error": "n8n_url e workflow_id são obrigatórios."}), 400

    audit("INFO", "SDR_WORKFLOW_TOGGLE", f"wf={wf_id} active={active}")
    try:
        from sdr.server import set_workflow_active
        result = set_workflow_active(n8n_url, wf_id, api_key, active)
        return jsonify({"active": result})
    except Exception as e:
        _log.error("toggle error: %s", e)
        return jsonify({"error": "Falha ao alterar estado do workflow."}), 500


@bp.post("/fetch-errors")
@admin_required
@csrf_protect
@rate_limit(max_requests=10, window_s=60, scope="sdr_fetch_err")
def fetch_errors():
    data    = request.json or {}
    n8n_url = sanitize_str(data.get("n8n_url", ""),     max_len=256).strip()
    wf_id   = sanitize_str(data.get("workflow_id", ""), max_len=64).strip()
    api_key = sanitize_str(data.get("api_key", ""),     max_len=128).strip()

    if not n8n_url or not wf_id:
        return jsonify({"error": "Preencha URL e Workflow ID."}), 400

    try:
        from sdr.server import get_execution_errors
        from sdr.db import record_error, get_stats
        execs = get_execution_errors(n8n_url, wf_id, api_key, limit=20)
        for ex in execs:
            record_error(
                workflow_id  = wf_id,
                execution_id = str(ex.get("id", "")),
                node_name    = str(ex.get("stoppedAt", ""))[:128],
                error_msg    = str(
                    ex.get("data", {}).get("resultData", {})
                      .get("error", {}).get("message", "Desconhecido")
                )[:500],
            )
        stats = get_stats()
        sse.push(SDR_STREAM, "error_update", {"stats": stats})
        return jsonify({"imported": len(execs), "stats": stats})
    except Exception as e:
        _log.error("fetch-errors error: %s", e)
        return jsonify({"error": "Falha ao importar erros."}), 500


@bp.get("/export")
@admin_required
def export():
    import csv, tempfile
    from sdr.db import init_db, get_recent_messages
    from datetime import datetime
    init_db()

    rows = get_recent_messages(5000)
    if not rows:
        return jsonify({"error": "Sem dados para exportar."}), 404

    fd, tmp = tempfile.mkstemp(
        suffix=".csv",
        prefix=f"sdr_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}_",
    )
    import os as _os
    _os.close(fd)
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)

    audit("INFO", "SDR_EXPORT", f"rows={len(rows)}")
    return send_file(tmp, as_attachment=True, download_name="sdr_historico.csv")


@bp.post("/clear")
@admin_required
@csrf_protect
def clear():
    from sdr.db import clear_all
    audit("WARNING", "SDR_CLEAR_ALL", f"ip={request.remote_addr}")
    clear_all()
    return jsonify({"ok": True})


@bp.get("/dashboard")
@admin_required
def dashboard():
    from sdr.db import init_db, get_dashboard_data
    init_db()
    data = get_dashboard_data(days=30)
    return render_template("sdr_dashboard.html", active="sdr-dashboard", **data)


@bp.get("/dashboard/data")
@admin_required
def dashboard_data():
    from sdr.db import init_db, get_dashboard_data
    init_db()
    days = sanitize_int(request.args.get("days", 30), default=30, min_v=1, max_v=365)
    return jsonify(get_dashboard_data(days=days))


@bp.get("/flow-info")
@admin_required
def flow_info():
    if not _FLOW_PATH.exists():
        return jsonify({"error": "Arquivo de fluxo não encontrado."}), 404
    try:
        with open(_FLOW_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        _log.error("flow-info JSON inválido: %s", e)
        return jsonify({"error": "Arquivo de fluxo inválido."}), 400

    nodes = data.get("nodes", [])
    system_prompt = ""
    for node in nodes:
        if node.get("type") == "@n8n/n8n-nodes-langchain.agent":
            sp = node.get("parameters", {}).get("options", {}).get("systemMessage", "")
            if sp.startswith("="):
                sp = sp[1:]
            system_prompt = sp
            break
    return jsonify({
        "name":          data.get("name", ""),
        "node_count":    len(nodes),
        "has_ai_agent":  bool(system_prompt),
        "system_prompt": system_prompt,
    })


@bp.post("/import-flow")
@admin_required
@csrf_protect
def import_flow():
    data    = request.json or {}
    n8n_url = sanitize_str(data.get("n8n_url", ""), max_len=256).strip()
    api_key = sanitize_str(data.get("api_key", ""), max_len=128).strip()
    if not n8n_url:
        return jsonify({"error": "URL do n8n é obrigatória."}), 400
    if not _FLOW_PATH.exists():
        return jsonify({"error": "Arquivo de fluxo não encontrado."}), 404
    try:
        with open(_FLOW_PATH, encoding="utf-8") as f:
            workflow_data = json.load(f)
        from sdr.server import import_workflow
        result = import_workflow(n8n_url, api_key, workflow_data)
        audit("INFO", "SDR_FLOW_IMPORTED", f"wf={result.get('id')}")
        return jsonify({"ok": True, "workflow_id": result["id"], "name": result["name"]})
    except Exception as e:
        _log.error("import-flow error: %s", e)
        return jsonify({"error": "Falha ao importar fluxo."}), 500


# ── Helpers ───────────────────────────────────────────────────────────────────

def _webhook_url() -> str:
    try:
        host = request.host if request else "localhost:5000"
        return f"http://{host}/sdr/webhook"
    except Exception:
        return "http://localhost:5000/sdr/webhook"


def _now_str() -> str:
    from datetime import datetime
    return datetime.now().strftime("%H:%M:%S")
