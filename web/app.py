"""
Flask app factory — Sigaway Agent Web.
"""
import os
import sys
from pathlib import Path

from flask import Flask

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.secret_key = os.getenv("FLASK_SECRET", "sigaway-change-in-production-2025")

    # Registra blueprints
    from web.routes.dashboard       import bp as dash_bp
    from web.routes.email_routes    import bp as email_bp
    from web.routes.leads_routes    import bp as leads_bp
    from web.routes.whatsapp_routes import bp as wz_bp
    from web.routes.sdr_routes      import bp as sdr_bp

    app.register_blueprint(dash_bp)
    app.register_blueprint(email_bp,    url_prefix="/email")
    app.register_blueprint(leads_bp,    url_prefix="/leads")
    app.register_blueprint(wz_bp,       url_prefix="/whatsapp")
    app.register_blueprint(sdr_bp,      url_prefix="/sdr")

    # Inicializa banco SDR
    from sdr.db import init_db
    init_db()

    return app
