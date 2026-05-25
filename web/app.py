"""
Flask app factory — Sigaway Agent Web.
"""
import logging
import os
import secrets
import sys
from datetime import timedelta
from pathlib import Path

from flask import Flask

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
_log = logging.getLogger("sigaway.app")


def _require_secret_key() -> str:
    key = os.getenv("FLASK_SECRET")
    if key:
        return key
    # Aviso claro se usando chave gerada em runtime (não persiste entre reinicializações)
    generated = secrets.token_hex(32)
    _log.warning(
        "AVISO DE SEGURANÇA: FLASK_SECRET não configurado no .env. "
        "Sessões serão invalidadas a cada reinicialização. "
        "Adicione ao .env:  FLASK_SECRET=%s",
        generated,
    )
    return generated


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    app.secret_key = _require_secret_key()
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"]   = os.getenv("HTTPS_ONLY", "0") == "1"
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)
    app.config["MAX_CONTENT_LENGTH"]    = 10 * 1024 * 1024  # 10 MB
    app.config["TEMPLATES_AUTO_RELOAD"] = True

    # Aviso se APP_PASSWORD não configurado
    if not os.getenv("APP_PASSWORD"):
        _log.warning(
            "AVISO DE SEGURANÇA: APP_PASSWORD não configurado. "
            "A aplicação está ABERTA sem autenticação. "
            "Adicione APP_PASSWORD=<senha> ao .env para exigir login."
        )

    # ── Segurança (headers, rate limiter, audit log) ──────────────────────────
    from web.security import init_security
    init_security(app)

    # ── Blueprints ────────────────────────────────────────────────────────────
    from web.auth                        import bp as auth_bp
    from web.routes.dashboard            import bp as dash_bp
    from web.routes.email_routes         import bp as email_bp
    from web.routes.leads_routes         import bp as leads_bp
    from web.routes.whatsapp_routes      import bp as wz_bp
    from web.routes.sdr_routes           import bp as sdr_bp
    from web.routes.security_routes      import bp as sec_bp
    from web.routes.admin_routes         import bp as admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dash_bp)
    app.register_blueprint(email_bp,    url_prefix="/email")
    app.register_blueprint(leads_bp,    url_prefix="/leads")
    app.register_blueprint(wz_bp,       url_prefix="/whatsapp")
    app.register_blueprint(sdr_bp,      url_prefix="/sdr")
    app.register_blueprint(sec_bp,      url_prefix="/security")
    app.register_blueprint(admin_bp,    url_prefix="/admin")

    # Expõe get_csrf_token como função de template global
    from web.auth import get_csrf_token
    app.jinja_env.globals["get_csrf_token"] = get_csrf_token

    # Inicializa bancos
    from sdr.db import init_db
    from web.users_db import init_db as init_users_db
    init_db()
    init_users_db()

    _log.info("Sigaway Agent Web iniciado.")
    return app
