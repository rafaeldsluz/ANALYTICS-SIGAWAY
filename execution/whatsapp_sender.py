"""
Integração com a Evolution API para envio de mensagens WhatsApp.
Implementa retentativas automáticas para erros transitórios.
"""
import logging
import re
import time

import urllib3
import requests

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_DELAYS = (15, 30, 60)
_STRIP_NON_DIGITS = re.compile(r"\D")


def _normalize_phone(phone: str) -> str:
    digits = _STRIP_NON_DIGITS.sub("", str(phone).strip())
    if len(digits) < 10:
        raise ValueError(f"Número inválido (mínimo 10 dígitos): '{phone}'")
    if not digits.startswith("55") and len(digits) <= 11:
        digits = "55" + digits
    return digits


def send_whatsapp(
    base_url: str,
    api_key: str,
    instance: str,
    phone: str,
    message: str,
) -> None:
    """
    Envia mensagem de texto via Evolution API.
    Retentativas automáticas para 429, 5xx e timeouts.
    Levanta RuntimeError se todas as tentativas falharem.
    """
    number = _normalize_phone(phone)
    url = f"{base_url.rstrip('/')}/message/sendText/{instance}"
    headers = {"apikey": api_key, "Content-Type": "application/json"}
    payload = {"number": number, "text": message}

    last_err: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        logger.info(f"  [WZ] Tentativa {attempt}/{_MAX_RETRIES} → {number}")
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=20, verify=False)
            if resp.status_code in (200, 201):
                logger.info(f"  [WZ] Enviado com sucesso → {number}")
                return
            body = resp.text[:300]
            is_connection_closed = (
                resp.status_code == 400 and "Connection Closed" in body
            )
            if resp.status_code == 429 or resp.status_code >= 500 or is_connection_closed:
                wait = _RETRY_DELAYS[min(attempt - 1, len(_RETRY_DELAYS) - 1)]
                last_err = RuntimeError(f"HTTP {resp.status_code}: {body}")
                logger.warning(f"  [WZ] Erro {resp.status_code} (instância desconectada?). Retentando em {wait}s...")
                time.sleep(wait)
                continue
            raise RuntimeError(
                f"Evolution API: HTTP {resp.status_code} — {body}"
            )
        except requests.exceptions.Timeout:
            wait = _RETRY_DELAYS[min(attempt - 1, len(_RETRY_DELAYS) - 1)]
            last_err = RuntimeError(f"Timeout (tentativa {attempt})")
            logger.warning(f"  [WZ] Timeout. Retentando em {wait}s...")
            time.sleep(wait)
        except requests.exceptions.ConnectionError as e:
            wait = _RETRY_DELAYS[min(attempt - 1, len(_RETRY_DELAYS) - 1)]
            last_err = RuntimeError(f"Conexão recusada: {e}")
            logger.warning(f"  [WZ] Falha de conexão. Retentando em {wait}s...")
            time.sleep(wait)

    raise RuntimeError(
        f"Falha após {_MAX_RETRIES} tentativas para '{phone}'. "
        f"Último erro: {last_err}"
    ) from last_err


def check_instance(base_url: str, api_key: str, instance: str) -> str:
    """
    Consulta o estado de conexão da instância na Evolution API.
    Retorna string de estado ('open', 'close', etc.).
    """
    url = f"{base_url.rstrip('/')}/instance/connectionState/{instance}"
    resp = requests.get(url, headers={"apikey": api_key}, timeout=10, verify=False)
    if not resp.ok:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    state = (
        data.get("instance", {}).get("state")
        or data.get("state")
        or data.get("status")
        or "desconhecido"
    )
    return str(state).lower()
