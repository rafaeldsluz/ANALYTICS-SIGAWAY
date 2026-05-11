"""
Ponto de entrada da versão web — Sigaway Agent Platform.
Desenvolvimento: python web_main.py
Produção:        gunicorn -w 2 -b 0.0.0.0:5000 --timeout 300 web_main:app
"""
import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

from web.app import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("WEB_PORT", 5000))
    print(f"\n  Sigaway Agent Web rodando em http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
