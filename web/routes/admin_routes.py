"""
web/routes/admin_routes.py — Painel administrativo de usuários.
Todas as rotas exigem role admin ou master.
"""
import logging
from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from web.auth     import admin_required, csrf_protect
from web.security import audit, rate_limit
from web.users_db import (
    approve_user, delete_user, get_all, get_by_id,
    get_stats, promote_user, reject_user,
)

_log = logging.getLogger("sigaway.admin")
bp   = Blueprint("admin", __name__)


@bp.get("/users")
@admin_required
def users():
    all_users = get_all()
    stats     = get_stats()
    return render_template("admin_users.html",
                           active="admin",
                           users=all_users,
                           stats=stats)


@bp.get("/users/data")
@admin_required
def users_data():
    status = request.args.get("status", "")
    rows   = get_all(status or None)
    # Remove password_hash antes de enviar ao frontend
    for r in rows:
        r.pop("password_hash", None)
        r.pop("totp_secret",   None)
        r.pop("reset_token",   None)
    return jsonify(rows)


@bp.post("/users/<int:uid>/approve")
@admin_required
@csrf_protect
@rate_limit(max_requests=30, window_s=60, scope="admin_approve")
def approve(uid: int):
    actor = session.get("user", "admin")
    user  = get_by_id(uid)
    if not user:
        return jsonify({"error": "Usuário não encontrado."}), 404
    ok = approve_user(uid, actor)
    audit("INFO", "USER_APPROVED",
          f"id={uid} username={user['username']} by={actor}")
    _log.info("Usuário %s aprovado por %s", user["username"], actor)
    return jsonify({"ok": ok, "status": "approved"})


@bp.post("/users/<int:uid>/reject")
@admin_required
@csrf_protect
@rate_limit(max_requests=30, window_s=60, scope="admin_reject")
def reject(uid: int):
    actor = session.get("user", "admin")
    user  = get_by_id(uid)
    if not user:
        return jsonify({"error": "Usuário não encontrado."}), 404
    notes = (request.json or {}).get("notes", "")
    ok    = reject_user(uid, actor, notes)
    audit("WARNING", "USER_REJECTED",
          f"id={uid} username={user['username']} by={actor}")
    return jsonify({"ok": ok, "status": "rejected"})


@bp.post("/users/<int:uid>/delete")
@admin_required
@csrf_protect
def remove(uid: int):
    actor = session.get("user", "admin")
    user  = get_by_id(uid)
    if not user:
        return jsonify({"error": "Usuário não encontrado."}), 404
    ok = delete_user(uid)
    audit("WARNING", "USER_DELETED",
          f"id={uid} username={user['username']} by={actor}")
    return jsonify({"ok": ok})


@bp.post("/users/<int:uid>/promote")
@admin_required
@csrf_protect
def promote(uid: int):
    actor = session.get("user", "admin")
    role  = (request.json or {}).get("role", "user")
    user  = get_by_id(uid)
    if not user:
        return jsonify({"error": "Usuário não encontrado."}), 404
    ok = promote_user(uid, role)
    audit("INFO", "USER_PROMOTED",
          f"id={uid} username={user['username']} role={role} by={actor}")
    return jsonify({"ok": ok})
