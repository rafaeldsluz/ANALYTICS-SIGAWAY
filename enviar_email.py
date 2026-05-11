"""
Envio de e-mail HTML com assinatura rica via SMTP.
Imagens embutidas via CID (MIMEImage) — sem anexos visíveis.

Coloque na pasta Assinatura/:
  - jhefferson.jpg      (foto do vendedor)
  - banner_sigaway.jpg  (banner da empresa)
"""

import smtplib
import ssl
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# ── Configuração SMTP ─────────────────────────────────────────────────────────
SMTP_HOST     = "smtp.office365.com"
SMTP_PORT     = 587
SMTP_USER     = "rafael.luz@sigaway.com.br"
SMTP_PASSWORD = "Rafa2205!"

ASSETS_DIR = Path(__file__).parent / "Assinatura"

CID_PHOTO      = "jhefferson_photo@sigaway"
CID_BANNER     = "banner_sigaway@sigaway"
CID_SCREENSHOT = "torre_screenshot@sigaway"
_SHOT_MARKER   = "[SCREENSHOT]"


# ── Carregamento de imagem ────────────────────────────────────────────────────

def _load_image(filename: str) -> bytes:
    path = ASSETS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(
            f"Imagem não encontrada: {path}\n"
            f"Coloque o arquivo '{filename}' dentro da pasta Assinatura/"
        )
    return path.read_bytes()


# ── HTML do e-mail ────────────────────────────────────────────────────────────

def build_html(corpo: str, has_screenshot: bool = False) -> str:
    img_shot = ""
    if has_screenshot:
        img_shot = (
            f'<div style="margin:20px 0 24px 0;border-radius:8px;overflow:hidden;">'
            f'<img src="cid:{CID_SCREENSHOT}" '
            f'style="display:block;width:100%;max-width:576px;height:auto;" '
            f'alt="Torre de Controle" /></div>\n'
        )

    paragrafos = ""
    shot_inserted = False
    for linha in corpo.strip().split("\n"):
        linha = linha.strip()
        if not linha:
            continue
        if linha == _SHOT_MARKER:
            paragrafos += img_shot
            shot_inserted = True
            continue
        is_bullet = linha.startswith("•")
        margin    = "0 0 5px 0" if is_bullet else "0 0 16px 0"
        padding   = "padding-left:20px;" if is_bullet else ""
        paragrafos += (
            f'<p style="margin:{margin};{padding}font-size:15px;line-height:1.65;'
            f'color:#1a1a1a;font-family:Arial,Helvetica,sans-serif;">'
            f"{linha}</p>\n"
        )

    # Marcador não usado → screenshot vai antes do botão
    if has_screenshot and not shot_inserted:
        paragrafos += img_shot

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background-color:#ffffff;">

  <div style="max-width:640px;margin:0 auto;padding:32px 16px;
              font-family:Arial,Helvetica,sans-serif;">

    <!-- ── Contêiner principal ───────────────────────────────────────────── -->
    <div style="background-color:#ffffff;border-radius:12px;padding:36px 32px;
                border:1px solid #e2e8f0;">

      <!-- Corpo do e-mail -->
      {paragrafos}

      <!-- Divisor -->
      <hr style="border:none;border-top:1px solid #e2e8f0;margin:28px 0 24px 0;">

      <!-- Card do vendedor -->
      <table cellpadding="0" cellspacing="0" border="0" width="100%"
             style="border-collapse:collapse;">
        <tr>
          <!-- Foto circular -->
          <td style="width:80px;vertical-align:top;padding-right:18px;">
            <img src="cid:{CID_PHOTO}"
                 width="80" height="80"
                 alt="Jhefferson Andrade"
                 style="display:block;width:80px;height:80px;
                        border-radius:50%;object-fit:cover;
                        border:2px solid #e2e8f0;" />
          </td>

          <!-- Dados do vendedor -->
          <td style="vertical-align:top;">
            <p style="margin:0 0 4px 0;
                      font-size:16px;font-weight:bold;
                      color:#0f172a;
                      font-family:Arial,Helvetica,sans-serif;">
              Jhefferson Andrade
            </p>
            <p style="margin:0 0 4px 0;
                      font-size:13px;color:#475569;
                      font-family:Arial,Helvetica,sans-serif;">
              Comercial Sigaway
            </p>
            <p style="margin:0 0 4px 0;font-size:13px;
                      font-family:Arial,Helvetica,sans-serif;">
              <a href="mailto:jhefferson.andrade@sigaway.com.br"
                 style="color:#2563eb;text-decoration:none;">
                jhefferson.andrade@sigaway.com.br
              </a>
            </p>
            <p style="margin:0;font-size:13px;color:#475569;
                      font-family:Arial,Helvetica,sans-serif;">
              &#128222;&nbsp;(48) 9 9154-8197
            </p>
          </td>
        </tr>
      </table>

      <!-- Botão CTA -->
      <div style="text-align:center;margin-top:28px;">
        <a href="https://api.whatsapp.com/send/?phone=5548991548197&text&type=phone_number&app_absent=0&utm_campaign=sigaway_-_o_que_voce_pensa_sobre_cameras_em_caminhoes&utm_source=RD+Station"
           style="display:inline-block;
                  background-color:#22c55e;
                  color:#ffffff;
                  font-family:Arial,Helvetica,sans-serif;
                  font-size:15px;font-weight:bold;
                  padding:14px 36px;
                  border-radius:8px;
                  text-decoration:none;
                  letter-spacing:0.3px;">
          Clique aqui e entre em contato
        </a>
      </div>

    </div><!-- /contêiner principal -->

    <!-- ── Assinatura Rafael Luz ──────────────────────────────────────────── -->
    <div style="margin-top:28px;padding:0 4px;">
      <p style="margin:0 0 4px 0;
                font-size:17px;font-weight:bold;
                color:#0f172a;
                font-family:'Times New Roman',Georgia,serif;">
        Rafael Luz
      </p>
      <p style="margin:0 0 10px 0;
                font-size:13px;color:#475569;
                font-family:'Times New Roman',Georgia,serif;">
        Assistente Administrativo
      </p>
      <p style="margin:0 0 5px 0;
                font-size:13px;color:#475569;
                font-family:'Times New Roman',Georgia,serif;">
        &#128222;&nbsp;(48) 9652-7654
      </p>
      <p style="margin:0 0 24px 0;
                font-size:13px;
                font-family:'Times New Roman',Georgia,serif;">
        &#127758;&nbsp;<a href="https://www.sigaway.com.br"
           style="color:#9b72cf;text-decoration:underline;">
          SIGAWAY
        </a>
      </p>
    </div>

    <!-- ── Banner da empresa ──────────────────────────────────────────────── -->
    <div style="text-align:center;">
      <img src="cid:{CID_BANNER}"
           alt="Sigaway"
           style="display:block;width:100%;max-width:640px;
                  height:auto;border-radius:8px;" />
    </div>

  </div><!-- /wrapper -->

</body>
</html>"""


# ── Montagem e envio ──────────────────────────────────────────────────────────

def send_email(
    to_email: str,
    subject: str,
    corpo: str,
    cc_email: str = "",
    screenshot_path: str | None = None,
    smtp_user: str = "",
    smtp_password: str = "",
) -> None:
    """
    Monta e envia o e-mail com imagens inline via CID.
    Use [SCREENSHOT] no corpo para posicionar a screenshot da empresa.

    Estrutura MIME:
      multipart/related
        multipart/alternative
          text/plain       (fallback)
          text/html        (versão rica)
        image/jpeg         (foto Jhefferson)
        image/jpeg         (banner Sigaway)
        image/png          (screenshot empresa — opcional)
    """
    shot_resolved = Path(screenshot_path).resolve() if screenshot_path else None
    if shot_resolved and not shot_resolved.exists():
        raise FileNotFoundError(f"Screenshot não encontrado: {shot_resolved}")

    html = build_html(corpo, has_screenshot=shot_resolved is not None)

    _user = smtp_user or SMTP_USER
    _pwd  = smtp_password or SMTP_PASSWORD

    msg = MIMEMultipart("related")
    msg["From"]    = _user
    msg["To"]      = to_email
    msg["Subject"] = subject
    cc_addrs = [a.strip() for a in cc_email.replace(";", ",").split(",") if a.strip()] if cc_email else []
    if cc_addrs:
        msg["Cc"] = ", ".join(cc_addrs)

    alt = MIMEMultipart("alternative")
    msg.attach(alt)
    alt.attach(MIMEText(corpo, "plain", "utf-8"))
    alt.attach(MIMEText(html,  "html",  "utf-8"))

    # Foto do Jhefferson
    img_photo = MIMEImage(_load_image("WhatsApp Image 2026-04-30 at 15.38.06.jpeg"))
    img_photo.add_header("Content-ID", f"<{CID_PHOTO}>")
    img_photo.add_header("Content-Disposition", "inline", filename="jhefferson.jpg")
    msg.attach(img_photo)

    # Banner Sigaway
    img_banner = MIMEImage(_load_image("4bcc7725-fba2-463b-8f72-d7bd7d84e0a7.jpg"))
    img_banner.add_header("Content-ID", f"<{CID_BANNER}>")
    img_banner.add_header("Content-Disposition", "inline", filename="banner_sigaway.jpg")
    msg.attach(img_banner)

    # Screenshot da empresa (opcional)
    if shot_resolved:
        img_shot = MIMEImage(shot_resolved.read_bytes())
        img_shot.add_header("Content-ID", f"<{CID_SCREENSHOT}>")
        img_shot.add_header("Content-Disposition", "inline", filename="screenshot.png")
        msg.attach(img_shot)

    # Envio
    recipients = [to_email] + cc_addrs
    context    = ssl.create_default_context()

    print(f"Conectando a {SMTP_HOST}:{SMTP_PORT}...")
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(_user, _pwd)
            server.sendmail(_user, recipients, msg.as_string())
            print(f"OK - E-mail enviado para {to_email}")

    except smtplib.SMTPAuthenticationError:
        raise RuntimeError(
            "Autenticação SMTP falhou. Verifique SMTP_USER e SMTP_PASSWORD.\n"
            "Se usar Gmail, ative 'Senhas de app' nas configurações da conta."
        )
    except smtplib.SMTPConnectError as e:
        raise RuntimeError(
            f"Não foi possível conectar ao servidor {SMTP_HOST}:{SMTP_PORT}.\n"
            f"Detalhe: {e}"
        )
    except smtplib.SMTPRecipientsRefused as e:
        raise RuntimeError(f"Destinatário recusado pelo servidor: {e}")
    except smtplib.SMTPSenderRefused as e:
        raise RuntimeError(f"Remetente recusado — verifique SMTP_USER: {e}")
    except smtplib.SMTPDataError as e:
        raise RuntimeError(f"Servidor recusou o conteúdo do e-mail: {e}")
    except smtplib.SMTPException as e:
        raise RuntimeError(f"Erro SMTP inesperado: {e}")
    except TimeoutError:
        raise RuntimeError(
            f"Timeout ao conectar a {SMTP_HOST}:{SMTP_PORT}. "
            "Verifique sua conexão e o firewall."
        )


# ── Ponto de entrada ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    send_email(
        to_email="rafaelsilvaluz07@gmail.com",
        subject="Relatório Torre de Controle — Sigaway",
        corpo=(
            "Você sabia que possui acesso a um ranking que mostra exatamente quais veículos estão abaixo da nota ideal?\n"
            "Nos últimos 7 dias, parte da sua frota operou abaixo do padrão recomendado.\n"
            "A diferença entre um score 96 e 100 pode representar:\n"
            "• Mais consumo de combustível\n"
            "• Maior desgaste de pneus\n"
            "• Maior risco de parada inesperada\n"
            "• Maior risco de acidente\n"
            "• Maior risco de multa\n"
            "A pergunta não é se isso impacta o custo.\n"
            "É QUANTO.\n"
            "\n"
            "Se quiser entender quais veículos estão impactando sua média e como corrigir isso rapidamente, "
            "acesse o ranking completo da sua frota 👉 https://app.sigaway.com.br/\n"
            "\n"
            "Ou fale diretamente com um de nossos especialistas e receba uma análise personalizada da sua operação."
        ),
        cc_email="",
    )
