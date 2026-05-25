"""
web/auth.py — Autenticação, CSRF e controle de acesso do Sigaway Analytics.

Hierarquia de roles:
  master  → admin do .env (APP_USERNAME/APP_PASSWORD), acesso total
  admin   → usuário DB promovido, pode gerenciar outros usuários
  user    → colaborador aprovado, acesso às funcionalidades

Fluxo de login:
  1. Verifica credenciais master (.env)  → role='master'
  2. Verifica DB: pending  → bloqueado com mensagem
              rejected → bloqueado com mensagem
              approved → login normal → role= user['role']
"""
import hashlib
import hmac
import logging
import os
import secrets
import smtplib
import ssl
import time
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import wraps

_log = logging.getLogger("sigaway.auth")

from flask import (
    Blueprint, jsonify, redirect, render_template,
    request, session, url_for,
)

bp = Blueprint("auth", __name__)

_APP_USER  = os.getenv("APP_USERNAME", "admin")
_APP_PASS  = os.getenv("APP_PASSWORD", "")

SESSION_TIMEOUT_S = 8 * 3600
CSRF_SESSION_KEY  = "_csrf_token"
CSRF_HEADER       = "X-CSRF-Token"

_PUBLIC_PATHS = ("/login", "/logout", "/register", "/forgot-password", "/reset-password", "/set-password", "/email/track/", "/sdr/health")

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_csrf_token() -> str:
    if CSRF_SESSION_KEY not in session:
        session[CSRF_SESSION_KEY] = secrets.token_hex(32)
        session.modified = True
    return session[CSRF_SESSION_KEY]


def _auth_required() -> bool:
    return bool(_APP_PASS)


def _is_public(path: str) -> bool:
    return any(path.startswith(p) for p in _PUBLIC_PATHS)


def _check_session_timeout() -> bool:
    """Retorna True se sessão válida, False se expirada."""
    last = session.get("last_seen", 0)
    if time.time() - last > SESSION_TIMEOUT_S:
        session.clear()
        return False
    session["last_seen"] = int(time.time())
    return True


# ── Decorators ────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not _auth_required() or _is_public(request.path):
            return f(*args, **kwargs)
        if not session.get("authenticated"):
            if request.is_json:
                return jsonify({"error": "Não autenticado."}), 401
            return redirect(url_for("auth.login", next=request.path))
        if not _check_session_timeout():
            if request.is_json:
                return jsonify({"error": "Sessão expirada."}), 401
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    """Exige role admin ou master. Inclui verificação de sessão."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not _auth_required():
            return f(*args, **kwargs)
        if not session.get("authenticated"):
            if request.is_json:
                return jsonify({"error": "Não autenticado."}), 401
            return redirect(url_for("auth.login"))
        if not _check_session_timeout():
            if request.is_json:
                return jsonify({"error": "Sessão expirada."}), 401
            return redirect(url_for("auth.login"))
        if session.get("role") not in ("admin", "master"):
            if request.is_json:
                return jsonify({"error": "Acesso restrito a administradores."}), 403
            return render_template("403.html"), 403
        return f(*args, **kwargs)
    return wrapper


def csrf_protect(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            if not _auth_required() or _is_public(request.path):
                return f(*args, **kwargs)
            received = (request.headers.get(CSRF_HEADER) or
                        request.form.get("csrf_token", ""))
            expected = session.get(CSRF_SESSION_KEY, "")
            if not received or not expected or not hmac.compare_digest(received, expected):
                from web.security import audit
                audit("WARNING", "CSRF_INVALID",
                      f"path={request.path} ip={request.remote_addr}")
                if request.is_json:
                    return jsonify({"error": "Token de segurança inválido. Recarregue (F5)."}), 403
                return "Token de segurança inválido.", 403
        return f(*args, **kwargs)
    return wrapper


# ── Rotas de autenticação ─────────────────────────────────────────────────────

@bp.get("/login")
def login():
    if not _auth_required():
        return redirect("/email")
    if session.get("authenticated"):
        return redirect("/email")
    return render_template("login.html", error=None, no_password=not _APP_PASS)


@bp.post("/login")
def login_post():
    from web.security import audit

    username = (request.form.get("username") or "").strip()
    password = (request.form.get("password") or "")

    if not _APP_PASS:
        audit("ERROR", "LOGIN_NO_PASSWORD")
        return render_template("login.html",
                               error="Configure APP_PASSWORD no .env.",
                               no_password=True)

    # ── 1. Verifica master admin (.env) ───────────────────────────────────────
    is_master = (
        hmac.compare_digest(username.lower(), _APP_USER.lower()) and
        hmac.compare_digest(
            hashlib.sha256(password.encode()).hexdigest(),
            hashlib.sha256(_APP_PASS.encode()).hexdigest(),
        )
    )
    if is_master:
        session.clear()
        session.update({
            "authenticated": True,
            "user":          _APP_USER,
            "role":          "master",
            "user_id":       None,
            "last_seen":     int(time.time()),
        })
        session.permanent = True
        audit("INFO", "LOGIN_OK", f"user={username} role=master")
        nxt = request.args.get("next", "/email")
        if not nxt.startswith("/") or "//" in nxt:
            nxt = "/email"
        return redirect(nxt)

    # ── 2. Verifica usuários do banco ─────────────────────────────────────────
    from web.users_db import get_by_username, record_login, verify_password

    db_user = get_by_username(username)

    # Usuário não encontrado — mesma mensagem genérica para não vazar info
    if not db_user or not verify_password(db_user, password):
        audit("WARNING", "LOGIN_FAIL", f"user={username}")
        time.sleep(1)
        return render_template("login.html",
                               error="Usuário ou senha incorretos.",
                               no_password=False), 401

    status = db_user["status"]
    if status == "pending":
        audit("INFO", "LOGIN_PENDING", f"user={username}")
        return render_template("login.html",
                               error="Sua conta está aguardando aprovação do administrador.",
                               no_password=False), 403
    if status == "rejected":
        audit("WARNING", "LOGIN_REJECTED", f"user={username}")
        return render_template("login.html",
                               error="Sua solicitação não foi aprovada. Entre em contato com o administrador.",
                               no_password=False), 403
    if status != "approved":
        return render_template("login.html",
                               error="Conta inativa.",
                               no_password=False), 403

    # Login aprovado
    session.clear()
    session.update({
        "authenticated": True,
        "user":          db_user["username"],
        "role":          db_user["role"],
        "user_id":       db_user["id"],
        "last_seen":     int(time.time()),
    })
    session.permanent = True
    record_login(db_user["id"])
    audit("INFO", "LOGIN_OK", f"user={username} role={db_user['role']}")

    nxt = request.args.get("next", "/email")
    if not nxt.startswith("/") or "//" in nxt:
        nxt = "/email"
    return redirect(nxt)


@bp.get("/logout")
def logout():
    user = session.get("user", "anônimo")
    session.clear()
    from web.security import audit
    audit("INFO", "LOGOUT", f"user={user}")
    return redirect(url_for("auth.login"))


# ── E-mail transacional ───────────────────────────────────────────────────────

def _send_reset_email(to_email: str, reset_url: str) -> bool:
    host  = os.getenv("SMTP_HOST", "smtp.office365.com")
    port  = int(os.getenv("SMTP_PORT", "587"))
    user  = os.getenv("SMTP_USER", "")
    pwd   = os.getenv("SMTP_PASS", "")
    if not user or not pwd:
        _log.warning("SMTP não configurado — e-mail de reset não enviado.")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Redefinição de senha — Sigaway Analytics"
    msg["From"]    = user
    msg["To"]      = to_email

    html = f"""
    <div style="font-family:Inter,sans-serif;background:#0f1117;padding:32px;max-width:480px;margin:0 auto;border-radius:12px;">
      <div style="text-align:center;margin-bottom:24px;">
        <h2 style="color:#f1f5f9;font-size:18px;margin:0;">Sigaway Analytics</h2>
        <p style="color:#64748b;font-size:13px;margin:4px 0 0;">Redefinição de senha</p>
      </div>
      <div style="background:#1a1d27;border:1px solid #2a2d3a;border-radius:10px;padding:24px;">
        <p style="color:#94a3b8;font-size:14px;line-height:1.6;margin:0 0 20px;">
          Recebemos uma solicitação para redefinir a senha da sua conta.<br>
          Clique no botão abaixo para criar uma nova senha.
        </p>
        <div style="text-align:center;margin-bottom:20px;">
          <a href="{reset_url}" style="display:inline-block;background:#10b981;color:#fff;text-decoration:none;border-radius:8px;padding:12px 28px;font-size:14px;font-weight:600;">
            Redefinir senha
          </a>
        </div>
        <p style="color:#64748b;font-size:12px;margin:0;text-align:center;">
          Este link expira em <strong style="color:#94a3b8;">1 hora</strong>.<br>
          Se você não solicitou a redefinição, ignore este e-mail.
        </p>
      </div>
    </div>
    """
    msg.attach(MIMEText(html, "html"))

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=10) as s:
            s.ehlo()
            s.starttls(context=ctx)
            s.login(user, pwd)
            s.sendmail(user, to_email, msg.as_string())
        return True
    except Exception as exc:
        _log.error("Falha ao enviar e-mail de reset: %s", exc)
        return False


# ── Registro de novos usuários ────────────────────────────────────────────────

@bp.get("/register")
def register():
    if session.get("authenticated"):
        return redirect("/email")
    return render_template("register.html", error=None, success=False)


@bp.post("/register")
def register_post():
    from web.security import audit, rate_limit, sanitize_email, sanitize_str
    from web.users_db import create_user

    username = sanitize_str((request.form.get("username") or "").strip(), max_len=30)
    email    = sanitize_email((request.form.get("email") or "").strip())
    password = (request.form.get("password") or "")
    confirm  = (request.form.get("confirm") or "")

    def _err(msg):
        return render_template("register.html", error=msg, success=False), 400

    # Validações server-side
    if not username or len(username) < 3:
        return _err("Nome de usuário deve ter pelo menos 3 caracteres.")
    if not username.replace("_", "").replace(".", "").isalnum():
        return _err("Nome de usuário: use apenas letras, números, _ ou .")
    if username.lower() == _APP_USER.lower():
        return _err("Nome de usuário indisponível.")
    if not email:
        return _err("E-mail inválido.")
    if len(password) < 8:
        return _err("A senha deve ter pelo menos 8 caracteres.")
    if password != confirm:
        return _err("As senhas não coincidem.")

    result = create_user(username, email, password)
    if not result.get("ok"):
        return _err(result.get("error", "Erro ao criar conta."))

    audit("INFO", "REGISTER_REQUEST", f"user={username} email={email}")
    return render_template("register.html", error=None, success=True)


# ── Esqueceu a senha ──────────────────────────────────────────────────────────

@bp.get("/forgot-password")
def forgot_password():
    if session.get("authenticated"):
        return redirect("/email")
    return render_template("forgot_password.html", error=None, success=False)


@bp.post("/forgot-password")
def forgot_password_post():
    from web.security import audit, sanitize_email
    from web.users_db import get_all, set_reset_token

    email = sanitize_email((request.form.get("email") or "").strip())

    # Sempre mesma mensagem — não vaza se e-mail existe ou não
    _GENERIC_OK = render_template("forgot_password.html", error=None, success=True)

    if not email:
        return _GENERIC_OK

    # Busca apenas usuários aprovados com esse e-mail
    approved = [u for u in get_all("approved") if u["email"] == email.lower()]
    if not approved:
        audit("INFO", "PASSWORD_RESET_NOTFOUND", f"email={email}")
        return _GENERIC_OK

    user  = approved[0]
    token = secrets.token_urlsafe(32)
    expiry = (datetime.utcnow() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    set_reset_token(user["id"], token, expiry)

    base_url = request.host_url.rstrip("/")
    reset_url = f"{base_url}/reset-password/{token}"
    sent = _send_reset_email(user["email"], reset_url)
    audit("INFO", "PASSWORD_RESET_SENT", f"user={user['username']} sent={sent}")
    return _GENERIC_OK


@bp.get("/reset-password/<token>")
def reset_password(token: str):
    if session.get("authenticated"):
        return redirect("/email")
    from web.users_db import get_by_reset_token
    user = get_by_reset_token(token)
    if not user or not user.get("reset_expiry"):
        return render_template("reset_password.html", token=None, error="Link inválido ou expirado.", success=False)
    if datetime.utcnow() > datetime.strptime(user["reset_expiry"], "%Y-%m-%d %H:%M:%S"):
        return render_template("reset_password.html", token=None, error="Este link expirou. Solicite um novo.", success=False)
    return render_template("reset_password.html", token=token, error=None, success=False)


@bp.post("/reset-password/<token>")
def reset_password_post(token: str):
    from web.security import audit
    from web.users_db import clear_reset_token, get_by_reset_token, update_password

    user = get_by_reset_token(token)
    if not user or not user.get("reset_expiry"):
        return render_template("reset_password.html", token=None, error="Link inválido ou expirado.", success=False)
    if datetime.utcnow() > datetime.strptime(user["reset_expiry"], "%Y-%m-%d %H:%M:%S"):
        return render_template("reset_password.html", token=None, error="Este link expirou. Solicite um novo.", success=False)

    password = request.form.get("password", "")
    confirm  = request.form.get("confirm", "")

    if len(password) < 8:
        return render_template("reset_password.html", token=token, error="A senha deve ter pelo menos 8 caracteres.", success=False)
    if password != confirm:
        return render_template("reset_password.html", token=token, error="As senhas não coincidem.", success=False)

    update_password(user["id"], password)
    clear_reset_token(user["id"])
    audit("INFO", "PASSWORD_RESET_OK", f"user={user['username']}")
    return render_template("reset_password.html", token=None, error=None, success=True)


# ── Definição de senha por convite ────────────────────────────────────────────

@bp.get("/set-password/<token>")
def set_password(token: str):
    if session.get("authenticated"):
        return redirect("/email")
    from web.users_db import get_by_reset_token
    user = get_by_reset_token(token)
    if not user or not user.get("reset_expiry") or user.get("status") != "invited":
        return render_template("set_password.html", token=None, error="Convite inválido ou expirado.", success=False, username="")
    if datetime.utcnow() > datetime.strptime(user["reset_expiry"], "%Y-%m-%d %H:%M:%S"):
        return render_template("set_password.html", token=None, error="Este convite expirou. Solicite um novo ao administrador.", success=False, username="")
    return render_template("set_password.html", token=token, error=None, success=False, username=user["username"])


@bp.post("/set-password/<token>")
def set_password_post(token: str):
    from web.security import audit
    from web.users_db import approve_user, clear_reset_token, get_by_reset_token, update_password

    user = get_by_reset_token(token)
    if not user or not user.get("reset_expiry") or user.get("status") != "invited":
        return render_template("set_password.html", token=None, error="Convite inválido ou expirado.", success=False, username="")
    if datetime.utcnow() > datetime.strptime(user["reset_expiry"], "%Y-%m-%d %H:%M:%S"):
        return render_template("set_password.html", token=None, error="Este convite expirou. Solicite um novo ao administrador.", success=False, username="")

    password = request.form.get("password", "")
    confirm  = request.form.get("confirm", "")

    if len(password) < 8:
        return render_template("set_password.html", token=token, error="A senha deve ter pelo menos 8 caracteres.", success=False, username=user["username"])
    if password != confirm:
        return render_template("set_password.html", token=token, error="As senhas não coincidem.", success=False, username=user["username"])

    update_password(user["id"], password)
    approve_user(user["id"], "invite")
    clear_reset_token(user["id"])
    audit("INFO", "INVITE_SET_PASSWORD", f"user={user['username']}")
    return render_template("set_password.html", token=None, error=None, success=True, username=user["username"])


def send_invite_email(to_email: str, username: str, invite_url: str) -> bool:
    host = os.getenv("SMTP_HOST", "smtp.office365.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "")
    pwd  = os.getenv("SMTP_PASS", "")
    if not user or not pwd:
        _log.warning("SMTP não configurado — e-mail de convite não enviado.")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Convite — Sigaway Analytics"
    msg["From"]    = user
    msg["To"]      = to_email

    html = f"""
    <div style="font-family:Inter,sans-serif;background:#0f1117;padding:32px;max-width:480px;margin:0 auto;border-radius:12px;">
      <div style="text-align:center;margin-bottom:24px;">
        <h2 style="color:#f1f5f9;font-size:18px;margin:0;">Sigaway Analytics</h2>
        <p style="color:#64748b;font-size:13px;margin:4px 0 0;">Você foi convidado</p>
      </div>
      <div style="background:#1a1d27;border:1px solid #2a2d3a;border-radius:10px;padding:24px;">
        <p style="color:#94a3b8;font-size:14px;line-height:1.6;margin:0 0 8px;">
          Olá, <strong style="color:#f1f5f9;">{username}</strong>!
        </p>
        <p style="color:#94a3b8;font-size:14px;line-height:1.6;margin:0 0 20px;">
          Você foi convidado para acessar a plataforma Sigaway Analytics.<br>
          Clique no botão abaixo para definir sua senha e ativar o acesso.
        </p>
        <div style="text-align:center;margin-bottom:20px;">
          <a href="{invite_url}" style="display:inline-block;background:#10b981;color:#fff;text-decoration:none;border-radius:8px;padding:12px 28px;font-size:14px;font-weight:600;">
            Definir minha senha
          </a>
        </div>
        <p style="color:#64748b;font-size:12px;margin:0;text-align:center;">
          Este link expira em <strong style="color:#94a3b8;">7 dias</strong>.<br>
          Se você não esperava este convite, ignore este e-mail.
        </p>
      </div>
    </div>
    """
    msg.attach(MIMEText(html, "html"))

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=10) as s:
            s.ehlo()
            s.starttls(context=ctx)
            s.login(user, pwd)
            s.sendmail(user, to_email, msg.as_string())
        return True
    except Exception as exc:
        _log.error("Falha ao enviar e-mail de convite: %s", exc)
        return False
