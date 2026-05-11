"""
Brasil.io API — Busca de empresas por CNAE (gratuito com cadastro).
Token gratuito em: https://brasil.io/auth/tokens-api/

Endpoint: /api/dataset/cnpj/estabelecimentos/data/
Filtros:  cnae_fiscal_principal, uf, municipio, situacao_cadastral=02 (ativa)
"""
import logging
import time
from typing import Callable, Optional

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://brasil.io/api/dataset/cnpj/estabelecimentos/data/"


def search_by_cnae(
    cnae: str,
    token: str,
    uf: str = "",
    municipio: str = "",
    max_results: int = 500,
    on_progress: Optional[Callable[[int, int], None]] = None,
    stop_event=None,
) -> list[dict]:
    """
    Busca empresas ativas filtrando por CNAE principal.

    Retorna lista de dicts com campos do estabelecimento (sem razao_social —
    esse campo vem do enriquecimento via CNPJ.ws).
    """
    headers = {"Authorization": f"Token {token}"}
    params: dict = {
        "cnae_fiscal_principal": cnae,
        "situacao_cadastral": "02",  # 02 = ATIVA
    }
    if uf:
        params["uf"] = uf.upper()
    if municipio:
        params["municipio"] = municipio.upper()

    results: list[dict] = []
    url: Optional[str] = BASE_URL
    page = 1

    while url and len(results) < max_results:
        if stop_event and stop_event.is_set():
            break
        try:
            resp = requests.get(
                url,
                headers=headers,
                params=params if page == 1 else {},
                timeout=30,
            )

            if resp.status_code == 401:
                raise ValueError(
                    "Token Brasil.io inválido. "
                    "Obtenha o token gratuito em: brasil.io/auth/tokens-api/"
                )
            if resp.status_code == 429:
                logger.warning("Rate limit Brasil.io — aguardando 30s...")
                time.sleep(30)
                continue

            resp.raise_for_status()
            data = resp.json()

            batch = data.get("results", [])
            results.extend(batch)

            total_est = data.get("count", 0)
            if on_progress:
                on_progress(len(results), total_est)

            url = data.get("next")
            page += 1
            time.sleep(0.4)  # respeita rate limit

        except ValueError:
            raise
        except requests.RequestException as e:
            logger.error(f"Erro Brasil.io CNAE {cnae}: {e}")
            break

    return results[:max_results]
