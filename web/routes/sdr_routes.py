"""
Rotas do módulo SDR Agent.
Inclui o webhook receptor (que antes rodava em porta separada 5050)
e a interface de controle do n8n.
"""
import json
import os
from pathlib import Path

from flask import (
    Blueprint, Response, render_template,
    request, jsonify, stream_with_context, send_file,
)

from web.sse import sse

bp = Blueprint("sdr", __name__)

ROOT = Path(__file__).parent.parent.parent
_FLOW_PATH = ROOT / "n8n" / "SDR (Otimizado Tokens) (26).json"

# Stream ID fixo — o SDR é um feed contínuo, não uma campanha pontual
SDR_STREAM = "sdr-live"


# ── Página principal ──────────────────────────────────────────────────────────

@bp.get("/")
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
    )


# ── SSE feed em tempo real ────────────────────────────────────────────────────

@bp.get("/stream")
def stream():
    """Browser escuta este endpoint para receber atualizações em tempo real."""
    return Response(
        stream_with_context(_sdr_stream()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sdr_stream():
    import queue as _q
    import json
    q = sse.create(SDR_STREAM)
    try:
        while True:
            try:
                payload = q.get(timeout=25)
                yield f"data: {json.dumps(payload)}\n\n"
            except _q.Empty:
                yield ": keepalive\n\n"
    finally:
        pass  # Stream permanece aberto — não fecha ao sair


# ── Webhook receptor (recebe dados do n8n) ────────────────────────────────────

@bp.post("/webhook")
def webhook():
    """Endpoint que o n8n chama para registrar cada mensagem da conversa."""
    from sdr.db import init_db, upsert_conversation, record_message
    from sdr.analyzer import detect_conversion
    init_db()

    data = request.get_json(force=True, silent=True) or {}

    session_id = data.get("session_id") or data.get("telefone") or data.get("phone", "")
    nome       = data.get("nome") or data.get("name", "")
    direction  = "out" if data.get("from_me") else "in"
    content    = data.get("mensagem") or data.get("message") or data.get("text", "")
    msg_type   = data.get("tipo") or data.get("type", "text")

    if not session_id:
        return jsonify({"ok": False, "error": "session_id required"}), 400

    upsert_conversation(session_id, nome)
    kw = detect_conversion(content)
    record_message(session_id, direction, content, msg_type, kw)

    # Notifica browser em tempo real via SSE
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
def error():
    """Endpoint que o n8n chama em caso de erro de execução."""
    from sdr.db import init_db, record_error, get_stats
    init_db()

    data = request.get_json(force=True, silent=True) or {}
    record_error(
        workflow_id  = data.get("workflow_id", ""),
        execution_id = data.get("execution_id", ""),
        node_name    = data.get("node_name", ""),
        error_msg    = data.get("error", ""),
    )

    stats = get_stats()
    sse.push(SDR_STREAM, "error_update", {"stats": stats})
    return jsonify({"ok": True})


@bp.get("/health")
def health():
    return jsonify({"status": "ok", "webhook": _webhook_url()})


# ── API de controle ───────────────────────────────────────────────────────────

@bp.get("/stats")
def stats():
    from sdr.db import init_db, get_stats
    init_db()
    return jsonify(get_stats())


@bp.get("/messages")
def messages():
    from sdr.db import init_db, get_recent_messages
    init_db()
    limit = int(request.args.get("limit", 100))
    return jsonify(get_recent_messages(limit))


@bp.post("/check-status")
def check_status():
    data = request.json or {}
    n8n_url = data.get("n8n_url", "").strip()
    wf_id   = data.get("workflow_id", "").strip()
    api_key = data.get("api_key", "").strip()

    if not n8n_url or not wf_id:
        return jsonify({"error": "n8n_url e workflow_id são obrigatórios."}), 400

    try:
        from sdr.server import get_workflow_status
        info = get_workflow_status(n8n_url, wf_id, api_key)
        return jsonify(info)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.post("/toggle")
def toggle():
    data    = request.json or {}
    n8n_url = data.get("n8n_url", "").strip()
    wf_id   = data.get("workflow_id", "").strip()
    api_key = data.get("api_key", "").strip()
    active  = data.get("active", True)

    if not n8n_url or not wf_id:
        return jsonify({"error": "n8n_url e workflow_id são obrigatórios."}), 400

    try:
        from sdr.server import set_workflow_active
        result = set_workflow_active(n8n_url, wf_id, api_key, active)
        return jsonify({"active": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.post("/fetch-errors")
def fetch_errors():
    data    = request.json or {}
    n8n_url = data.get("n8n_url", "").strip()
    wf_id   = data.get("workflow_id", "").strip()
    api_key = data.get("api_key", "").strip()

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
                node_name    = str(ex.get("stoppedAt", "")),
                error_msg    = str(
                    ex.get("data", {}).get("resultData", {})
                      .get("error", {}).get("message", "Desconhecido")
                ),
            )
        stats = get_stats()
        sse.push(SDR_STREAM, "error_update", {"stats": stats})
        return jsonify({"imported": len(execs), "stats": stats})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.get("/export")
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

    return send_file(tmp, as_attachment=True, download_name="sdr_historico.csv")


@bp.post("/clear")
def clear():
    from sdr.db import clear_all
    clear_all()
    return jsonify({"ok": True})


@bp.get("/dashboard")
def dashboard():
    from sdr.db import init_db, get_dashboard_data
    init_db()
    data = get_dashboard_data(days=30)
    return render_template("sdr_dashboard.html", active="sdr-dashboard", **data)


@bp.get("/dashboard/data")
def dashboard_data():
    from sdr.db import init_db, get_dashboard_data
    init_db()
    days = int(request.args.get("days", 30))
    return jsonify(get_dashboard_data(days=days))


@bp.get("/flow-info")
def flow_info():
    if not _FLOW_PATH.exists():
        return jsonify({"error": "Arquivo de fluxo não encontrado."}), 404
    with open(_FLOW_PATH, encoding="utf-8") as f:
        data = json.load(f)
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
        "name":         data.get("name", ""),
        "node_count":   len(nodes),
        "has_ai_agent": bool(system_prompt),
        "system_prompt": system_prompt,
    })


@bp.post("/import-flow")
def import_flow():
    data    = request.json or {}
    n8n_url = data.get("n8n_url", "").strip()
    api_key = data.get("api_key", "").strip()
    if not n8n_url:
        return jsonify({"error": "URL do n8n é obrigatória."}), 400
    if not _FLOW_PATH.exists():
        return jsonify({"error": "Arquivo de fluxo não encontrado."}), 404
    try:
        with open(_FLOW_PATH, encoding="utf-8") as f:
            workflow_data = json.load(f)
        from sdr.server import import_workflow
        result = import_workflow(n8n_url, api_key, workflow_data)
        return jsonify({"ok": True, "workflow_id": result["id"], "name": result["name"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
