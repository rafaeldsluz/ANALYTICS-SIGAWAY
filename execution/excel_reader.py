"""
Camada de Execução — Leitura do Excel de destinatários.
Espera encontrar as colunas REPRESENTANTE, CLIENTE e EMAIL na planilha.
"""

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_EXCEL = Path(__file__).parent.parent / "AÇÃO E-MKT.xlsx"


_HEADER_ANCHORS = {
    "REPRESENTANTE", "CLIENTE", "EMPRESA", "NOME",
    "TELEFONE", "CELULAR", "PHONE", "PHONE_NUMBER",
    "WHATSAPP", "EMAIL", "COUNTRY_CODE", "SAVED_NAME",
}


def _find_header_row(df: pd.DataFrame) -> int:
    """
    Localiza a linha que contém o cabeçalho da planilha.
    Aceita qualquer coluna reconhecível como âncora (flexível para múltiplos formatos).
    Retorna 0 (primeira linha) como fallback seguro.
    """
    for idx, row in df.iterrows():
        values_upper = {str(v).strip().upper() for v in row.values}
        if values_upper & _HEADER_ANCHORS:
            return idx
    return 0


def load_recipients(excel_path: str | None = None) -> list[dict]:
    """
    Carrega a lista de destinatários do Excel.

    Colunas esperadas (insensível a maiúsculas):
      - REPRESENTANTE
      - CLIENTE
      - EMAIL  (obrigatório para envio; linhas sem e-mail são ignoradas com aviso)

    Retorna lista de dicts:
      {representante, cliente, email, status}
    """
    path = Path(excel_path) if excel_path else DEFAULT_EXCEL

    try:
        raw = pd.read_excel(path, header=None, engine="openpyxl")
    except PermissionError:
        raise PermissionError(
            f"O arquivo '{path.name}' está aberto em outro programa. "
            "Feche-o no Excel e tente novamente."
        )
    except FileNotFoundError:
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")

    header_row = _find_header_row(raw)
    df = pd.read_excel(path, header=header_row, engine="openpyxl")
    df = df.dropna(how="all")

    # Normaliza nomes de colunas para uppercase sem espaços extras
    df.columns = [str(c).strip().upper() for c in df.columns]

    # Mapeia nomes de colunas com tolerância a variações.
    # Colunas de CC (representante, vendedor) são acumuladas em lista para suportar múltiplos CCs.
    col_map: dict[str, str] = {}
    cc_cols: list[str] = []

    for col in df.columns:
        col_up = col.upper()
        is_email_col = "EMAIL" in col_up or "E-MAIL" in col_up
        if is_email_col and ("REPRESENTANTE" in col_up or "VENDEDOR" in col_up):
            cc_cols.append(col)
        elif is_email_col:
            # EMAIL CLIENTE, EMAIL, E-MAIL — checado antes de CLIENTE/EMPRESA
            if "email" not in col_map:
                col_map["email"] = col
        elif "REPRESENTANTE" in col_up:
            if "representante" not in col_map:
                col_map["representante"] = col
        elif "CLIENTE" in col_up or "EMPRESA" in col_up:
            if "cliente" not in col_map:
                col_map["cliente"] = col
        elif "STATUS" in col_up:
            col_map["status"] = col

    if "email" not in col_map:
        logger.warning(
            "Coluna EMAIL não encontrada no Excel. "
            "Adicione uma coluna com cabeçalho EMAIL para habilitar o envio."
        )
    if not cc_cols:
        logger.warning(
            "Colunas de CC (REPRESENTANTE/VENDEDOR) não encontradas. "
            "O CC dos e-mails usará o valor global configurado na interface."
        )

    def _clean(val) -> str:
        s = str(val).strip()
        return "" if s in ("nan", "None", "") else s

    recipients: list[dict] = []
    for _, row in df.iterrows():
        rep    = _clean(row.get(col_map.get("representante", ""), ""))
        cli    = _clean(row.get(col_map.get("cliente", ""), ""))
        email  = _clean(row.get(col_map.get("email", ""), "")) if "email" in col_map else ""
        status = _clean(row.get(col_map.get("status", ""), "")) if "status" in col_map else ""

        # Coleta todos os e-mails de CC, ignorando vazios
        cc_list = [_clean(row.get(c, "")) for c in cc_cols]
        cc_list = [e for e in cc_list if e]

        if not rep or rep.upper() in ("REPRESENTANTE", "NAN", "NONE"):
            continue

        recipients.append(
            {
                "representante": rep,
                "cliente":       cli,
                "email":         email,
                "cc_list":       cc_list,
                "status":        status,
            }
        )

    logger.info(f"{len(recipients)} destinatários carregados de '{path.name}'.")
    return recipients


def load_whatsapp_contacts(excel_path: str | None = None) -> list[dict]:
    """
    Carrega contatos para disparo WhatsApp.

    Colunas esperadas (insensível a maiúsculas):
      - NOME / CLIENTE / EMPRESA  → nome de exibição
      - TELEFONE / CELULAR / WHATSAPP / PHONE / FONE → número

    Retorna lista de dicts: {nome, phone}
    """
    path = Path(excel_path) if excel_path else DEFAULT_EXCEL

    try:
        raw = pd.read_excel(path, header=None, engine="openpyxl")
    except PermissionError:
        raise PermissionError(
            f"O arquivo '{path.name}' está aberto em outro programa. "
            "Feche-o no Excel e tente novamente."
        )
    except FileNotFoundError:
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")

    header_row = _find_header_row(raw)
    df = pd.read_excel(path, header=header_row, engine="openpyxl")
    df = df.dropna(how="all")
    df.columns = [str(c).strip().upper() for c in df.columns]

    _PHONE_KEYWORDS   = (
        "PHONE_NUMBER", "TELEFONE", "CELULAR", "WHATSAPP",
        "PHONE", "FONE", "CONTATO", "FORMATTED_PHONE",
    )
    _EMPRESA_KEYWORDS = ("EMPRESA", "CLIENTE", "COMPANY", "RAZAO")
    _NAME_KEYWORDS    = ("SAVED_NAME", "PUBLIC_NAME", "NOME", "REPRESENTANTE")

    phone_col:   str | None = None
    empresa_col: str | None = None
    name_col:    str | None = None
    for col in df.columns:
        if phone_col is None and any(k in col for k in _PHONE_KEYWORDS):
            phone_col = col
        if empresa_col is None and any(k in col for k in _EMPRESA_KEYWORDS):
            empresa_col = col
        if name_col is None and any(k in col for k in _NAME_KEYWORDS):
            name_col = col

    if phone_col is None:
        raise ValueError(
            "Coluna de telefone não encontrada. "
            "Use um cabeçalho como TELEFONE, CELULAR ou WHATSAPP."
        )

    def _clean(val) -> str:
        s = str(val).strip()
        return "" if s in ("nan", "None", "") else s

    contacts: list[dict] = []
    for _, row in df.iterrows():
        phone   = _clean(row.get(phone_col, ""))
        nome    = _clean(row.get(name_col, ""))    if name_col    else ""
        empresa = _clean(row.get(empresa_col, "")) if empresa_col else ""
        if not phone:
            continue
        contacts.append({"nome": nome, "phone": phone, "empresa": empresa})

    logger.info(f"{len(contacts)} contatos WhatsApp carregados de '{path.name}'.")
    return contacts
