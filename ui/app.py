"""
Sigaway Agent — Interface Principal (CRM v2).
Sidebar navigation · GitHub-dark palette · SDR Agent integrado.
"""

import logging
import os
import queue
import sys
import threading
import uuid as _uuid_mod
from datetime import datetime as _dt_now
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")

# ── Paleta ────────────────────────────────────────────────────────────────────
BG          = "#0d1117"
SIDEBAR_BG  = "#161b22"
SURFACE     = "#1c2128"
SURFACE2    = "#161b22"
CARD        = "#21262d"
BORDER      = "#30363d"
BORDER2     = "#3d444d"
GREEN       = "#22c55e"
GREEN_BRIGHT= "#4ade80"
GREEN_DIM   = "#0a3622"
GREEN_GLOW  = "#15803d"
RED         = "#ef4444"
AMBER       = "#e3b341"
TEXT        = "#e6edf3"
TEXT_SEC    = "#8d96a0"
TEXT_MUTED  = "#545d68"
CONSOLE_BG  = "#0d1117"
CONSOLE_TXT = "#7ee787"
WZ_GREEN    = "#25D366"
WZ_DIM      = "#064e3b"
WZ_GLOW     = "#059669"
SDR         = "#818cf8"
SDR_DIM     = "#1e1b4b"
SDR_GLOW    = "#4338ca"
SDR_BRIGHT  = "#a5b4fc"
LEADS       = "#38bdf8"
LEADS_DIM   = "#0c2840"
LEADS_GLOW  = "#0284c7"

MONO   = "Consolas"
SANS   = "Segoe UI"
LOGO_P = Path(__file__).parent.parent / "Ativo 1@2x.png"

DEFAULT_BODY = (
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
    "[SCREENSHOT]\n"
    "Se quiser entender quais veículos estão impactando sua média e como corrigir isso rapidamente, acesse o ranking completo da sua frota: https://app.sigaway.com.br/\n"
    "\n"
    "Ou fale diretamente com um de nossos especialistas e receba uma análise personalizada da sua operação."
)

DEFAULT_WZ_MSG = (
    "Bom dia, tudo bem? Meu nome é Rafael, sou estudante da 7ª fase de Ciências Econômicas na UNESC. 🎓\n\n"
    "Estamos realizando uma pesquisa acadêmica focada nas empresas aqui da região da AMREC sobre o uso de operações de Factoring.\n\n"
    "Sei que a rotina é bem corrida, mas o questionário é bem rápido (leva uns 2 minutinhos) e a visão da sua empresa seria fundamental para o nosso estudo! Você conseguiria nos ajudar respondendo?\n\n"
    "Segue o link: https://docs.google.com/forms/d/e/1FAIpQLSc3OGkn7ORrgWG0Lmgf-jpk21wIhPvJSsvXI5ejN-vrRKHBlQ/viewform\n\n"
    "Fico muito grato desde já pela força! 🙏"
)


# ── Queue log handler ─────────────────────────────────────────────────────────
class _QHandler(logging.Handler):
    def __init__(self, q):
        super().__init__()
        self._q = q

    def emit(self, r):
        self._q.put(r)


# ── Helpers de widget ─────────────────────────────────────────────────────────
def _label(parent, text, size=11, weight="normal", color=TEXT, font=SANS, **kw):
    return ctk.CTkLabel(
        parent, text=text,
        font=ctk.CTkFont(family=font, size=size, weight=weight),
        text_color=color, **kw,
    )


def _entry(parent, placeholder="", secret=False, default="", height=36, font_size=11):
    e = ctk.CTkEntry(
        parent, placeholder_text=placeholder,
        fg_color=CARD, border_color=BORDER2,
        text_color=TEXT, placeholder_text_color=TEXT_MUTED,
        show="*" if secret else "",
        height=height,
        font=ctk.CTkFont(family=SANS, size=font_size),
        corner_radius=8,
    )
    if default:
        e.insert(0, default)
    return e


def _section_header(parent, text, pad_top=18, accent=GREEN, dim=GREEN_DIM):
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    frame.pack(fill="x", padx=0, pady=(pad_top, 8))
    _label(frame, text, size=10, weight="bold", color=accent, font=MONO).pack(side="left")
    ctk.CTkFrame(frame, fg_color=dim, height=1).pack(
        side="left", fill="x", expand=True, padx=(8, 0), pady=(1, 0)
    )


def _field_group(parent, label, widget_factory):
    _label(parent, label, size=10, color=TEXT_SEC).pack(anchor="w", padx=2, pady=(10, 2))
    w = widget_factory()
    w.pack(fill="x", padx=2)
    return w


def _metric_card(parent, title: str, color: str = GREEN) -> ctk.CTkLabel:
    card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=12,
                        border_color=BORDER2, border_width=1)
    card.pack(side="left", fill="both", expand=True, padx=5, pady=0)
    lbl_val = ctk.CTkLabel(
        card, text="0",
        font=ctk.CTkFont(family=MONO, size=28, weight="bold"),
        text_color=color,
    )
    lbl_val.pack(pady=(14, 2))
    _label(card, title, size=9, weight="bold", color=TEXT_MUTED, font=MONO).pack(pady=(0, 12))
    return lbl_val


# ── App ───────────────────────────────────────────────────────────────────────
class SigawayAgentApp(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title("Sigaway Agent")
        self.geometry("1380x880")
        self.minsize(1100, 720)
        self.configure(fg_color=BG)

        # Estado E-mail
        self._stop    = threading.Event()
        self._running = threading.Event()
        self._running.set()           # inicia não-pausado
        self._queue   = queue.Queue()
        self._thread  = None
        self._entries: dict[str, ctk.CTkEntry] = {}
        self._blink_id = None
        self._email_skipped_count: int = 0

        # Estado WhatsApp
        self._wz_queue    = None
        self._wz_campaign = None
        self._wz_tick_id  = None
        self._wz_entries: dict[str, ctk.CTkEntry] = {}
        self._email_campaign_id: str | None = None
        self._email_no_email_count: int = 0

        self._setup_log()
        self._build()
        self._poll()
        self._log("Sistema inicializado. Configure as credenciais e edite o e-mail.", "INFO")

    # ── Logging ───────────────────────────────────────────────────────────────
    def _setup_log(self):
        h = _QHandler(self._queue)
        h.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s", "%H:%M:%S"))
        root = logging.getLogger()
        root.setLevel(logging.DEBUG)
        root.addHandler(h)
        self._logger = logging.getLogger("sigaway_agent")

    def _log(self, msg, level="INFO"):
        getattr(self._logger, level.lower(), self._logger.info)(msg)

    # ── Build ─────────────────────────────────────────────────────────────────
    def _build(self):
        # ── Layout principal: sidebar + conteúdo ──────────────────────────────
        self._build_sidebar()

        self._content_area = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self._content_area.pack(side="left", fill="both", expand=True)

        self._build_content_header()

        # ── Container de páginas ──────────────────────────────────────────────
        self._pages_wrap = ctk.CTkFrame(self._content_area, fg_color=BG, corner_radius=0)
        self._pages_wrap.pack(fill="both", expand=True)

        # Página E-mail
        self._email_page = ctk.CTkFrame(self._pages_wrap, fg_color=BG)
        self._build_left(self._email_page)
        self._build_console(self._email_page)

        # Página WhatsApp
        self._wz_page = ctk.CTkFrame(self._pages_wrap, fg_color=BG)
        self._build_wz_page(self._wz_page)

        # Página SDR Agent
        self._sdr_page_frame = ctk.CTkFrame(self._pages_wrap, fg_color=BG)
        self._build_sdr_page(self._sdr_page_frame)

        # Página Leads / CNAE
        self._leads_page_frame = ctk.CTkFrame(self._pages_wrap, fg_color=BG)
        self._build_leads_page(self._leads_page_frame)

        # Footers (empacotam no content_area, side="bottom")
        self._build_footer()
        self._build_wz_footer()
        self._wz_footer_frame.pack_forget()

        # Página padrão: e-mail
        self._email_page.pack(fill="both", expand=True, padx=16, pady=(8, 0))
        self._current_page = "email"

    # ── Sidebar ───────────────────────────────────────────────────────────────
    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, fg_color=SIDEBAR_BG, width=220, corner_radius=0)
        sb.pack(side="left", fill="y")
        sb.pack_propagate(False)

        # Logo
        logo_frame = ctk.CTkFrame(sb, fg_color="transparent", height=68)
        logo_frame.pack(fill="x")
        logo_frame.pack_propagate(False)

        if LOGO_P.exists():
            img  = Image.open(LOGO_P).convert("RGBA")
            h    = 32
            w    = int(img.width * h / img.height)
            logo = ctk.CTkImage(light_image=img, dark_image=img, size=(w, h))
            ctk.CTkLabel(logo_frame, image=logo, text="").pack(
                side="left", padx=18, pady=18
            )
        else:
            _label(sb, "SIGAWAY", size=16, weight="bold",
                   color=GREEN, font=MONO).pack(anchor="w", padx=18, pady=18)

        ctk.CTkFrame(sb, fg_color=BORDER, height=1).pack(fill="x", padx=0)

        # Nav label
        _label(sb, "MÓDULOS", size=9, weight="bold",
               color=TEXT_MUTED, font=MONO).pack(anchor="w", padx=18, pady=(16, 6))

        # Nav items: (page_key, label, active_color, active_bg)
        nav_defs = [
            ("email",     "  📧  E-MAIL AGENT",   GREEN,    GREEN_DIM),
            ("whatsapp",  "  💬  WHATSAPP",        WZ_GREEN, WZ_DIM),
            ("sdr",       "  🤖  SDR AGENT",       SDR,      SDR_DIM),
            ("leads",     "  🎯  LEADS / CNAE",    LEADS,    LEADS_DIM),
        ]
        self._nav_btns: dict[str, dict] = {}
        for key, label, active_col, active_bg in nav_defs:
            btn = ctk.CTkButton(
                sb, text=label,
                font=ctk.CTkFont(family=SANS, size=12),
                fg_color="transparent", hover_color=CARD,
                text_color=TEXT_MUTED, anchor="w",
                corner_radius=8, height=42,
                command=lambda k=key: self._show_page(k),
            )
            btn.pack(fill="x", padx=8, pady=2)
            self._nav_btns[key] = {
                "btn": btn, "color": active_col, "bg": active_bg,
            }

        # Ativa e-mail por padrão
        self._nav_btns["email"]["btn"].configure(
            fg_color=GREEN_DIM, text_color=GREEN
        )

        # Status no rodapé da sidebar
        ctk.CTkFrame(sb, fg_color=BORDER, height=1).pack(
            fill="x", side="bottom", padx=0, pady=(0, 0)
        )
        status_card = ctk.CTkFrame(sb, fg_color=CARD, corner_radius=10)
        status_card.pack(fill="x", padx=10, pady=10, side="bottom")

        self._lbl_status = ctk.CTkLabel(
            status_card, text="  ●  AGUARDANDO",
            font=ctk.CTkFont(family=MONO, size=10, weight="bold"),
            text_color=AMBER,
        )
        self._lbl_status.pack(padx=10, pady=8)

    # ── Content header (thin bar acima das páginas) ───────────────────────────
    def _build_content_header(self):
        bar = ctk.CTkFrame(
            self._content_area, fg_color=SIDEBAR_BG,
            height=46, corner_radius=0,
        )
        bar.pack(fill="x")
        bar.pack_propagate(False)

        self._lbl_page_title = _label(
            bar, "E-MAIL AGENT  /  Disparo Automático",
            size=11, color=TEXT_SEC,
        )
        self._lbl_page_title.pack(side="left", padx=20, pady=12)

        ctk.CTkFrame(
            self._content_area, fg_color=GREEN_DIM, height=2, corner_radius=0
        ).pack(fill="x")

    _PAGE_TITLES = {
        "email":    "E-MAIL AGENT  /  Disparo Automático",
        "whatsapp": "WHATSAPP  /  Disparo de Mensagens",
        "sdr":      "SDR AGENT  /  Centro de Controle",
        "leads":    "LEADS  /  Extração por CNAE  —  Brasil.io + CNPJ.ws",
    }

    # ── Page switcher ─────────────────────────────────────────────────────────
    def _show_page(self, name: str):
        if name == self._current_page:
            return

        # Reset todos os nav items
        for key, cfg in self._nav_btns.items():
            cfg["btn"].configure(fg_color="transparent", text_color=TEXT_MUTED)

        # Ativa o selecionado
        cfg = self._nav_btns.get(name, {})
        if cfg:
            cfg["btn"].configure(fg_color=cfg["bg"], text_color=cfg["color"])

        # Esconde tudo
        for page in (self._email_page, self._wz_page, self._sdr_page_frame, self._leads_page_frame):
            page.pack_forget()
        for footer in (self._email_footer_frame, self._wz_footer_frame):
            footer.pack_forget()

        # Mostra página selecionada
        if name == "email":
            self._email_page.pack(fill="both", expand=True, padx=16, pady=(8, 0))
            self._email_footer_frame.pack(fill="x", side="bottom")
        elif name == "whatsapp":
            self._wz_page.pack(fill="both", expand=True, padx=16, pady=(8, 0))
            self._wz_footer_frame.pack(fill="x", side="bottom")
        elif name == "sdr":
            self._sdr_page_frame.pack(fill="both", expand=True, padx=16, pady=(8, 0))
        elif name == "leads":
            self._leads_page_frame.pack(fill="both", expand=True, padx=16, pady=(8, 0))

        # Atualiza título
        title = self._PAGE_TITLES.get(name, "")
        self._lbl_page_title.configure(text=title)

        self._current_page = name

    # ── SDR page mount ────────────────────────────────────────────────────────
    def _build_sdr_page(self, parent):
        try:
            from ui.sdr_page import SDRPage
            self._sdr_page = SDRPage(parent, log_callback=self._log)
            self._sdr_page.pack(fill="both", expand=True)

            # Registra callback de atualização
            try:
                from sdr.server import set_update_callback
                set_update_callback(self._sdr_page.refresh_stats)
            except Exception:
                pass
        except Exception as e:
            _label(parent, f"Erro ao carregar SDR page: {e}",
                   size=11, color=RED).pack(pady=40)

    # ── Leads page mount ──────────────────────────────────────────────────────
    def _build_leads_page(self, parent):
        try:
            from ui.leads_page import LeadsPage
            self._leads_page = LeadsPage(parent, log_callback=self._log)
            self._leads_page.pack(fill="both", expand=True)
        except Exception as e:
            _label(parent, f"Erro ao carregar Leads page: {e}",
                   size=11, color=RED).pack(pady=40)

    # ── Left panel (e-mail) ───────────────────────────────────────────────────
    def _build_left(self, parent):
        panel = ctk.CTkFrame(parent, fg_color=SURFACE, corner_radius=16,
                             border_color=BORDER, border_width=1, width=420)
        panel.pack(side="left", fill="y", padx=(0, 14), pady=(0, 12))
        panel.pack_propagate(False)

        tabs = ctk.CTkTabview(
            panel,
            fg_color=SURFACE,
            segmented_button_fg_color=SIDEBAR_BG,
            segmented_button_selected_color=GREEN_GLOW,
            segmented_button_selected_hover_color=GREEN_DIM,
            segmented_button_unselected_color=SIDEBAR_BG,
            segmented_button_unselected_hover_color=CARD,
            text_color=TEXT,
            border_color=BORDER, border_width=1,
            corner_radius=12,
        )
        tabs.pack(fill="both", expand=True, padx=12, pady=12)
        tabs.add("  CONFIG  ")
        tabs.add("  E-MAIL  ")
        tabs.add("  TESTES  ")
        tabs.add("  MÉTRICAS  ")

        self._build_config_tab(tabs.tab("  CONFIG  "))
        self._build_email_tab(tabs.tab("  E-MAIL  "))
        self._build_tests_tab(tabs.tab("  TESTES  "))
        self._build_metrics_tab(tabs.tab("  MÉTRICAS  "))

    def _build_config_tab(self, tab):
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent",
                                        scrollbar_button_color=BORDER2,
                                        scrollbar_button_hover_color=GREEN_DIM)
        scroll.pack(fill="both", expand=True)

        _section_header(scroll, "ACESSO AO SIGAWAY", pad_top=4)

        for label, key, ph, sec in [
            ("URL da plataforma", "SIGAWAY_URL",  "https://app.sigaway.com.br", False),
            ("Usuário",           "SIGAWAY_USER", "seu@email.com",              False),
            ("Senha",             "SIGAWAY_PASS", "••••••••",                   True),
        ]:
            self._entries[key] = _field_group(
                scroll, label,
                lambda ph=ph, sec=sec, key=key: _entry(
                    scroll, ph, sec, os.getenv(key, "")
                )
            )

        _section_header(scroll, "ENVIO DE E-MAIL (SMTP)")

        for label, key, ph, sec, default in [
            ("E-mail remetente", "SMTP_USER", "email@sigaway.com.br", False,
             os.getenv("SMTP_USER", "rafael.luz@sigaway.com.br")),
            ("Senha do e-mail",  "SMTP_PASS", "••••••••",             True,
             os.getenv("SMTP_PASS", "")),
        ]:
            self._entries[key] = _field_group(
                scroll, label,
                lambda ph=ph, sec=sec, d=default: _entry(scroll, ph, sec, d)
            )

        _section_header(scroll, "DISPARO")

        self._entries["EMAIL_CC"] = _field_group(
            scroll, "CC (opcional)",
            lambda: _entry(scroll, "gerencia@empresa.com",
                           default=os.getenv("EMAIL_CC", ""))
        )

        _label(scroll, "Intervalo entre envios (segundos)", size=10,
               color=TEXT_SEC).pack(anchor="w", padx=2, pady=(10, 2))
        interval_row = ctk.CTkFrame(scroll, fg_color="transparent")
        interval_row.pack(fill="x", padx=2)

        _label(interval_row, "Mín", size=10, color=TEXT_MUTED).pack(side="left")
        self._interval_min = ctk.CTkEntry(
            interval_row, width=60, height=34, fg_color=CARD,
            border_color=BORDER2, text_color=TEXT, corner_radius=8,
            font=ctk.CTkFont(family=MONO, size=11),
        )
        self._interval_min.insert(0, "30")
        self._interval_min.pack(side="left", padx=(4, 8))

        _label(interval_row, "Máx", size=10, color=TEXT_MUTED).pack(side="left")
        self._interval_max = ctk.CTkEntry(
            interval_row, width=60, height=34, fg_color=CARD,
            border_color=BORDER2, text_color=TEXT, corner_radius=8,
            font=ctk.CTkFont(family=MONO, size=11),
        )
        self._interval_max.insert(0, "90")
        self._interval_max.pack(side="left", padx=(4, 0))

        self._lbl_eta = _label(
            scroll, "100 e-mails ≈ 1h 50min com intervalo de 60s",
            size=9, color=TEXT_MUTED,
        )
        self._lbl_eta.pack(anchor="w", padx=2, pady=(4, 0))
        self._interval_min.bind("<KeyRelease>", lambda e: self._update_eta())
        self._interval_max.bind("<KeyRelease>", lambda e: self._update_eta())

        _section_header(scroll, "MICROSOFT GRAPH API  (retornos)")
        _label(scroll,
               "Opcional — necessário apenas para verificar e-mails retornados (NDR).",
               size=9, color=TEXT_MUTED
               ).pack(anchor="w", padx=2, pady=(0, 4))

        for label, key, ph, sec in [
            ("Tenant ID",     "GRAPH_TENANT_ID",     "xxxxxxxx-xxxx-…", False),
            ("Client ID",     "GRAPH_CLIENT_ID",     "xxxxxxxx-xxxx-…", False),
            ("Client Secret", "GRAPH_CLIENT_SECRET", "••••••••",        True),
        ]:
            self._entries[key] = _field_group(
                scroll, label,
                lambda ph=ph, sec=sec, key=key: _entry(
                    scroll, ph, sec, os.getenv(key, "")
                )
            )

        _section_header(scroll, "ARQUIVO EXCEL")
        self._excel_entry = _field_group(
            scroll, "Planilha de destinatários",
            lambda: self._make_excel_picker(scroll)
        )

        _section_header(scroll, "MEMÓRIA ANTI-DUPLICATA")
        self._chk_skip_sent = ctk.CTkCheckBox(
            scroll, text="Pular e-mails já enviados em campanhas anteriores",
            font=ctk.CTkFont(family=SANS, size=11),
            text_color=TEXT, fg_color=GREEN_GLOW,
            hover_color=GREEN_DIM, checkmark_color="#ffffff",
        )
        self._chk_skip_sent.select()
        self._chk_skip_sent.pack(anchor="w", padx=2, pady=(4, 6))

        ctk.CTkButton(
            scroll, text="Ver histórico / Limpar memória",
            font=ctk.CTkFont(family=SANS, size=10),
            fg_color=SURFACE, hover_color="#2a0a0a",
            text_color=TEXT_MUTED, border_color=BORDER2, border_width=1,
            corner_radius=8, height=32,
            command=self._on_clear_history,
        ).pack(fill="x", padx=2, pady=(0, 8))

        self._stats_card = ctk.CTkFrame(scroll, fg_color=CARD, corner_radius=10,
                                        border_color=BORDER, border_width=1)
        self._stats_card.pack(fill="x", padx=2, pady=(20, 8))
        self._lbl_stats = _label(self._stats_card,
                                  "Aguardando início...", size=11, color=TEXT_MUTED, font=MONO)
        self._lbl_stats.pack(padx=16, pady=12, anchor="w")

    def _make_excel_picker(self, parent):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        entry = _entry(frame, "Caminho do arquivo Excel",
                       default=os.getenv("EXCEL_PATH",
                                         str(Path(__file__).parent.parent / "AÇÃO E-MKT.xlsx")))
        entry.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(frame, text="···", width=38, height=36,
                      fg_color=CARD, hover_color=BORDER2,
                      text_color=TEXT_SEC, corner_radius=8,
                      command=lambda: self._browse(entry)).pack(side="right", padx=(6, 0))
        return frame

    def _build_email_tab(self, tab):
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent",
                                        scrollbar_button_color=BORDER2)
        scroll.pack(fill="both", expand=True)

        _section_header(scroll, "ASSUNTO", pad_top=4)
        self._entries["EMAIL_SUBJECT"] = ctk.CTkEntry(
            scroll,
            placeholder_text="Ex: SUA FROTA APRESENTA VEÍCULOS COM PERFORMANCE REDUZIDA",
            fg_color=CARD, border_color=GREEN_DIM, border_width=2,
            text_color=TEXT, placeholder_text_color=TEXT_MUTED,
            height=40, corner_radius=8,
            font=ctk.CTkFont(family=SANS, size=12, weight="bold"),
        )
        default_subj = os.getenv("EMAIL_SUBJECT",
                                  "SUA FROTA APRESENTA VEICULOS COM PERFORMANCE REDUZIDA")
        if default_subj:
            self._entries["EMAIL_SUBJECT"].insert(0, default_subj)
        self._entries["EMAIL_SUBJECT"].pack(fill="x", padx=2)

        _section_header(scroll, "CORPO DO E-MAIL")
        _label(scroll,
               "Cada parágrafo separado por linha em branco. O screenshot é anexado individualmente.",
               size=9, color=TEXT_MUTED
               ).pack(anchor="w", padx=2, pady=(0, 6))

        self._email_body = ctk.CTkTextbox(
            scroll, fg_color=CARD, text_color=TEXT,
            font=ctk.CTkFont(family=SANS, size=12),
            corner_radius=10, border_color=BORDER2, border_width=1,
            wrap="word", height=200,
        )
        self._email_body.insert("1.0", DEFAULT_BODY)
        self._email_body.pack(fill="x", padx=2)

        ctk.CTkButton(scroll, text="Limpar", height=28, width=80,
                      fg_color=SURFACE, hover_color=CARD,
                      text_color=TEXT_MUTED, corner_radius=8,
                      font=ctk.CTkFont(family=SANS, size=10),
                      command=lambda: (
                          self._email_body.delete("1.0", "end"),
                          self._email_body.insert("1.0", "Prezado(a),\n\n"),
                      )).pack(anchor="e", padx=2, pady=(6, 0))

    def _build_tests_tab(self, tab):
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent",
                                        scrollbar_button_color=BORDER2,
                                        scrollbar_button_hover_color=GREEN_DIM)
        scroll.pack(fill="both", expand=True)

        _section_header(scroll, "CAPTURA DE SCREENSHOT", pad_top=4)
        _label(scroll, "Digite o nome (ou parte) da empresa para testar a captura",
               size=9, color=TEXT_MUTED).pack(anchor="w", padx=2, pady=(0, 4))

        self._test_company = _field_group(
            scroll, "Nome da empresa (palavra-chave)",
            lambda: _entry(scroll, "Ex: GARIBALDI ou SPRICIGO")
        )

        self._btn_test = ctk.CTkButton(
            scroll, text="📷  Testar Screenshot",
            font=ctk.CTkFont(family=SANS, size=12),
            fg_color=SURFACE, hover_color=CARD,
            text_color=CONSOLE_TXT, border_color=GREEN_DIM, border_width=1,
            corner_radius=10, height=40,
            command=self._on_test_screenshot,
        )
        self._btn_test.pack(fill="x", padx=2, pady=(0, 4))

        _section_header(scroll, "CONEXÃO COM OUTLOOK")
        _label(scroll, "Verifica se o Outlook está aberto e acessível.",
               size=9, color=TEXT_MUTED).pack(anchor="w", padx=2, pady=(0, 8))

        self._btn_outlook = ctk.CTkButton(
            scroll, text="📧  Testar Conexão Outlook",
            font=ctk.CTkFont(family=SANS, size=12),
            fg_color=SURFACE, hover_color=CARD,
            text_color=AMBER, border_color=BORDER2, border_width=1,
            corner_radius=10, height=40,
            command=self._on_test_outlook,
        )
        self._btn_outlook.pack(fill="x", padx=2, pady=(0, 4))

        _section_header(scroll, "ENVIO DE E-MAIL AVULSO")
        _label(scroll, "Envia para um endereço avulso usando o assunto e corpo da aba E-MAIL",
               size=9, color=TEXT_MUTED).pack(anchor="w", padx=2, pady=(0, 6))

        self._test_email = _field_group(
            scroll, "E-mail destinatário",
            lambda: _entry(scroll, "seuemail@teste.com")
        )

        self._btn_send_test = ctk.CTkButton(
            scroll, text="Enviar E-mail de Teste",
            font=ctk.CTkFont(family=SANS, size=12),
            fg_color=SURFACE, hover_color=GREEN_DIM,
            text_color=GREEN, border_color=GREEN_DIM, border_width=1,
            corner_radius=10, height=40,
            command=self._on_send_test,
        )
        self._btn_send_test.pack(fill="x", padx=2, pady=(8, 4))

    def _build_metrics_tab(self, tab):
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent",
                                        scrollbar_button_color=BORDER2,
                                        scrollbar_button_hover_color=GREEN_DIM)
        scroll.pack(fill="both", expand=True)

        _section_header(scroll, "CAMPANHA ATUAL", pad_top=4)
        self._lbl_metrics_campaign = _label(
            scroll, "Nenhuma campanha iniciada.", size=10, color=TEXT_MUTED, font=MONO
        )
        self._lbl_metrics_campaign.pack(anchor="w", padx=2, pady=(0, 8))

        row_btns = ctk.CTkFrame(scroll, fg_color="transparent")
        row_btns.pack(fill="x", padx=2, pady=(0, 4))

        self._btn_export_csv = ctk.CTkButton(
            row_btns, text="Exportar CSV",
            font=ctk.CTkFont(family=SANS, size=11),
            fg_color=SURFACE, hover_color=GREEN_DIM,
            text_color=GREEN, border_color=GREEN_DIM, border_width=1,
            corner_radius=8, height=34,
            command=self._on_export_csv,
        )
        self._btn_export_csv.pack(side="left")

        _section_header(scroll, "RETORNOS  (NDR — requer Graph API)")
        _label(scroll,
               "Verifica a caixa de entrada em busca de e-mails devolvidos.",
               size=9, color=TEXT_MUTED, wraplength=360,
               ).pack(anchor="w", padx=2, pady=(0, 8))

        self._btn_check_bounces = ctk.CTkButton(
            scroll, text="Verificar Retornos (NDR)",
            font=ctk.CTkFont(family=SANS, size=11),
            fg_color=SURFACE, hover_color="#4a0a6a",
            text_color="#a855f7", border_color="#6b21a8", border_width=1,
            corner_radius=8, height=34,
            command=self._on_check_bounces,
        )
        self._btn_check_bounces.pack(fill="x", padx=2)

        _section_header(scroll, "HISTÓRICO DE CAMPANHAS")
        self._history_text = ctk.CTkTextbox(
            scroll, fg_color=CONSOLE_BG, text_color=CONSOLE_TXT,
            font=ctk.CTkFont(family=MONO, size=9),
            corner_radius=8, border_color=BORDER2, border_width=1,
            wrap="none", height=200, state="disabled",
        )
        self._history_text.pack(fill="x", padx=2, pady=(0, 8))

        ctk.CTkButton(
            scroll, text="Atualizar histórico", height=28,
            fg_color=SURFACE, hover_color=CARD,
            text_color=TEXT_MUTED, corner_radius=8,
            font=ctk.CTkFont(family=SANS, size=10),
            command=self._do_refresh_metrics_history,
        ).pack(anchor="e", padx=2)

    # ── Console (e-mail) ──────────────────────────────────────────────────────
    def _build_console(self, parent):
        panel = ctk.CTkFrame(parent, fg_color=SURFACE, corner_radius=16,
                             border_color=BORDER, border_width=1)
        panel.pack(side="left", fill="both", expand=True, pady=(0, 12))

        con_hdr = ctk.CTkFrame(panel, fg_color="transparent", height=44)
        con_hdr.pack(fill="x", padx=16, pady=(14, 4))
        con_hdr.pack_propagate(False)
        _label(con_hdr, "CONSOLE DE OPERAÇÕES", size=10, weight="bold",
               color=GREEN, font=MONO).pack(side="left", pady=10)
        ctk.CTkButton(
            con_hdr, text="Limpar", height=24, width=60,
            fg_color=CARD, hover_color=BORDER2,
            text_color=TEXT_MUTED, corner_radius=6,
            font=ctk.CTkFont(family=SANS, size=9),
            command=self._clear_console,
        ).pack(side="right", pady=10)

        ctk.CTkFrame(panel, fg_color=BORDER, height=1).pack(fill="x", padx=16)

        cards_row = ctk.CTkFrame(panel, fg_color="transparent")
        cards_row.pack(fill="x", padx=12, pady=(10, 0))

        self._lbl_em_total   = _metric_card(cards_row, "TOTAL",     TEXT_SEC)
        self._lbl_em_sent    = _metric_card(cards_row, "ENVIADOS",  GREEN)
        self._lbl_em_failed  = _metric_card(cards_row, "FALHAS",    RED)
        self._lbl_em_skipped = _metric_card(cards_row, "PULADOS",   "#f59e0b")
        self._lbl_em_noemail = _metric_card(cards_row, "SEM EMAIL", AMBER)
        self._lbl_em_bounced = _metric_card(cards_row, "RETORNOS",  "#a855f7")

        ctk.CTkFrame(panel, fg_color=BORDER2, height=1).pack(fill="x", padx=12, pady=(10, 0))

        self._txt_log = ctk.CTkTextbox(
            panel, fg_color=CONSOLE_BG, text_color=CONSOLE_TXT,
            font=ctk.CTkFont(family=MONO, size=11),
            corner_radius=10, border_color=BORDER, border_width=1,
            wrap="word", state="disabled",
        )
        self._txt_log.pack(fill="both", expand=True, padx=12, pady=12)

    # ── Footer (e-mail) ───────────────────────────────────────────────────────
    def _build_footer(self):
        ctk.CTkFrame(self._content_area, fg_color=BORDER, height=1).pack(fill="x")

        self._email_footer_frame = ctk.CTkFrame(
            self._content_area, fg_color=SURFACE, corner_radius=0, height=68
        )
        self._email_footer_frame.pack(fill="x", side="bottom")
        self._email_footer_frame.pack_propagate(False)

        btn_area = ctk.CTkFrame(self._email_footer_frame, fg_color="transparent")
        btn_area.pack(side="left", padx=20, pady=14)

        self._btn_start = ctk.CTkButton(
            btn_area, text="▶  Iniciar Varredura",
            font=ctk.CTkFont(family=SANS, size=13, weight="bold"),
            fg_color=GREEN_GLOW, hover_color=GREEN_DIM,
            text_color="#ffffff", corner_radius=10, height=40, width=180,
            command=self._on_start,
        )
        self._btn_start.pack(side="left")

        self._btn_pause = ctk.CTkButton(
            btn_area, text="⏸  Pausar",
            font=ctk.CTkFont(family=SANS, size=13),
            fg_color=SURFACE, hover_color="#3a2a00",
            text_color=AMBER, border_color="#78350f", border_width=1,
            corner_radius=10, height=40, width=120, state="disabled",
            command=self._on_pause,
        )
        self._btn_pause.pack(side="left", padx=(10, 0))

        self._btn_stop = ctk.CTkButton(
            btn_area, text="■  Parar",
            font=ctk.CTkFont(family=SANS, size=13),
            fg_color=SURFACE, hover_color="#2a0a0a",
            text_color=RED, border_color="#7f1d1d", border_width=1,
            corner_radius=10, height=40, width=110, state="disabled",
            command=self._on_stop,
        )
        self._btn_stop.pack(side="left", padx=(10, 0))

        right = ctk.CTkFrame(self._email_footer_frame, fg_color="transparent")
        right.pack(side="right", padx=20, pady=14)

        self._lbl_counter = _label(right, "0 / 0  enviados",
                                    size=11, color=TEXT_MUTED, font=MONO)
        self._lbl_counter.pack(side="right", padx=(14, 0))

        self._lbl_pct = _label(right, "0%", size=11, color=TEXT_MUTED, font=MONO)
        self._lbl_pct.pack(side="right", padx=(0, 8))

        self._progress = ctk.CTkProgressBar(
            right, width=260, height=6,
            fg_color=CARD, progress_color=GREEN, corner_radius=4,
        )
        self._progress.set(0)
        self._progress.pack(side="right")

    # =========================================================================
    # ── WhatsApp page ─────────────────────────────────────────────────────────
    # =========================================================================

    def _build_wz_page(self, parent):
        self._build_wz_left(parent)
        self._build_wz_dashboard(parent)

    def _build_wz_left(self, parent):
        panel = ctk.CTkFrame(parent, fg_color=SURFACE, corner_radius=16,
                             border_color="#1a3a2a", border_width=1, width=420)
        panel.pack(side="left", fill="y", padx=(0, 14), pady=(0, 12))
        panel.pack_propagate(False)

        scroll = ctk.CTkScrollableFrame(panel, fg_color="transparent",
                                        scrollbar_button_color=BORDER2,
                                        scrollbar_button_hover_color=WZ_DIM)
        scroll.pack(fill="both", expand=True, padx=14, pady=12)

        _section_header(scroll, "EVOLUTION API", pad_top=4, accent=WZ_GREEN, dim=WZ_DIM)

        for label, key, ph, sec in [
            ("URL base",  "WZ_BASE_URL", "https://api.seuservidor.com", False),
            ("API Key",   "WZ_API_KEY",  "sua_api_key_aqui",           True),
            ("Instância", "WZ_INSTANCE", "minha-instancia",            False),
        ]:
            self._wz_entries[key] = _field_group(
                scroll, label,
                lambda ph=ph, sec=sec, key=key: _entry(
                    scroll, ph, sec, os.getenv(key, "")
                )
            )

        self._btn_wz_test_conn = ctk.CTkButton(
            scroll, text="Testar Conexão",
            font=ctk.CTkFont(family=SANS, size=11),
            fg_color=SURFACE, hover_color=WZ_DIM,
            text_color=WZ_GREEN, border_color=WZ_DIM, border_width=1,
            corner_radius=8, height=34,
            command=self._on_wz_test_connection,
        )
        self._btn_wz_test_conn.pack(fill="x", padx=2, pady=(10, 0))

        _section_header(scroll, "ARQUIVO EXCEL", accent=WZ_GREEN, dim=WZ_DIM)
        _label(scroll,
               "Colunas necessárias: NOME (ou SAVED_NAME) e TELEFONE (ou PHONE_NUMBER)",
               size=9, color=TEXT_MUTED
               ).pack(anchor="w", padx=2, pady=(0, 6))

        self._wz_excel_frame = _field_group(
            scroll, "Planilha de contatos",
            lambda: self._make_wz_excel_picker(scroll)
        )

        self._lbl_wz_contacts = _label(
            scroll, "Nenhum arquivo carregado", size=10, color=TEXT_MUTED, font=MONO
        )
        self._lbl_wz_contacts.pack(anchor="w", padx=2, pady=(4, 0))

        _section_header(scroll, "MENSAGEM PADRÃO", accent=WZ_GREEN, dim=WZ_DIM)
        _label(scroll,
               "Use {nome} para personalizar com o nome do contato.",
               size=9, color=TEXT_MUTED
               ).pack(anchor="w", padx=2, pady=(0, 6))

        self._wz_msg_body = ctk.CTkTextbox(
            scroll, fg_color=CARD, text_color=TEXT,
            font=ctk.CTkFont(family=SANS, size=12),
            corner_radius=10, border_color="#1a3a2a", border_width=1,
            wrap="word", height=220,
        )
        self._wz_msg_body.insert("1.0", DEFAULT_WZ_MSG)
        self._wz_msg_body.pack(fill="x", padx=2)

        self._lbl_wz_char = _label(
            scroll, f"{len(DEFAULT_WZ_MSG)} caracteres",
            size=9, color=TEXT_MUTED
        )
        self._lbl_wz_char.pack(anchor="e", padx=2, pady=(2, 0))
        self._wz_msg_body.bind("<KeyRelease>", self._wz_update_char_count)

    def _make_wz_excel_picker(self, parent):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        entry = _entry(frame, "Caminho do arquivo Excel",
                       default=os.getenv("WZ_EXCEL_PATH",
                                         str(Path(__file__).parent.parent
                                             / "Exportação contatos (1).xlsx")))
        entry.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(frame, text="···", width=38, height=36,
                      fg_color=CARD, hover_color=BORDER2,
                      text_color=TEXT_SEC, corner_radius=8,
                      command=lambda: self._wz_browse(entry)).pack(side="right", padx=(6, 0))
        return frame

    def _build_wz_dashboard(self, parent):
        panel = ctk.CTkFrame(parent, fg_color=SURFACE, corner_radius=16,
                             border_color="#1a3a2a", border_width=1)
        panel.pack(side="left", fill="both", expand=True, pady=(0, 12))

        title_bar = ctk.CTkFrame(panel, fg_color="transparent", height=44)
        title_bar.pack(fill="x", padx=16, pady=(14, 4))
        title_bar.pack_propagate(False)
        ctk.CTkLabel(
            title_bar, text="DASHBOARD  —  WHATSAPP",
            font=ctk.CTkFont(family=MONO, size=10, weight="bold"),
            text_color=WZ_GREEN,
        ).pack(side="left", pady=10)
        self._btn_wz_clear = ctk.CTkButton(
            title_bar, text="Limpar log", height=24, width=80,
            fg_color=CARD, hover_color=BORDER2,
            text_color=TEXT_MUTED, corner_radius=6,
            font=ctk.CTkFont(family=SANS, size=9),
            command=self._wz_clear_log,
        )
        self._btn_wz_clear.pack(side="right", pady=10)

        ctk.CTkFrame(panel, fg_color=BORDER2, height=1).pack(fill="x", padx=16)

        cards_row = ctk.CTkFrame(panel, fg_color="transparent")
        cards_row.pack(fill="x", padx=16, pady=(16, 8))

        self._lbl_wz_total   = _metric_card(cards_row, "TOTAL",    TEXT_SEC)
        self._lbl_wz_sent    = _metric_card(cards_row, "ENVIADOS",  WZ_GREEN)
        self._lbl_wz_failed  = _metric_card(cards_row, "FALHAS",    RED)
        self._lbl_wz_pending = _metric_card(cards_row, "PENDENTES", AMBER)

        prog_row = ctk.CTkFrame(panel, fg_color="transparent")
        prog_row.pack(fill="x", padx=16, pady=(4, 0))
        self._wz_progress = ctk.CTkProgressBar(
            prog_row, height=8,
            fg_color=CARD, progress_color=WZ_GREEN, corner_radius=4,
        )
        self._wz_progress.set(0)
        self._wz_progress.pack(side="left", fill="x", expand=True)
        self._lbl_wz_pct = _label(prog_row, "0%", size=10, color=TEXT_MUTED, font=MONO)
        self._lbl_wz_pct.pack(side="right", padx=(10, 0))

        ctk.CTkFrame(panel, fg_color=BORDER2, height=1).pack(fill="x", padx=16, pady=(10, 0))
        countdown_row = ctk.CTkFrame(panel, fg_color="transparent", height=52)
        countdown_row.pack(fill="x", padx=16)
        countdown_row.pack_propagate(False)

        _label(countdown_row, "⏱  Próximo envio em",
               size=10, color=TEXT_MUTED).pack(side="left", pady=14)
        self._lbl_wz_countdown = ctk.CTkLabel(
            countdown_row, text="--:--",
            font=ctk.CTkFont(family=MONO, size=22, weight="bold"),
            text_color=AMBER,
        )
        self._lbl_wz_countdown.pack(side="left", padx=(10, 0), pady=10)

        self._lbl_wz_status_inline = _label(
            countdown_row, "  AGUARDANDO", size=10, color=TEXT_MUTED, font=MONO
        )
        self._lbl_wz_status_inline.pack(side="right", pady=14)

        ctk.CTkFrame(panel, fg_color=BORDER2, height=1).pack(fill="x", padx=16)

        self._wz_txt_log = ctk.CTkTextbox(
            panel, fg_color=CONSOLE_BG, text_color=WZ_GREEN,
            font=ctk.CTkFont(family=MONO, size=11),
            corner_radius=10, border_color="#1a3a2a", border_width=1,
            wrap="word", state="disabled",
        )
        self._wz_txt_log.pack(fill="both", expand=True, padx=12, pady=12)

    # ── WZ Footer ─────────────────────────────────────────────────────────────
    def _build_wz_footer(self):
        ctk.CTkFrame(self._content_area, fg_color="#0d2a1a", height=1).pack(fill="x")

        self._wz_footer_frame = ctk.CTkFrame(
            self._content_area, fg_color=SURFACE, corner_radius=0, height=68
        )
        self._wz_footer_frame.pack_propagate(False)

        btn_area = ctk.CTkFrame(self._wz_footer_frame, fg_color="transparent")
        btn_area.pack(side="left", padx=20, pady=14)

        self._btn_wz_start = ctk.CTkButton(
            btn_area, text="▶  Iniciar Disparo WZ",
            font=ctk.CTkFont(family=SANS, size=13, weight="bold"),
            fg_color=WZ_GLOW, hover_color=WZ_DIM,
            text_color="#ffffff", corner_radius=10, height=40, width=200,
            command=self._on_wz_start,
        )
        self._btn_wz_start.pack(side="left")

        self._btn_wz_pause = ctk.CTkButton(
            btn_area, text="⏸  Pausar",
            font=ctk.CTkFont(family=SANS, size=13),
            fg_color=SURFACE, hover_color="#3a2a00",
            text_color=AMBER, border_color="#78350f", border_width=1,
            corner_radius=10, height=40, width=120, state="disabled",
            command=self._on_wz_pause,
        )
        self._btn_wz_pause.pack(side="left", padx=(10, 0))

        self._btn_wz_stop = ctk.CTkButton(
            btn_area, text="■  Parar",
            font=ctk.CTkFont(family=SANS, size=13),
            fg_color=SURFACE, hover_color="#2a0a0a",
            text_color=RED, border_color="#7f1d1d", border_width=1,
            corner_radius=10, height=40, width=110, state="disabled",
            command=self._on_wz_stop,
        )
        self._btn_wz_stop.pack(side="left", padx=(10, 0))

        right = ctk.CTkFrame(self._wz_footer_frame, fg_color="transparent")
        right.pack(side="right", padx=20, pady=14)

        self._lbl_wz_counter = _label(right, "0 / 0  enviados",
                                       size=11, color=TEXT_MUTED, font=MONO)
        self._lbl_wz_counter.pack(side="right", padx=(14, 0))

        self._lbl_wz_footer_pct = _label(right, "0%", size=11, color=TEXT_MUTED, font=MONO)
        self._lbl_wz_footer_pct.pack(side="right", padx=(0, 8))

        prog = ctk.CTkProgressBar(right, width=240, height=6,
                                   fg_color=CARD, progress_color=WZ_GREEN, corner_radius=4)
        prog.set(0)
        prog.pack(side="right")
        self._wz_footer_progress = prog

    # =========================================================================
    # ── Helpers (e-mail) ──────────────────────────────────────────────────────
    # =========================================================================

    def _update_eta(self):
        try:
            mn  = int(self._interval_min.get() or 30)
            mx  = int(self._interval_max.get() or 90)
            avg = (mn + mx) / 2
            total_s = avg * 100
            h = int(total_s // 3600)
            m = int((total_s % 3600) // 60)
            eta = f"{h}h {m:02d}min" if h else f"{m}min"
            self._lbl_eta.configure(
                text=f"100 e-mails ≈ {eta} com intervalo médio de {int(avg)}s"
            )
        except Exception:
            pass

    def _browse(self, entry):
        p = filedialog.askopenfilename(
            filetypes=[("Excel", "*.xlsx *.xls"), ("Todos", "*.*")]
        )
        if p:
            entry.delete(0, "end")
            entry.insert(0, p)

    def _clear_console(self):
        self._txt_log.configure(state="normal")
        self._txt_log.delete("1.0", "end")
        self._txt_log.configure(state="disabled")

    def _set_status(self, text, color):
        self._lbl_status.configure(text=f"  ●  {text}", text_color=color)

    def _update_progress(self, i, total, sent, errors):
        pct = int(i / total * 100) if total else 0
        self._progress.set(i / total if total else 0)
        self._lbl_pct.configure(text=f"{pct}%")
        self._lbl_counter.configure(text=f"{sent} / {total}  enviados")
        self._lbl_stats.configure(
            text=f"Total: {total}   Enviados: {sent}   Pulados: {self._email_skipped_count}   Erros: {errors}"
        )
        self._update_email_cards(
            total=total, sent=sent,
            failed=errors - self._email_no_email_count,
            no_email=self._email_no_email_count,
            skipped=self._email_skipped_count,
        )

    def _update_email_cards(self, total=0, sent=0, failed=0, no_email=0, bounced=0, skipped=0):
        self._lbl_em_total.configure(text=str(total))
        self._lbl_em_sent.configure(text=str(sent))
        self._lbl_em_failed.configure(text=str(max(0, failed)))
        self._lbl_em_skipped.configure(text=str(skipped))
        self._lbl_em_noemail.configure(text=str(no_email))
        self._lbl_em_bounced.configure(text=str(bounced))

    def _start_blink(self):
        self._blink_state = True

        def _blink():
            if self._blink_id is None:
                return
            color = GREEN if self._blink_state else GREEN_DIM
            self._lbl_status.configure(text_color=color)
            self._blink_state = not self._blink_state
            self._blink_id = self.after(600, _blink)

        self._blink_id = self.after(0, _blink)

    def _stop_blink(self):
        if self._blink_id:
            self.after_cancel(self._blink_id)
            self._blink_id = None

    # =========================================================================
    # ── Helpers (WhatsApp) ────────────────────────────────────────────────────
    # =========================================================================

    def _wz_update_char_count(self, _event=None):
        try:
            n = len(self._wz_msg_body.get("1.0", "end").strip())
            self._lbl_wz_char.configure(
                text=f"{n} caracteres",
                text_color=RED if n > 4096 else TEXT_MUTED,
            )
        except Exception:
            pass

    def _wz_browse(self, entry):
        p = filedialog.askopenfilename(
            filetypes=[("Excel", "*.xlsx *.xls"), ("Todos", "*.*")]
        )
        if p:
            entry.delete(0, "end")
            entry.insert(0, p)

    def _wz_clear_log(self):
        self._wz_txt_log.configure(state="normal")
        self._wz_txt_log.delete("1.0", "end")
        self._wz_txt_log.configure(state="disabled")

    def _wz_append_log(self, msg: str, level: str = "INFO"):
        colors = {
            "INFO": WZ_GREEN, "WARNING": AMBER,
            "ERROR": RED, "DEBUG": TEXT_MUTED,
        }
        color = colors.get(level.upper(), WZ_GREEN)
        import datetime as _dt
        ts   = _dt.datetime.now().strftime("%H:%M:%S")
        line = f"{ts}  {level:<8}  {msg}\n"

        self._wz_txt_log.configure(state="normal")
        self._wz_txt_log.insert("end", line, level)
        self._wz_txt_log.tag_config(level, foreground=color)
        self._wz_txt_log.configure(state="disabled")
        self._wz_txt_log.see("end")

    def _wz_update_stats(self, stats: dict):
        total   = stats.get("total",   0)
        sent    = stats.get("sent",    0)
        failed  = stats.get("failed",  0)
        pending = stats.get("pending", 0)

        self._lbl_wz_total.configure(text=str(total))
        self._lbl_wz_sent.configure(text=str(sent))
        self._lbl_wz_failed.configure(text=str(failed))
        self._lbl_wz_pending.configure(text=str(pending))

        done = sent + failed
        pct  = int(done / total * 100) if total else 0
        self._wz_progress.set(done / total if total else 0)
        self._wz_footer_progress.set(done / total if total else 0)
        self._lbl_wz_pct.configure(text=f"{pct}%")
        self._lbl_wz_footer_pct.configure(text=f"{pct}%")
        self._lbl_wz_counter.configure(text=f"{sent} / {total}  enviados")

    def _wz_update_countdown(self, remaining: int):
        if remaining <= 0:
            self._lbl_wz_countdown.configure(text="--:--", text_color=WZ_GREEN)
        else:
            mins, secs = divmod(remaining, 60)
            self._lbl_wz_countdown.configure(
                text=f"{mins:02d}:{secs:02d}", text_color=AMBER
            )

    def _wz_done(self, err: bool):
        self._btn_wz_start.configure(state="normal", text="▶  Iniciar Disparo WZ")
        self._btn_wz_stop.configure(state="disabled")
        self._btn_wz_pause.configure(state="disabled", text="⏸  Pausar")
        self._lbl_wz_countdown.configure(text="--:--", text_color=TEXT_MUTED)
        color  = RED if err else WZ_GREEN
        status = "ERRO" if err else "CONCLUÍDO"
        self._lbl_wz_status_inline.configure(text=f"  {status}", text_color=color)
        self._set_status(f"WZ {status}", color)
        if not err:
            self._wz_progress.set(1)
            self._wz_footer_progress.set(1)
            self._lbl_wz_pct.configure(text="100%")

    # =========================================================================
    # ── Button handlers (e-mail) ──────────────────────────────────────────────
    # =========================================================================

    def _on_start(self):
        try:
            interval_min = max(5,  int(self._interval_min.get() or 30))
            interval_max = max(10, int(self._interval_max.get() or 90))
        except ValueError:
            interval_min, interval_max = 30, 90

        if interval_min > interval_max:
            interval_min, interval_max = interval_max, interval_min

        config = {
            "url":          self._entries["SIGAWAY_URL"].get().strip(),
            "username":     self._entries["SIGAWAY_USER"].get().strip(),
            "password":     self._entries["SIGAWAY_PASS"].get().strip(),
            "subject":      self._entries["EMAIL_SUBJECT"].get().strip(),
            "cc":           self._entries["EMAIL_CC"].get().strip(),
            "excel_path":   self._excel_entry.winfo_children()[0].get().strip(),
            "email_body":   self._email_body.get("1.0", "end").strip(),
            "interval_min": interval_min,
            "interval_max": interval_max,
            "smtp_user":    self._entries["SMTP_USER"].get().strip(),
            "smtp_pass":    self._entries["SMTP_PASS"].get().strip(),
        }
        if not all([config["url"], config["username"], config["password"]]):
            self._log("Preencha URL, usuário e senha antes de iniciar.", "WARNING")
            return
        if not config["email_body"]:
            self._log("O corpo do e-mail está vazio. Preencha na aba E-MAIL.", "WARNING")
            return

        self._stop.clear()
        self._running.set()
        self._email_skipped_count = 0
        self._btn_start.configure(state="disabled")
        self._btn_pause.configure(state="normal", text="⏸  Pausar")
        self._btn_stop.configure(state="normal")
        self._btn_test.configure(state="disabled")
        self._set_status("EXECUTANDO", GREEN_BRIGHT)
        self._start_blink()
        self._progress.set(0)
        self._lbl_pct.configure(text="0%")
        self._update_email_cards()

        self._thread = threading.Thread(
            target=self._run_agent, args=(config,), daemon=True
        )
        self._thread.start()

    def _on_pause(self):
        if self._running.is_set():
            self._running.clear()
            self._btn_pause.configure(text="▶  Retomar")
            self._set_status("PAUSADO", AMBER)
            self._log("Campanha pausada. Clique em Retomar para continuar.", "WARNING")
        else:
            self._running.set()
            self._btn_pause.configure(text="⏸  Pausar")
            self._set_status("EXECUTANDO", GREEN_BRIGHT)
            self._log("Campanha retomada.", "INFO")

    def _on_stop(self):
        self._stop.set()
        self._running.set()  # desbloqueia thread pausada para que ela possa encerrar
        self._set_status("PARANDO...", AMBER)
        self._btn_stop.configure(state="disabled")
        self._btn_pause.configure(state="disabled")
        self._log("Solicitação de parada recebida.", "WARNING")

    def _on_clear_history(self):
        from tkinter import messagebox
        from execution.email_db import init_db, get_all_sent_emails
        init_db()
        sent = get_all_sent_emails()
        if not sent:
            messagebox.showinfo("Memória", "Nenhum envio registrado ainda.")
            return
        msg = (
            f"{len(sent)} e-mail(s) na memória.\n\n"
            "Deseja limpar o histórico?\n"
            "(os e-mails não serão desfeitos — só a memória do agente será apagada)"
        )
        if messagebox.askyesno("Limpar memória?", msg):
            from execution.email_db import clear_sent_history
            n = clear_sent_history()
            self._log(f"Memória limpa — {n} registros removidos.", "WARNING")
            self._do_refresh_metrics_history()

    def _on_send_test(self):
        email = self._test_email.get().strip()
        if not email or "@" not in email:
            self._log("Digite um e-mail válido no campo de teste.", "WARNING")
            return
        subject = self._entries["EMAIL_SUBJECT"].get().strip() or "Teste — Sigaway Agent"
        body    = self._email_body.get("1.0", "end").strip()
        self._btn_send_test.configure(state="disabled", text="Enviando...")
        self._log(f"Enviando e-mail de teste para {email}...")

        def _run():
            from enviar_email import send_email
            try:
                send_email(
                    to_email=email,
                    subject=f"[TESTE] {subject}",
                    corpo=body,
                    smtp_user=self._entries["SMTP_USER"].get().strip(),
                    smtp_password=self._entries["SMTP_PASS"].get().strip(),
                )
                self.after(0, lambda: self._log(
                    f"Teste enviado para {email}.", "INFO"
                ))
            except Exception as e:
                self.after(0, lambda: self._log(f"Falha: {e}", "ERROR"))
            finally:
                self.after(0, lambda: self._btn_send_test.configure(
                    state="normal", text="Enviar Teste"
                ))

        threading.Thread(target=_run, daemon=True).start()

    def _on_test_screenshot(self):
        nome = self._test_company.get().strip()
        if not nome:
            self._log("Digite o nome de uma empresa no campo de teste.", "WARNING")
            return
        url  = self._entries["SIGAWAY_URL"].get().strip()
        user = self._entries["SIGAWAY_USER"].get().strip()
        pwd  = self._entries["SIGAWAY_PASS"].get().strip()
        if not all([url, user, pwd]):
            self._log("Preencha as credenciais antes de testar.", "WARNING")
            return

        self._btn_test.configure(state="disabled", text="⏳  Capturando...")
        self._log(f"Iniciando captura de teste: '{nome}'")

        def _run():
            from execution.screenshot import run_capture
            import subprocess
            try:
                path = run_capture(url=url, username=user, password=pwd, cliente=nome)
                self.after(0, lambda: self._log(f"Screenshot salvo: {path}"))
                subprocess.Popen(["start", "", path], shell=True)
                self.after(0, lambda: self._log(
                    "Imagem aberta. Verifique se o conteúdo está correto.", "INFO"
                ))
            except Exception as e:
                self.after(0, lambda: self._log(f"Erro no teste: {e}", "ERROR"))
            finally:
                self.after(0, lambda: self._btn_test.configure(
                    state="normal", text="📷  Testar Screenshot"
                ))

        threading.Thread(target=_run, daemon=True).start()

    def _on_export_csv(self):
        cid = self._email_campaign_id
        if not cid:
            self._log("Nenhuma campanha registrada para exportar.", "WARNING")
            return
        p = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile=f"relatorio_{cid}.csv",
            title="Salvar relatório CSV",
        )
        if not p:
            return
        self._log(f"Exportando relatório da campanha {cid}...")

        def _run():
            from execution.email_db import export_csv
            try:
                path = export_csv(cid, p)
                import subprocess
                subprocess.Popen(["explorer", "/select,", path.replace("/", "\\")])
                self.after(0, lambda: self._log(f"CSV salvo: {path}", "INFO"))
            except Exception as e:
                self.after(0, lambda: self._log(f"Erro ao exportar: {e}", "ERROR"))

        threading.Thread(target=_run, daemon=True).start()

    def _get_entry_val(self, key: str) -> str:
        w = self._entries.get(key)
        return w.get().strip() if w else ""

    def _on_check_bounces(self):
        cid        = self._email_campaign_id
        tenant_id  = self._get_entry_val("GRAPH_TENANT_ID")
        client_id  = self._get_entry_val("GRAPH_CLIENT_ID")
        client_sec = self._get_entry_val("GRAPH_CLIENT_SECRET")
        sender     = self._get_entry_val("SMTP_USER")

        if not cid:
            self._log("Nenhuma campanha ativa para verificar retornos.", "WARNING")
            return
        if not all([tenant_id, client_id, client_sec, sender]):
            self._log("Preencha Graph API na aba CONFIG.", "WARNING")
            return

        self._btn_check_bounces.configure(state="disabled", text="Verificando...")
        self._log("Consultando caixa de entrada em busca de NDRs...")

        def _run():
            from execution.email_db import check_bounces_graph, get_campaign_stats
            try:
                bounced = check_bounces_graph(
                    tenant_id, client_id, client_sec, sender, cid
                )
                stats   = get_campaign_stats(cid)
                b_count = stats.get("bounced", 0)
                if bounced:
                    self.after(0, lambda: self._log(
                        f"Retornos: {', '.join(bounced)}", "WARNING"
                    ))
                else:
                    self.after(0, lambda: self._log("Nenhum retorno (NDR) encontrado.", "INFO"))
                self.after(0, lambda: self._lbl_em_bounced.configure(text=str(b_count)))
                self.after(0, self._refresh_metrics_history)
            except Exception as e:
                self.after(0, lambda: self._log(f"Erro: {e}", "ERROR"))
            finally:
                self.after(0, lambda: self._btn_check_bounces.configure(
                    state="normal", text="Verificar Retornos (NDR)"
                ))

        threading.Thread(target=_run, daemon=True).start()

    def _refresh_metrics_history(self):
        self.after(0, self._do_refresh_metrics_history)

    def _do_refresh_metrics_history(self):
        try:
            from execution.email_db import get_recent_campaigns, init_db
            init_db()
            campaigns = get_recent_campaigns(8)
            self._history_text.configure(state="normal")
            self._history_text.delete("1.0", "end")
            if not campaigns:
                self._history_text.insert("1.0", "Nenhuma campanha registrada ainda.\n")
            else:
                header = f"{'CAMPANHA':<34} {'TOTAL':>5} {'ENVIADOS':>8} {'FALHAS':>6} {'RETORNOS':>8}  STATUS\n"
                self._history_text.insert("end", header)
                self._history_text.insert("end", "─" * 80 + "\n")
                for c in campaigns:
                    cid_short = c["campaign_id"][-20:]
                    status = "Concluída" if c.get("completed_at") else "Em andamento"
                    line = (
                        f"{cid_short:<34}"
                        f" {c.get('total', 0):>5}"
                        f" {c.get('sent', 0):>8}"
                        f" {c.get('failed', 0):>6}"
                        f" {c.get('bounced', 0):>8}"
                        f"  {status}\n"
                    )
                    self._history_text.insert("end", line)
            self._history_text.configure(state="disabled")
        except Exception:
            pass

    def _on_test_outlook(self):
        self._btn_outlook.configure(state="disabled", text="Verificando...")
        self._log("Testando conexão com o Outlook...")

        def _run():
            from execution.email_sender import test_outlook_connection
            try:
                account = test_outlook_connection()
                self.after(0, lambda: self._log(
                    f"Outlook conectado — conta: {account}", "INFO"
                ))
            except Exception as e:
                self.after(0, lambda: self._log(f"Falha: {e}", "ERROR"))
            finally:
                self.after(0, lambda: self._btn_outlook.configure(
                    state="normal", text="📧  Testar Conexão Outlook"
                ))

        threading.Thread(target=_run, daemon=True).start()

    # =========================================================================
    # ── Button handlers (WhatsApp) ────────────────────────────────────────────
    # =========================================================================

    def _on_wz_test_connection(self):
        base_url = self._wz_entries["WZ_BASE_URL"].get().strip()
        api_key  = self._wz_entries["WZ_API_KEY"].get().strip()
        instance = self._wz_entries["WZ_INSTANCE"].get().strip()

        if not all([base_url, api_key, instance]):
            self._wz_append_log("Preencha URL, API Key e Instância.", "WARNING")
            return

        self._btn_wz_test_conn.configure(state="disabled", text="Verificando...")
        self._wz_append_log(f"Verificando instância '{instance}'...")

        def _run():
            from execution.whatsapp_sender import check_instance
            try:
                state = check_instance(base_url, api_key, instance)
                color = WZ_GREEN if state == "open" else AMBER
                msg   = f"Instância '{instance}': {state.upper()}"
                self.after(0, lambda m=msg, c=color: (
                    self._wz_append_log(m, "INFO" if state == "open" else "WARNING"),
                    self._lbl_wz_status_inline.configure(
                        text=f"  {state.upper()}", text_color=c
                    ),
                ))
            except Exception as e:
                self.after(0, lambda: self._wz_append_log(f"Falha: {e}", "ERROR"))
            finally:
                self.after(0, lambda: self._btn_wz_test_conn.configure(
                    state="normal", text="Testar Conexão"
                ))

        threading.Thread(target=_run, daemon=True).start()

    def _on_wz_start(self):
        base_url = self._wz_entries["WZ_BASE_URL"].get().strip()
        api_key  = self._wz_entries["WZ_API_KEY"].get().strip()
        instance = self._wz_entries["WZ_INSTANCE"].get().strip()
        message  = self._wz_msg_body.get("1.0", "end").strip()
        excel_path = self._wz_excel_frame.winfo_children()[0].get().strip()

        if not all([base_url, api_key, instance]):
            self._wz_append_log("Preencha URL, API Key e Instância.", "WARNING")
            return
        if not message:
            self._wz_append_log("A mensagem está vazia.", "WARNING")
            return
        if not excel_path:
            self._wz_append_log("Selecione o arquivo Excel.", "WARNING")
            return

        def _load_and_start():
            from execution.excel_reader import load_whatsapp_contacts
            from execution.whatsapp_queue import WhatsAppQueue
            try:
                self.after(0, lambda: self._wz_append_log("Carregando contatos do Excel..."))
                contacts = load_whatsapp_contacts(excel_path)
                if not contacts:
                    self.after(0, lambda: self._wz_append_log(
                        "Nenhum contato válido encontrado.", "ERROR"
                    ))
                    return

                count = len(contacts)
                self.after(0, lambda: (
                    self._wz_append_log(f"{count} contatos carregados."),
                    self._lbl_wz_contacts.configure(
                        text=f"{count} contatos · disparo imediato (sem intervalo)",
                        text_color=WZ_GREEN,
                    ),
                ))

                config = {
                    "base_url": base_url,
                    "api_key":  api_key,
                    "instance": instance,
                    "message":  message,
                }

                def _on_stats(s):
                    self.after(0, lambda: self._wz_update_stats(s))

                def _on_log(msg, level):
                    self.after(0, lambda m=msg, lv=level: self._wz_append_log(m, lv))

                def _on_done(err):
                    self.after(0, lambda: self._wz_done(err))

                def _on_tick(remaining):
                    self.after(0, lambda r=remaining: self._wz_update_countdown(r))

                self._wz_queue = WhatsAppQueue(
                    on_stats=_on_stats, on_log=_on_log,
                    on_done=_on_done, on_tick=_on_tick,
                )
                self._wz_queue.start(contacts, config)

                self.after(0, lambda: (
                    self._btn_wz_start.configure(state="disabled"),
                    self._btn_wz_stop.configure(state="normal"),
                    self._btn_wz_pause.configure(state="normal"),
                    self._lbl_wz_status_inline.configure(
                        text="  EXECUTANDO", text_color=WZ_GREEN
                    ),
                    self._set_status("WZ EXECUTANDO", WZ_GREEN),
                    self._wz_update_stats({
                        "total": count, "sent": 0,
                        "failed": 0, "pending": count,
                    }),
                ))

            except Exception as e:
                self.after(0, lambda: self._wz_append_log(f"Erro ao iniciar: {e}", "ERROR"))
                self.after(0, lambda: self._btn_wz_start.configure(
                    state="normal", text="▶  Iniciar Disparo WZ"
                ))

        self._btn_wz_start.configure(state="disabled", text="Carregando...")
        threading.Thread(target=_load_and_start, daemon=True).start()

    def _on_wz_pause(self):
        if not self._wz_queue:
            return
        if self._wz_queue.is_paused:
            self._wz_queue.resume()
            self._btn_wz_pause.configure(text="⏸  Pausar")
            self._lbl_wz_status_inline.configure(text="  EXECUTANDO", text_color=WZ_GREEN)
            self._set_status("WZ EXECUTANDO", WZ_GREEN)
        else:
            self._wz_queue.pause()
            self._btn_wz_pause.configure(text="▶  Retomar")
            self._lbl_wz_status_inline.configure(text="  PAUSADO", text_color=AMBER)
            self._set_status("WZ PAUSADO", AMBER)

    def _on_wz_stop(self):
        if self._wz_queue:
            self._wz_queue.stop()
        self._btn_wz_stop.configure(state="disabled")
        self._btn_wz_pause.configure(state="disabled", text="⏸  Pausar")
        self._lbl_wz_status_inline.configure(text="  PARANDO...", text_color=AMBER)
        self._set_status("WZ PARANDO...", AMBER)
        self._wz_append_log("Solicitação de parada recebida.", "WARNING")

    # =========================================================================
    # ── Agent runner (e-mail) ─────────────────────────────────────────────────
    # =========================================================================

    def _run_agent(self, cfg):
        import random
        import time
        from execution.excel_reader import load_recipients
        from execution.screenshot   import run_capture
        from execution.email_db     import (
            init_db, start_campaign, record_send,
            finish_campaign, get_campaign_stats, get_all_sent_emails,
        )
        from enviar_email import send_email

        init_db()
        campaign_id = (
            f"em_{_dt_now.now().strftime('%Y%m%d_%H%M%S')}_{_uuid_mod.uuid4().hex[:6]}"
        )
        self._email_campaign_id    = campaign_id
        self._email_no_email_count = 0
        self._email_skipped_count  = 0

        # Carrega memória de já-enviados se opção estiver ativa
        skip_sent = True
        try:
            skip_sent = self._chk_skip_sent.get() == 1
        except Exception:
            pass
        already_sent: set[str] = get_all_sent_emails() if skip_sent else set()
        if already_sent:
            self._log(f"Memória: {len(already_sent)} e-mail(s) já enviados serão pulados.")

        sent = errors = no_email = skipped = total = 0
        try:
            self._log("Carregando destinatários do Excel...")
            recs  = load_recipients(cfg["excel_path"])
            total = len(recs)
            self._log(f"{total} destinatários carregados.")
            start_campaign(campaign_id, cfg.get("excel_path", ""), total)
            self.after(0, lambda: (
                self._lbl_counter.configure(text=f"0 / {total}  enviados"),
                self._update_email_cards(total=total),
            ))
            self._refresh_metrics_history()

            for i, rec in enumerate(recs, 1):
                # ── Verificação de pausa ──────────────────────────────────────
                while not self._running.is_set():
                    if self._stop.is_set():
                        break
                    time.sleep(0.3)

                if self._stop.is_set():
                    self._log("Varredura interrompida.", "WARNING")
                    break

                cliente  = rec["cliente"]
                email    = rec["email"]
                cc_list  = rec.get("cc_list", [])
                global_cc = cfg["cc"].strip()
                if global_cc and global_cc not in cc_list:
                    cc_list = [global_cc] + cc_list
                cc = ", ".join(cc_list)

                self._log(f"[{i}/{total}]  {cliente}")

                if not email:
                    self._log(f"  Sem e-mail para '{cliente}'.", "WARNING")
                    no_email += 1
                    errors   += 1
                    self._email_no_email_count = no_email
                    record_send(campaign_id, cliente, "", "no_email")
                    self.after(0, self._update_progress, i, total, sent, errors)
                    continue

                # ── Memória anti-duplicata ────────────────────────────────────
                if skip_sent and email.lower() in already_sent:
                    skipped += 1
                    self._email_skipped_count = skipped
                    self._log(f"  Pulado — já enviado anteriormente: {email}", "WARNING")
                    record_send(campaign_id, cliente, email, "skipped")
                    self.after(0, self._update_progress, i, total, sent, errors)
                    continue

                try:
                    self._log("  Capturando screenshot...")
                    shot = run_capture(cfg["url"], cfg["username"], cfg["password"], cliente)

                    self._log(
                        f"  Enviando para {email}"
                        + (f"  CC: {cc}" if cc else "") + "..."
                    )
                    send_email(
                        to_email=email, subject=cfg["subject"],
                        corpo=cfg["email_body"], cc_email=cc,
                        screenshot_path=shot,
                        smtp_user=cfg["smtp_user"],
                        smtp_password=cfg["smtp_pass"],
                    )
                    sent += 1
                    already_sent.add(email.lower())  # atualiza memória local da sessão
                    record_send(campaign_id, cliente, email, "sent")
                    self._log("  ✓ E-mail enviado.")
                    try:
                        Path(shot).unlink(missing_ok=True)
                    except Exception:
                        pass
                except Exception as e:
                    errors += 1
                    record_send(campaign_id, cliente, email, "failed", str(e))
                    self._log(f"  Erro: {e}", "ERROR")

                self.after(0, self._update_progress, i, total, sent, errors)

                if i < total and not self._stop.is_set():
                    delay = random.randint(cfg["interval_min"], cfg["interval_max"])
                    self._log(f"  ⏱  Aguardando {delay}s...")
                    for _ in range(delay):
                        if self._stop.is_set():
                            break
                        self._running.wait()  # pausa também durante o intervalo
                        time.sleep(1)

            finish_campaign(campaign_id)
            self._log(
                f"Varredura concluída — Enviados: {sent}  Pulados: {skipped}  "
                f"Falhas: {errors - no_email}  Sem e-mail: {no_email}  Total: {total}"
            )
            self._refresh_metrics_history()
            self.after(0, self._done, False)

        except Exception as e:
            self._log(f"Erro crítico: {e}", "ERROR")
            self.after(0, self._done, True)

    def _done(self, err):
        self._stop_blink()
        self._running.set()
        self._btn_start.configure(state="normal")
        self._btn_pause.configure(state="disabled", text="⏸  Pausar")
        self._btn_stop.configure(state="disabled")
        self._btn_test.configure(state="normal")
        self._set_status("ERRO" if err else "CONCLUÍDO", RED if err else GREEN)
        if not err:
            self._progress.set(1)
            self._lbl_pct.configure(text="100%")

    # ── Log polling ───────────────────────────────────────────────────────────
    _COLORS = {
        "DEBUG":    TEXT_MUTED,
        "INFO":     CONSOLE_TXT,
        "WARNING":  AMBER,
        "ERROR":    RED,
        "CRITICAL": "#ff0000",
    }
    _FMT = logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s", "%H:%M:%S")

    def _poll(self):
        try:
            while True:
                rec   = self._queue.get_nowait()
                msg   = self._FMT.format(rec)
                color = self._COLORS.get(rec.levelname, CONSOLE_TXT)
                self._txt_log.configure(state="normal")
                self._txt_log.insert("end", msg + "\n", rec.levelname)
                self._txt_log.tag_config(rec.levelname, foreground=color)
                self._txt_log.configure(state="disabled")
                self._txt_log.see("end")
        except queue.Empty:
            pass
        self.after(80, self._poll)
