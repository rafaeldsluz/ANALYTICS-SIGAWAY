"""
Camada de Execução — Envio de e-mail.
Suporta dois backends:
  1. Microsoft Graph API (preferido) — não requer Outlook aberto
  2. Outlook desktop via win32com (fallback)
"""

import base64
import logging
import re
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_MAX_RETRIES = 3    # tentativas de envio antes de desistir
_RETRY_DELAY = 5    # segundos entre tentativas

_IMG_CID = "torre_screenshot@sigaway"
_PR_CONTENT_ID = "http://schemas.microsoft.com/mapi/proptag/0x3712001F"

# Regex para localizar a tag <body ...> de abertura no HTML do Outlook
_BODY_TAG_RE = re.compile(r"(<body[^>]*>)", re.IGNORECASE)


# ── Microsoft Graph API ───────────────────────────────────────────────────────

def _graph_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    """Obtém access token via client credentials flow."""
    import requests
    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    resp = requests.post(url, data={
        "grant_type":    "client_credentials",
        "client_id":     client_id,
        "client_secret": client_secret,
        "scope":         "https://graph.microsoft.com/.default",
    }, timeout=20)
    if not resp.ok:
        err = resp.json().get("error_description", resp.text)
        if "AADSTS700016" in err:
            raise RuntimeError("Client ID inválido ou app não encontrado no tenant.")
        if "AADSTS7000215" in err:
            raise RuntimeError("Client Secret inválido ou expirado.")
        if "AADSTS90002" in err:
            raise RuntimeError("Tenant ID inválido.")
        raise RuntimeError(f"Falha na autenticação Graph: {err}")
    return resp.json()["access_token"]


def test_graph_connection(
    tenant_id: str, client_id: str, client_secret: str, sender_email: str
) -> str:
    """
    Verifica credenciais Graph API e acesso à caixa do remetente.
    Retorna o DisplayName do remetente em caso de sucesso.
    """
    try:
        import requests
    except ImportError:
        raise ImportError("Execute: pip install requests")

    logger.info("[Graph] Obtendo token de autenticação...")
    token = _graph_token(tenant_id, client_id, client_secret)
    logger.info("[Graph] Token obtido. Verificando acesso à caixa do remetente...")

    resp = requests.get(
        f"https://graph.microsoft.com/v1.0/users/{sender_email}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    if not resp.ok:
        raise RuntimeError(
            f"Token válido, mas sem acesso à caixa '{sender_email}' (HTTP {resp.status_code}). "
            "Verifique se a permissão Mail.Send foi concedida (admin consent)."
        )
    display_name = resp.json().get("displayName", sender_email)
    logger.info(f"[Graph] Pronto — remetente: {display_name} ({sender_email})")
    return display_name


def send_via_graph(
    tenant_id: str,
    client_id: str,
    client_secret: str,
    sender_email: str,
    to_email: str,
    subject: str,
    cliente: str,
    custom_text: str = "",
    attachment_path: str | None = None,
    cc_email: str = "",
    inline_image: bool = True,
) -> None:
    """Envia e-mail via Microsoft Graph API (não requer Outlook aberto)."""
    try:
        import requests
    except ImportError:
        raise ImportError("Execute: pip install requests")

    _validate_email(to_email)

    att_resolved = None
    if attachment_path:
        att_resolved = Path(attachment_path).resolve()
        if not att_resolved.exists():
            raise FileNotFoundError(f"Screenshot não encontrado: {att_resolved}")

    logger.info(f"  [Graph] Tentativa de envio → {to_email}")
    logger.debug("  [Graph] Obtendo token...")
    token = _graph_token(tenant_id, client_id, client_secret)

    body_html = build_email_body(
        cliente=cliente,
        custom_text=custom_text,
        inline_image=inline_image and att_resolved is not None,
    )

    attachments = []
    if att_resolved:
        logger.debug(f"  [Graph] Codificando imagem inline: {att_resolved.name}")
        attachments.append({
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name":         att_resolved.name,
            "contentType":  "image/png",
            "contentBytes": base64.b64encode(att_resolved.read_bytes()).decode(),
            "isInline":     True,
            "contentId":    _IMG_CID,
        })

    message: dict = {
        "subject": subject,
        "body":    {"contentType": "HTML", "content": body_html},
        "toRecipients": [{"emailAddress": {"address": to_email}}],
    }
    if cc_email:
        _validate_email(cc_email)
        message["ccRecipients"] = [{"emailAddress": {"address": cc_email}}]
        logger.debug(f"  [Graph] CC: {cc_email}")
    if attachments:
        message["attachments"] = attachments

    logger.info(f"  [Graph] Enviando e-mail...")
    resp = requests.post(
        f"https://graph.microsoft.com/v1.0/users/{sender_email}/sendMail",
        json={"message": message, "saveToSentItems": True},
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
        },
        timeout=30,
    )
    if not resp.ok:
        raise RuntimeError(f"Graph API erro {resp.status_code}: {resp.text}")

    logger.info(f"Enviado → {to_email} (Graph API)")


# ── Outlook COM (fallback) ────────────────────────────────────────────────────

def _connect_outlook_instance():
    """
    Tenta conectar ao Outlook via COM. Retorna o objeto Application.
    Lança RuntimeError com diagnóstico específico em caso de falha.
    """
    import win32com.client

    # Tenta a instância já aberta primeiro
    try:
        outlook = win32com.client.GetActiveObject("Outlook.Application")
        logger.debug("  [Outlook] Instância ativa encontrada via GetActiveObject.")
        return outlook
    except Exception as e_active:
        logger.debug(f"  [Outlook] GetActiveObject falhou: {e_active}")

    # Tenta iniciar/registrar nova instância
    try:
        outlook = win32com.client.Dispatch("Outlook.Application")
        logger.debug("  [Outlook] Nova instância iniciada via Dispatch.")
        return outlook
    except Exception as e_dispatch:
        err_str = str(e_dispatch).lower()
        if "permission" in err_str or "access" in err_str or "denied" in err_str:
            raise RuntimeError(
                f"Permissão negada ao conectar ao Outlook: {e_dispatch}. "
                "Verifique as políticas de segurança do Windows e as configurações de DCOM."
            ) from e_dispatch
        if "not registered" in err_str or "clsid" in err_str or "progid" in err_str:
            raise RuntimeError(
                f"Outlook não está registrado como servidor COM: {e_dispatch}. "
                "Verifique se o Microsoft Office está instalado corretamente."
            ) from e_dispatch
        if "busy" in err_str or "rpc" in err_str:
            raise RuntimeError(
                f"Outlook está ocupado ou não responde: {e_dispatch}. "
                "Aguarde o Outlook terminar a operação atual e tente novamente."
            ) from e_dispatch
        raise RuntimeError(
            f"Não foi possível conectar ao Outlook: {e_dispatch}. "
            "Certifique-se de que o Outlook está instalado e aberto."
        ) from e_dispatch


def test_outlook_connection() -> str:
    """
    Verifica se o Outlook está aberto e acessível via COM.
    Inicializa o COM no modelo STA (obrigatório para Outlook em threads Python).
    Retorna nome da conta configurada como padrão.
    """
    try:
        import win32com.client
        import pythoncom
    except ImportError:
        raise ImportError("Execute: pip install pywin32")

    logger.info("[Outlook] Iniciando verificação de conexão...")
    pythoncom.CoInitialize()
    try:
        outlook = _connect_outlook_instance()

        # Tenta obter o nome da conta padrão para confirmar sessão ativa
        account_name = "desconhecida"
        try:
            account_name = outlook.Session.CurrentUser.Name
            logger.info(f"[Outlook] Sessão ativa — conta: {account_name}")
        except Exception:
            logger.debug("[Outlook] Não foi possível obter nome da conta — sem bloqueio.")

        # Cria e descarta item para confirmar permissão de criação
        mail = outlook.CreateItem(0)
        mail.Subject = "__test__"
        mail.Close(0)  # olDiscard
        logger.info("[Outlook] Criação de item de e-mail testada com sucesso.")
        return account_name
    except RuntimeError:
        raise
    except Exception as e:
        msg = str(e) or type(e).__name__
        raise RuntimeError(
            f"Não foi possível conectar ao Outlook: {msg}. "
            "Abra o Outlook antes de usar o agente."
        ) from e
    finally:
        pythoncom.CoUninitialize()


def _validate_email(email: str) -> None:
    if not email or not _EMAIL_RE.match(email):
        raise ValueError(f"Endereço de e-mail inválido: '{email}'")


def _inject_before_body(outlook_html: str, fragment: str) -> str:
    """
    Insere `fragment` imediatamente após a tag <body ...> do HTML do Outlook.
    Se não encontrar a tag, prepende o fragmento antes do HTML completo.
    """
    m = _BODY_TAG_RE.search(outlook_html)
    if m:
        pos = m.end()
        return outlook_html[:pos] + fragment + outlook_html[pos:]
    return fragment + outlook_html


def send_via_outlook(
    to_email: str,
    subject: str,
    cliente: str,
    custom_text: str = "",
    attachment_path: str | None = None,
    cc_email: str = "",
    inline_image: bool = True,
) -> None:
    """
    Cria e envia e-mail via Outlook desktop (COM).

    Lógica de composição do corpo:
      - Captura HTMLBody gerado pelo Outlook (contém assinatura padrão do Rafael)
      - Injeta nosso fragmento (copy + screenshot + assinatura Jhefferson) no início do <body>
      - A assinatura padrão permanece intacta no rodapé
    """
    try:
        import win32com.client
        import pythoncom
    except ImportError:
        raise ImportError("Execute: pip install pywin32")

    _validate_email(to_email)

    att_resolved = None
    if attachment_path:
        att_resolved = Path(attachment_path).resolve()
        if not att_resolved.exists():
            raise FileNotFoundError(f"Screenshot não encontrado: {att_resolved}")

    # CoInitialize garante modelo STA no thread — obrigatório para Outlook COM
    pythoncom.CoInitialize()
    try:
        return _send_com(
            to_email, subject, cliente, custom_text,
            att_resolved, cc_email, inline_image,
        )
    finally:
        pythoncom.CoUninitialize()


def _send_com(
    to_email: str,
    subject: str,
    cliente: str,
    custom_text: str,
    att_resolved,
    cc_email: str,
    inline_image: bool,
) -> None:
    last_error: Exception | None = None

    for attempt in range(1, _MAX_RETRIES + 1):
        logger.info(f"  [E-mail] Tentativa {attempt}/{_MAX_RETRIES} → {to_email}")
        try:
            outlook = _connect_outlook_instance()

            logger.debug("  [E-mail] Criando item olMailItem...")
            mail = outlook.CreateItem(0)

            # Captura assinatura padrão inserida automaticamente pelo Outlook
            default_signature_html = mail.HTMLBody or ""

            mail.To = to_email
            if cc_email:
                _validate_email(cc_email)
                mail.CC = cc_email
                logger.debug(f"  [E-mail] CC definido: {cc_email}")
            mail.Subject = subject
            logger.debug(f"  [E-mail] Assunto: {subject}")

            content_fragment = build_email_body(
                cliente=cliente,
                custom_text=custom_text,
                inline_image=inline_image and att_resolved is not None,
            )
            final_html = _inject_before_body(default_signature_html, content_fragment)
            mail.HTMLBody = final_html

            if att_resolved:
                logger.debug(f"  [E-mail] Adicionando anexo inline: {att_resolved.name}")
                att = mail.Attachments.Add(str(att_resolved))
                att.PropertyAccessor.SetProperty(_PR_CONTENT_ID, _IMG_CID)

            logger.info(f"  [E-mail] Chamando mail.Send()...")
            mail.Send()
            logger.info(f"  [E-mail] mail.Send() concluído — e-mail na fila de saída.")

            # Solicita sincronização imediata do Outbox
            try:
                outlook.Session.SendAndReceive(False)
                logger.debug("  [E-mail] SendAndReceive() chamado — Outbox sincronizado.")
            except Exception as e_sync:
                logger.warning(f"  [E-mail] SendAndReceive() falhou (não crítico): {e_sync}")

            logger.info(f"Enviado → {to_email}")
            return  # Sucesso — encerra o loop de retry

        except Exception as e:
            last_error = e
            logger.error(f"  [E-mail] Tentativa {attempt} falhou: {e}")
            if attempt < _MAX_RETRIES:
                logger.info(f"  [E-mail] Aguardando {_RETRY_DELAY}s antes da próxima tentativa...")
                time.sleep(_RETRY_DELAY)

    raise RuntimeError(
        f"E-mail para '{to_email}' não pôde ser enviado após {_MAX_RETRIES} tentativa(s). "
        f"Último erro: {last_error}"
    ) from last_error


_SHOT_MARKER = "[SCREENSHOT]"


def build_email_body(
    cliente: str,
    custom_text: str = "",
    inline_image: bool = True,
) -> str:
    """
    Retorna fragmento HTML do corpo do e-mail.
    Use [SCREENSHOT] no texto para posicionar a imagem inline exatamente ali.
    Se não houver marcador e inline_image=True, a imagem vai ao final.
    """
    img_block = ""
    if inline_image:
        img_block = (
            f'<div style="margin:20px 0 24px 0;border:1px solid #e2e8f0;'
            f'border-radius:8px;overflow:hidden;'
            f'box-shadow:0 4px 16px rgba(0,0,0,.08);">'
            f'<img src="cid:{_IMG_CID}" width="600" '
            f'style="display:block;width:100%;max-width:600px;height:auto;" '
            f'alt="Torre de Controle — {cliente}" />'
            f'</div>\n'
            f'<p style="margin:0 0 24px 0;font-size:11px;color:#94a3b8;'
            f'font-family:Arial,sans-serif;text-align:center;">'
            f'Torre de Controle — {cliente}</p>\n'
        )

    paragraphs = ""
    shot_inserted = False
    for line in (custom_text or "").split("\n"):
        line = line.strip()
        if not line:
            continue
        if line == _SHOT_MARKER:
            paragraphs += img_block
            shot_inserted = True
            continue
        is_bullet = line.startswith("•")
        margin = "0 0 5px 0" if is_bullet else "0 0 14px 0"
        padding = "padding-left:18px;" if is_bullet else ""
        paragraphs += (
            f'<p style="margin:{margin};{padding}font-size:15px;line-height:1.75;'
            f'color:#1a1a1a;font-family:Arial,Helvetica,sans-serif;">'
            f"{line}</p>\n"
        )

    if not paragraphs and not shot_inserted:
        paragraphs = (
            '<p style="margin:0 0 14px 0;font-size:15px;line-height:1.75;'
            'color:#1a1a1a;font-family:Arial,Helvetica,sans-serif;">'
            "Prezado(a), identificamos veículos na sua frota com performance reduzida. "
            "Segue abaixo o relatório da Torre de Controle.</p>\n"
        )

    # Marcador não usado → screenshot vai ao final
    if inline_image and not shot_inserted:
        paragraphs += img_block

    # Wrapper externo para isolar estilos do nosso bloco
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;'
        'max-width:640px;padding:0 0 8px 0;">\n'
        + paragraphs
        + img_block
        + "</div>\n"
        '<hr style="border:none;border-top:1px solid #e2e8f0;margin:8px 0 16px 0;" />\n'
    )
