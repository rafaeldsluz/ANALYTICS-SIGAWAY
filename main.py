"""
Ponto de entrada do Sigaway Agent.
Carrega variáveis de ambiente e abre a interface gráfica.
"""

import sys
from pathlib import Path

# Garante que o diretório raiz esteja no path antes de qualquer import local
ROOT = Path(__file__).parent.resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from ui.app import SigawayAgentApp
from sdr.server import start_server_thread

if __name__ == "__main__":
    start_server_thread()
    app = SigawayAgentApp()
    app.mainloop()
