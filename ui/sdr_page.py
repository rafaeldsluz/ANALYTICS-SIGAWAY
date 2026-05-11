"""
SDR Agent Page — Centro de Controle do agente n8n (Carina SDR).
"""
from __future__ import annotations

import logging
import os
import threading
import tkinter as tk
import tkinter.ttk as ttk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

logger = logging.getLogger(__name__)

# ── Paleta (compartilhada com app.py) ─────────────────────────────────────────
BG         = "#0d1117"
SIDEBAR_BG = "#161b22"
SURFACE    = "#1c2128"
CARD       = "#21262d"
BORDER     = "#30363d"
BORDER2    = "#3d444d"
GREEN      = "#22c55e"
GREEN_DIM  = "#0a3622"
RED        = "#ef4444"
AMBER      = "#e3b341"
TEXT       = "#e6edf3"
TEXT_SEC   = "#8d96a0"
TEXT_MUTED = "#545d68"
CONSOLE_BG = "#0d1117"

SDR        = "#818cf8"   # indigo-400
SDR_DIM    = "#1e1b4b"
SDR_GLOW   = "#4338ca"
SDR_BRIGHT = "#a5b4fc"

MONO = "Consolas"
SANS = "Segoe UI"


def _lbl(parent, text, size=11, weight="normal", color=TEXT, font=SANS, **kw):
    return ctk.CTkLabel(
        parent, text=text,
        font=ctk.CTkFont(family=font, size=size, weight=weight),
        text_color=color, **kw,
    )


def _entry(parent, placeholder="", secret=False, default="", height=36):
    e = ctk.CTkEntry(
        parent, placeholder_text=placeholder,
        fg_color=CARD, border_color=BORDER2,
        text_color=TEXT, placeholder_text_color=TEXT_MUTED,
        show="*" if secret else "",
        height=height,
        font=ctk.CTkFont(family=SANS, size=11),
        corner_radius=8,
    )
    if default:
        e.insert(0, default)
    return e


def _section(parent, title: str, pad_top: int = 16):
    f = ctk.CTkFrame(parent, fg_color="transparent")
    f.pack(fill="x", padx=0, pady=(pad_top, 6))
    _lbl(f, title, size=9, weight="bold", color=SDR, font=MONO).pack(side="left")
    ctk.CTkFrame(f, fg_color=SDR_DIM, height=1).pack(
        side="left", fill="x", expand=True, padx=(8, 0), pady=(1, 0)
    )


def _field(parent, label: str, widget_factory):
    _lbl(parent, label, size=10, color=TEXT_SEC).pack(anchor="w", padx=2, pady=(8, 2))
    w = widget_factory()
    w.pack(fill="x", padx=2)
    return w


def _metric_card(parent, title: str, icon: str, color: str = SDR) -> ctk.CTkLabel:
    card = ctk.CTkFrame(
        parent, fg_color=CARD, corner_radius=12,
        border_color=BORDER2, border_width=1,
    )
    card.pack(side="left", fill="both", expand=True, padx=5)

    ctk.CTkLabel(
        card, text=icon,
        font=ctk.CTkFont(size=22),
        text_color=color,
    ).pack(pady=(14, 2))

    lbl_val = ctk.CTkLabel(
        card, text="0",
        font=ctk.CTkFont(family=MONO, size=32, weight="bold"),
        text_color=color,
    )
    lbl_val.pack(pady=(0, 2))

    _lbl(card, title, size=9, weight="bold", color=TEXT_MUTED, font=MONO).pack(pady=(0, 14))
    return lbl_val


# ── Treeview dark style ───────────────────────────────────────────────────────

def _apply_treeview_style():
    style = ttk.Style()
    try:
        style.theme_use("default")
    except Exception:
        pass
    style.configure(
        "SDR.Treeview",
        background=CARD,
        fieldbackground=CARD,
        foreground=TEXT,
        rowheight=26,
        borderwidth=0,
        font=("Consolas", 10),
    )
    style.configure(
        "SDR.Treeview.Heading",
        background=SURFACE,
        foreground=TEXT_MUTED,
        borderwidth=0,
        relief="flat",
        font=("Segoe UI", 9, "bold"),
    )
    style.map(
        "SDR.Treeview",
        background=[("selected", SDR_DIM)],
        foreground=[("selected", SDR_BRIGHT)],
    )
    style.layout("SDR.Treeview", [
        ("Treeview.treearea", {"sticky": "nswe"}),
    ])


# ── Main page ─────────────────────────────────────────────────────────────────

class SDRPage(ctk.CTkFrame):

    def __init__(self, master, log_callback=None, **kwargs):
        super().__init__(master, fg_color=BG, **kwargs)
        self._log = log_callback or (lambda msg, lv="INFO": None)
        self._workflow_active: bool | None = None
        self._poll_id = None

        _apply_treeview_style()
        self._build()
        self.after(1000, self._poll_stats)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self):
        self._build_left()
        self._build_dashboard()

    # ── Left panel ────────────────────────────────────────────────────────────

    def _build_left(self):
        panel = ctk.CTkFrame(
            self, fg_color=SURFACE, corner_radius=16,
            border_color=SDR_DIM, border_width=1, width=380,
        )
        panel.pack(side="left", fill="y", padx=(0, 14), pady=(0, 12))
        panel.pack_propagate(False)

        scroll = ctk.CTkScrollableFrame(
            panel, fg_color="transparent",
            scrollbar_button_color=BORDER2,
            scrollbar_button_hover_color=SDR_DIM,
        )
        scroll.pack(fill="both", expand=True, padx=14, pady=14)

        # ── n8n config ────────────────────────────────────────────────────────
        _section(scroll, "CONFIGURAÇÃO n8n", pad_top=4)

        self._e_n8n_url = _field(
            scroll, "URL do n8n",
            lambda: _entry(scroll, "http://192.168.x.x:5678",
                           default=os.getenv("N8N_URL", "")),
        )
        self._e_api_key = _field(
            scroll, "API Key",
            lambda: _entry(scroll, "••••••••", secret=True,
                           default=os.getenv("N8N_API_KEY", "")),
        )
        self._e_wf_id = _field(
            scroll, "Workflow ID  (número ou UUID)",
            lambda: _entry(scroll, "Ex: 26  ou  Bzt3s9QxIpjdUomX",
                           default=os.getenv("N8N_WORKFLOW_ID", "")),
        )

        ctk.CTkButton(
            scroll, text="Verificar Status",
            font=ctk.CTkFont(family=SANS, size=11),
            fg_color=SURFACE, hover_color=SDR_DIM,
            text_color=SDR, border_color=SDR_DIM, border_width=1,
            corner_radius=8, height=34,
            command=self._on_check_status,
        ).pack(fill="x", padx=2, pady=(10, 0))

        # Status card
        self._status_card = ctk.CTkFrame(
            scroll, fg_color=CARD, corner_radius=10,
            border_color=BORDER, border_width=1,
        )
        self._status_card.pack(fill="x", padx=2, pady=(10, 0))
        self._lbl_wf_status = _lbl(
            self._status_card, "● Não verificado",
            size=11, weight="bold", color=TEXT_MUTED, font=MONO,
        )
        self._lbl_wf_status.pack(padx=14, pady=10, anchor="w")
        self._lbl_wf_name = _lbl(
            self._status_card, "", size=9, color=TEXT_MUTED,
        )
        self._lbl_wf_name.pack(padx=14, pady=(0, 10), anchor="w")

        # ── Webhook receptor ──────────────────────────────────────────────────
        _section(scroll, "WEBHOOK RECEPTOR")

        self._e_port = _field(
            scroll, "Porta local",
            lambda: _entry(scroll, "5050", default=os.getenv("SDR_WEBHOOK_PORT", "5050")),
        )

        self._lbl_wh_url = ctk.CTkLabel(
            scroll, text=self._current_webhook_url(),
            font=ctk.CTkFont(family=MONO, size=10),
            text_color=SDR_BRIGHT, wraplength=320, justify="left",
        )
        self._lbl_wh_url.pack(anchor="w", padx=2, pady=(6, 0))

        ctk.CTkButton(
            scroll, text="Copiar URL",
            font=ctk.CTkFont(family=SANS, size=10),
            fg_color=CARD, hover_color=BORDER2,
            text_color=TEXT_SEC, corner_radius=8, height=30,
            command=self._copy_webhook_url,
        ).pack(anchor="w", padx=2, pady=(6, 0))

        _lbl(
            scroll,
            "Configure este URL como destino do nó HTTP Request no n8n"
            " para registrar conversas finalizadas.",
            size=9, color=TEXT_MUTED, wraplength=320, justify="left",
        ).pack(anchor="w", padx=2, pady=(8, 0))

        # ── Erros n8n ─────────────────────────────────────────────────────────
        _section(scroll, "ERROS DE EXECUÇÃO")

        ctk.CTkButton(
            scroll, text="Buscar Erros Recentes",
            font=ctk.CTkFont(family=SANS, size=11),
            fg_color=SURFACE, hover_color="#2a0a0a",
            text_color=RED, border_color="#7f1d1d", border_width=1,
            corner_radius=8, height=34,
            command=self._on_fetch_errors,
        ).pack(fill="x", padx=2, pady=(0, 8))

    def _current_webhook_url(self) -> str:
        try:
            from sdr.server import get_webhook_url
            return get_webhook_url()
        except Exception:
            return "http://<ip-local>:5050/sdr/webhook"

    # ── Right dashboard ───────────────────────────────────────────────────────

    def _build_dashboard(self):
        panel = ctk.CTkFrame(
            self, fg_color=SURFACE, corner_radius=16,
            border_color=SDR_DIM, border_width=1,
        )
        panel.pack(side="left", fill="both", expand=True, pady=(0, 12))

        # Title bar
        title_bar = ctk.CTkFrame(panel, fg_color="transparent", height=44)
        title_bar.pack(fill="x", padx=16, pady=(14, 4))
        title_bar.pack_propagate(False)

        _lbl(title_bar, "TORRE DE CONTROLE  —  SDR AGENT",
             size=10, weight="bold", color=SDR, font=MONO).pack(side="left", pady=10)

        self._btn_clear_log = ctk.CTkButton(
            title_bar, text="Limpar log", height=24, width=90,
            fg_color=CARD, hover_color=BORDER2,
            text_color=TEXT_MUTED, corner_radius=6,
            font=ctk.CTkFont(family=SANS, size=9),
            command=self._clear_log,
        )
        self._btn_clear_log.pack(side="right", pady=10)

        ctk.CTkButton(
            title_bar, text="Exportar CSV", height=24, width=100,
            fg_color=SDR_DIM, hover_color=SDR_GLOW,
            text_color=SDR_BRIGHT, corner_radius=6,
            font=ctk.CTkFont(family=SANS, size=9),
            command=self._export_csv,
        ).pack(side="right", pady=10, padx=(0, 8))

        ctk.CTkFrame(panel, fg_color=BORDER, height=1).pack(fill="x", padx=16)

        # ── Metric cards ──────────────────────────────────────────────────────
        cards = ctk.CTkFrame(panel, fg_color="transparent")
        cards.pack(fill="x", padx=16, pady=(16, 8))

        self._lbl_conversations = _metric_card(cards, "CONVERSAS\nINICIADAS", "💬", SDR)
        self._lbl_errors        = _metric_card(cards, "ERROS DE\nEXECUÇÃO",  "⚠️", RED)
        self._lbl_meetings      = _metric_card(cards, "REUNIÕES\nAGENDADAS",  "📅", GREEN)

        ctk.CTkFrame(panel, fg_color=BORDER2, height=1).pack(fill="x", padx=16, pady=(8, 0))

        # ── Log table ─────────────────────────────────────────────────────────
        log_hdr = ctk.CTkFrame(panel, fg_color="transparent", height=36)
        log_hdr.pack(fill="x", padx=16, pady=(10, 4))
        log_hdr.pack_propagate(False)
        _lbl(log_hdr, "HISTÓRICO DE MENSAGENS",
             size=9, weight="bold", color=TEXT_MUTED, font=MONO).pack(side="left", pady=8)

        table_frame = ctk.CTkFrame(panel, fg_color=CARD, corner_radius=10)
        table_frame.pack(fill="both", expand=True, padx=16, pady=(0, 14))

        cols = ("hora", "contato", "dir", "tipo", "mensagem", "status")
        self._tree = ttk.Treeview(
            table_frame, columns=cols, show="headings",
            style="SDR.Treeview", selectmode="browse",
        )

        col_cfg = [
            ("hora",     "HORA",     85,  False),
            ("contato",  "CONTATO",  140, False),
            ("dir",      "DIR",      45,  False),
            ("tipo",     "TIPO",     75,  False),
            ("mensagem", "MENSAGEM", 0,   True),
            ("status",   "STATUS",   95,  False),
        ]
        for cid, heading, width, stretch in col_cfg:
            self._tree.heading(cid, text=heading, anchor="w")
            self._tree.column(
                cid, width=width, minwidth=45 if not stretch else 120,
                stretch=stretch, anchor="w",
            )

        # Tags for row colors
        self._tree.tag_configure("converted", foreground=GREEN)
        self._tree.tag_configure("error",     foreground=RED)
        self._tree.tag_configure("bot",       foreground=SDR_BRIGHT)
        self._tree.tag_configure("lead",      foreground=TEXT)

        vsb = ttk.Scrollbar(table_frame, orient="vertical",   command=self._tree.yview)
        hsb = ttk.Scrollbar(table_frame, orient="horizontal",  command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        hsb.pack(side="bottom", fill="x")
        vsb.pack(side="right",  fill="y")
        self._tree.pack(side="left", fill="both", expand=True)

    # ── Handlers ──────────────────────────────────────────────────────────────

    def _on_check_status(self):
        url = self._e_n8n_url.get().strip()
        key = self._e_api_key.get().strip()
        wid = self._e_wf_id.get().strip()

        if not all([url, wid]):
            self._log("Preencha URL do n8n e Workflow ID antes de verificar.", "WARNING")
            return

        self._lbl_wf_status.configure(text="● Verificando...", text_color=AMBER)

        def _run():
            from sdr.server import get_workflow_status
            try:
                info = get_workflow_status(url, wid, key)
                active = info.get("active", False)
                name   = info.get("name", wid)
                color  = GREEN if active else RED
                status = "ATIVO" if active else "PAUSADO"
                self._workflow_active = active
                self.after(0, lambda: self._lbl_wf_status.configure(
                    text=f"● {status}", text_color=color,
                ))
                self.after(0, lambda: self._lbl_wf_name.configure(text=name))
                self._log(f"[SDR] Workflow '{name}': {status}", "INFO")
            except Exception as e:
                self.after(0, lambda: self._lbl_wf_status.configure(
                    text="● Erro de conexão", text_color=RED,
                ))
                self._log(f"[SDR] Erro ao verificar status: {e}", "ERROR")

        threading.Thread(target=_run, daemon=True).start()

    def toggle_agent(self):
        """Chamado pelo botão Ativar/Pausar no footer."""
        url = self._e_n8n_url.get().strip()
        key = self._e_api_key.get().strip()
        wid = self._e_wf_id.get().strip()

        if not all([url, wid]):
            self._log("Preencha URL do n8n e Workflow ID para controlar o agente.", "WARNING")
            return

        target = not (self._workflow_active or False)

        def _run():
            from sdr.server import set_workflow_active
            try:
                active = set_workflow_active(url, wid, key, target)
                self._workflow_active = active
                color  = GREEN if active else RED
                status = "ATIVO" if active else "PAUSADO"
                self.after(0, lambda: self._lbl_wf_status.configure(
                    text=f"● {status}", text_color=color,
                ))
                action = "ativado" if active else "pausado"
                self._log(f"[SDR] Agente {action} com sucesso.", "INFO")
                if hasattr(self, "_on_agent_toggle"):
                    self.after(0, lambda: self._on_agent_toggle(active))
            except Exception as e:
                self._log(f"[SDR] Erro ao alterar status: {e}", "ERROR")

        threading.Thread(target=_run, daemon=True).start()

    def _on_fetch_errors(self):
        url = self._e_n8n_url.get().strip()
        key = self._e_api_key.get().strip()
        wid = self._e_wf_id.get().strip()

        if not all([url, wid]):
            self._log("Preencha URL e Workflow ID para buscar erros.", "WARNING")
            return

        def _run():
            from sdr.server import get_execution_errors
            from sdr.db import record_error
            try:
                execs = get_execution_errors(url, wid, key, limit=20)
                for ex in execs:
                    record_error(
                        workflow_id  = wid,
                        execution_id = ex.get("id", ""),
                        node_name    = ex.get("stoppedAt", ""),
                        error_msg    = str(ex.get("data", {}).get("resultData", {})
                                           .get("error", {}).get("message", "Desconhecido")),
                    )
                self._log(f"[SDR] {len(execs)} execuções com erro importadas.", "WARNING" if execs else "INFO")
                self.after(0, self.refresh_stats)
            except Exception as e:
                self._log(f"[SDR] Erro ao buscar execuções: {e}", "ERROR")

        threading.Thread(target=_run, daemon=True).start()

    def _copy_webhook_url(self):
        url = self._current_webhook_url()
        self.clipboard_clear()
        self.clipboard_append(url)
        self._log(f"[SDR] URL copiada: {url}", "INFO")

    def _clear_log(self):
        for item in self._tree.get_children():
            self._tree.delete(item)

    def _export_csv(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile=f"sdr_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            title="Exportar histórico SDR",
        )
        if not path:
            return

        def _run():
            from sdr.db import get_recent_messages
            import csv
            rows = get_recent_messages(5000)
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=rows[0].keys() if rows else [])
                w.writeheader()
                w.writerows(rows)
            self._log(f"[SDR] CSV exportado: {path}", "INFO")

        threading.Thread(target=_run, daemon=True).start()

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh_stats(self):
        """Atualiza cards e tabela — seguro chamar de qualquer thread via after()."""
        self.after(0, self._do_refresh)

    def _do_refresh(self):
        try:
            from sdr.db import get_stats, get_recent_messages
            stats = get_stats()
            self._lbl_conversations.configure(text=str(stats["conversations"]))
            self._lbl_errors.configure(text=str(stats["errors"]))
            self._lbl_meetings.configure(text=str(stats["meetings"]))

            rows = get_recent_messages(300)
            # Repopulate table (insert new rows at top without full clear
            # to avoid flicker — just prepend missing ones)
            existing = set(self._tree.get_children())
            if len(existing) > 250:
                # Keep table bounded
                for iid in list(self._tree.get_children())[-50:]:
                    self._tree.delete(iid)

            for row in rows[:50]:
                hora    = row.get("created_at", "")[-8:] if row.get("created_at") else ""
                nome    = (row.get("nome") or "")[:20]
                dire    = "→" if row.get("direction") == "out" else "←"
                tipo    = row.get("msg_type", "text")[:10]
                content = (row.get("content") or "")[:120].replace("\n", " ")
                kw      = row.get("keyword_match", "")
                status  = "QUALIFICADO" if kw else ("BOT" if row.get("direction") == "out" else "LEAD")

                tag = "converted" if kw else ("bot" if row.get("direction") == "out" else "lead")

                self._tree.insert(
                    "", 0,
                    values=(hora, nome, dire, tipo, content, status),
                    tags=(tag,),
                )

        except Exception as e:
            logger.debug(f"SDR refresh error: {e}")

    def _poll_stats(self):
        self._do_refresh()
        self._poll_id = self.after(5000, self._poll_stats)
