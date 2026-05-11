"""
CNPJ.ws API — Enriquecimento gratuito, sem autenticação.
Endpoint: https://publica.cnpj.ws/cnpj/{cnpj_14_digitos}
Rate limit: ~3 req/min na versão pública.
"""
import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://publica.cnpj.ws/cnpj"


def enrich(cnpj: str, retry: int = 3) -> Optional[dict]:
    """Busca dados completos de um CNPJ. Retorna None se não encontrado."""
    cnpj_clean = "".join(filter(str.isdigit, str(cnpj)))
    if len(cnpj_clean) != 14:
        logger.debug(f"CNPJ inválido (não tem 14 dígitos): {cnpj}")
        return None

    url = f"{BASE_URL}/{cnpj_clean}"

    for attempt in range(retry):
        try:
            resp = requests.get(url, timeout=15)

            if resp.status_code == 429:
                wait = 60 * (attempt + 1)
                logger.warning(f"Rate limit CNPJ.ws — aguardando {wait}s...")
                time.sleep(wait)
                continue

            if resp.status_code == 404:
                return None

            resp.raise_for_status()
            return resp.json()

        except requests.RequestException as e:
            if attempt < retry - 1:
                time.sleep(5)
            else:
                logger.error(f"Erro CNPJ.ws {cnpj_clean}: {e}")

    return None


def normalize(raw: dict) -> dict:
    """
    Transforma a resposta bruta do CNPJ.ws no schema padronizado de lead.
    Todos os campos são strings; nunca None.
    """
    estab  = raw.get("estabelecimento") or {}
    socios = raw.get("socios") or []
    porte  = raw.get("porte") or {}
    estado = estab.get("estado") or {}
    municipio = estab.get("municipio") or {}

    ddd1 = _s(estab.get("ddd1"))
    tel1 = _s(estab.get("telefone1"))
    telefone = f"({ddd1}) {tel1}" if ddd1 and tel1 else tel1

    # Descrição do CNAE principal
    ativ_principal = estab.get("atividade_principal") or {}
    cnae_desc = _s(ativ_principal.get("descricao"))
    cnae_code = _s(ativ_principal.get("id") or raw.get("cnae_fiscal"))

    return {
        "razao_social":    _s(raw.get("razao_social")),
        "nome_fantasia":   _s(estab.get("nome_fantasia") or raw.get("nome_fantasia")),
        "cnpj":            _s(raw.get("cnpj") or estab.get("cnpj")),
        "email":           _s(estab.get("email")).lower(),
        "telefone":        telefone,
        "municipio":       _s(municipio.get("descricao") or municipio.get("nome")),
        "uf":              _s(estado.get("sigla")),
        "cep":             _s(estab.get("cep")),
        "logradouro":      _s(estab.get("logradouro")),
        "numero":          _s(estab.get("numero")),
        "bairro":          _s(estab.get("bairro")),
        "cnae_principal":  cnae_code,
        "cnae_descricao":  cnae_desc,
        "situacao":        _s(estab.get("situacao_cadastral")),
        "porte":           _s(porte.get("descricao")),
        "capital_social":  _s(raw.get("capital_social")),
        "data_inicio":     _s(estab.get("data_inicio_atividade")),
        "socio_principal": _s(socios[0].get("nome") if socios else ""),
        "website":         "",
        "fonte":           "Brasil.io + CNPJ.ws",
    }


def _s(val) -> str:
    """Converte qualquer valor para string limpa, nunca None."""
    if val is None:
        return ""
    s = str(val).strip()
    return "" if s in ("nan", "None", "null") else s
