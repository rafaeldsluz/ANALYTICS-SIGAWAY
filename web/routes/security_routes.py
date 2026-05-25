"""
web/routes/security_routes.py — Dashboard administrativo de segurança.
Exibe eventos de auditoria, estatísticas e alertas de segurança.
"""
from flask import Blueprint, jsonify, render_template, request

from web.auth import admin_required
from web.security import get_audit_events, get_audit_stats

bp = Blueprint("security", __name__)


@bp.get("/")
@admin_required
def dashboard():
    stats  = get_audit_stats()
    events = get_audit_events(limit=100)
    return render_template("security_dashboard.html",
                           active="security",
                           stats=stats,
                           events=events)


@bp.get("/events")
@admin_required
def events():
    level = request.args.get("level", "")
    limit = min(int(request.args.get("limit", 200)), 1000)
    rows  = get_audit_events(limit=limit, level=level or None)
    return jsonify(rows)


@bp.get("/stats")
@admin_required
def stats():
    return jsonify(get_audit_stats())
