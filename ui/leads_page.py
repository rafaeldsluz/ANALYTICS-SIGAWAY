"""
Leads Page — Extração de leads qualificados por CNAE.
Fontes gratuitas: Brasil.io (descoberta) + CNPJ.ws (enriquecimento).
"""
import os
import threading
import time
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

# ── Paleta ────────────────────────────────────────────────────────────────────
BG         = "#0d1117"
SURFACE    = "#1c2128"
CARD       = "#21262d"
BORDER     = "#30363d"
BORDER2    = "#3d444d"
GREEN      = "#22c55e"
GREEN_DIM  = "#0a3622"
GREEN_GLOW = "#15803d"
RED        = "#ef4444"
AMBER      = "#e3b341"
TEXT       = "#e6edf3"
TEXT_SEC   = "#8d96a0"
TEXT_MUTED = "#545d68"
CONSOLE_BG = "#0d1117"
MONO       = "Consolas"
SANS       = "Segoe UI"

LEADS       = "#38bdf8"
LEADS_DIM   = "#0c2840"
LEADS_GLOW  = "#0284c7"
LEADS_BRIGHT = "#7dd3fc"

# ── CNAEs de referência rápida ────────────────────────────────────────────────
COMMON_CNAES = [
    ("4930201", "Transporte rodoviário de cargas – geral"),
    ("4930202", "Transporte rodoviário – carga pesada"),
    ("5229001", "Serviços de apoio ao transporte"),
    ("4921301", "Transporte coletivo de passageiros"),
    ("6201501", "Desenvolvimento de softwares customizados"),
    ("6202300", "Desenvolvimento de softwares – pacote"),
    ("4610100", "Representantes comerciais e agentes"),
    ("4711301", "Comércio varejista – hipermercados"),
    ("4731800", "Comércio varejista de combustíveis"),
    ("5611201", "Restaurantes e similares"),
    ("8621601", "UTI móvel – serviços médicos"),
    ("8599601", "Ensino de esportes e lazer"),
    ("7490101", "Serviços de tradução e interpretação"),
    ("4120400", "Construção de edifícios"),
    ("4399101", "Administração de obras de construção"),
]


class LeadsPage(ctk.CTkFrame):

    def __init__(self, parent, log_callback=None, **kwargs):
        super().__init__(parent, fg_color=BG, **kwargs)
        self._log_cb     = log_callback or (lambda m, lv="INFO": None)
        self._thread     = None
        self._stop_event = threading.Event()
        self._cnae_rows: list[tuple[ctk.CTkFrame, ctk.CTkEntry]] = []

        self._build()

    # ── Build ─────────────────────────────────────────────────────────────────
    def _build(self):
        self._build_left()
        self._build_right()

    # ═════════════════════════════════════════════════════════════════════════
    # LEFT PANEL — configuração
    # ═════════════════════════════════════════════════════════════════════════
    def _build_left(self):
        panel = ctk.CTkFrame(
            self, fg_color=SURFACE, corner_radius=16,
            border_color=LEADS_DIM, border_width=1, width=400,
        )
        panel.pack(side="left", fill="y", padx=(0, 14), pady=(0, 12))
        panel.pack_propagate(False)

        scroll = ctk.CTkScrollableFrame(
            panel, fg_color="transparent",
            scrollbar_button_color=BORDER2,
            scrollbar_button_hover_color=LEADS_DIM,
        )
        scroll.pack(fill="both", expand=True, padx=14, pady=12)

        self._sec_api(scroll)
        self._sec_filters(scroll)
        self._sec_options(scroll)
        self._sec_output(scroll)
        self._sec_cnae_ref(scroll)

    # ── Seção: API token ──────────────────────────────────────────────────────
    def _sec_api(self, p):
        self._sh(p, "BRASIL.IO  —  TOKEN GRATUITO", pad_top=4)

        self._lbl(p,
            "Crie sua conta em brasil.io e acesse /auth/tokens-api/ para gerar o token.",
            size=9, color=TEXT_MUTED, wraplength=340,
        ).pack(anchor="w", padx=2, pady=(0, 6))

        self._fl(p, "API Token (gratuito)")
        self._token_entry = self._entry(
            p, "Cole o token aqui",
            default=os.getenv("BRASILIO_TOKEN", ""), secret=True,
        )
        self._token_entry.pack(fill="x", padx=2)

    # ── Seção: Filtros ────────────────────────────────────────────────────────
    def _sec_filters(self, p):
        self._sh(p, "FILTROS DE BUSCA")

        self._fl(p, "Código(s) CNAE")
        self._cnae_container = ctk.CTkFrame(p, fg_color="transparent")
        self._cnae_container.pack(fill="x", padx=2)
        self._add_cnae_row()

        ctk.CTkButton(
            p, text="+ Adicionar CNAE",
            font=ctk.CTkFont(family=SANS, size=10),
            fg_color="transparent", hover_color=LEADS_DIM,
            text_color=LEADS, corner_radius=6, height=26,
            border_color=LEADS_DIM, border_width=1,
            command=self._add_cnae_row,
        ).pack(anchor="w", padx=2, pady=(4, 0))

        self._fl(p, "Estado (UF)")
        self._uf_entry = self._entry(p, "Ex: SC, SP, RS  (vazio = Brasil todo)")
        self._uf_entry.pack(fill="x", padx=2)

        self._fl(p, "Município (opcional)")
        self._mun_entry = self._entry(p, "Ex: CRICIUMA, FLORIANOPOLIS")
        self._mun_entry.pack(fill="x", padx=2)

        self._fl(p, "Máx. resultados por CNAE")
        row = ctk.CTkFrame(p, fg_color="transparent")
        row.pack(fill="x", padx=2)
        self._max_entry = ctk.CTkEntry(
            row, width=80, height=34, fg_color=CARD,
            border_color=BORDER2, text_color=TEXT, corner_radius=8,
            font=ctk.CTkFont(family=MONO, size=11),
        )
        self._max_entry.insert(0, "200")
        self._max_entry.pack(side="left")
        self._lbl(row, " empresas / CNAE", size=10, color=TEXT_MUTED).pack(side="left", padx=6)

    def _add_cnae_row(self):
        row = ctk.CTkFrame(self._cnae_container, fg_color="transparent")
        row.pack(fill="x", pady=(0, 4))

        entry = ctk.CTkEntry(
            row, placeholder_text="Ex: 4930201",
            fg_color=CARD, border_color=BORDER2,
            text_color=TEXT, placeholder_text_color=TEXT_MUTED,
            height=34, corner_radius=8,
            font=ctk.CTkFont(family=MONO, size=11),
        )
        entry.pack(side="left", fill="x", expand=True)

        if self._cnae_rows:
            ctk.CTkButton(
                row, text="✕", width=30, height=34,
                fg_color=CARD, hover_color="#2a0a0a",
                text_color=TEXT_MUTED, corner_radius=8,
                command=lambda r=row, e=entry: self._remove_cnae_row(r, e),
            ).pack(side="right", padx=(4, 0))

        self._cnae_rows.append((row, entry))

    def _remove_cnae_row(self, row, entry):
        self._cnae_rows = [(r, e) for r, e in self._cnae_rows if e is not entry]
        row.destroy()

    # ── Seção: Opções ─────────────────────────────────────────────────────────
    def _sec_options(self, p):
        self._sh(p, "OPÇÕES DE EXTRAÇÃO")

        self._chk_enrich = self._chk(
            p, "Enriquecer via CNPJ.ws  (e-mail, telefone, sócios, CNAE desc.)"
        )
        self._chk_enrich.select()

        self._chk_only_email = self._chk(p, "Exportar apenas leads com e-mail")
        self._chk_only_phone = self._chk(p, "Exportar apenas leads com telefone")

    # ── Seção: Saída ──────────────────────────────────────────────────────────
    def _sec_output(self, p):
        self._sh(p, "ARQUIVO DE SAÍDA")

        self._fl(p, "Caminho do arquivo .xlsx")
        frame = ctk.CTkFrame(p, fg_color="transparent")
        frame.pack(fill="x", padx=2)

        self._out_entry = self._entry(
            frame, default=str(Path.home() / "leads_cnae.xlsx")
        )
        self._out_entry.pack(side="left", fill="x", expand=True)

        ctk.CTkButton(
            frame, text="···", width=38, height=36,
            fg_color=CARD, hover_color=BORDER2,
            text_color=TEXT_SEC, corner_radius=8,
            command=self._browse_output,
        ).pack(side="right", padx=(6, 0))

        self._fl(p, "Formato de exportação")
        self._fmt_var = ctk.StringVar(value="emkt")
        fmt_row = ctk.CTkFrame(p, fg_color="transparent")
        fmt_row.pack(fill="x", padx=2)

        for val, txt in [("emkt", "Compatível com E-MKT Agent"), ("full", "Completo (todos campos)")]:
            ctk.CTkRadioButton(
                fmt_row, text=txt, variable=self._fmt_var, value=val,
                font=ctk.CTkFont(family=SANS, size=11),
                text_color=TEXT, fg_color=LEADS_GLOW, hover_color=LEADS_DIM,
            ).pack(side="left", padx=(0, 12))

    # ── Seção: CNAEs de referência ────────────────────────────────────────────
    def _sec_cnae_ref(self, p):
        self._sh(p, "REFERÊNCIA  —  CNAEs COMUNS")
        self._lbl(p, "Clique para copiar o código para o campo CNAE.",
                  size=9, color=TEXT_MUTED).pack(anchor="w", padx=2, pady=(0, 6))

        for code, desc in COMMON_CNAES:
            card = ctk.CTkFrame(p, fg_color=CARD, corner_radius=6, cursor="hand2")
            card.pack(fill="x", padx=2, pady=2)
            card.bind("<Button-1>", lambda e, c=code: self._paste_cnae(c))

            lbl_code = ctk.CTkLabel(
                card, text=code,
                font=ctk.CTkFont(family=MONO, size=10, weight="bold"),
                text_color=LEADS, width=72, anchor="w", cursor="hand2",
            )
            lbl_code.pack(side="left", padx=(10, 4), pady=6)
            lbl_code.bind("<Button-1>", lambda e, c=code: self._paste_cnae(c))

            lbl_desc = ctk.CTkLabel(
                card, text=desc,
                font=ctk.CTkFont(family=SANS, size=9),
                text_color=TEXT_SEC, anchor="w", cursor="hand2",
            )
            lbl_desc.pack(side="left", padx=(0, 10), pady=6)
            lbl_desc.bind("<Button-1>", lambda e, c=code: self._paste_cnae(c))

    def _paste_cnae(self, code: str):
        for _, entry in self._cnae_rows:
            if not entry.get().strip():
                entry.delete(0, "end")
                entry.insert(0, code)
                return
        self._add_cnae_row()
        if self._cnae_rows:
            self._cnae_rows[-1][1].insert(0, code)

    def _browse_output(self):
        p = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx"), ("CSV", "*.csv"), ("Todos", "*.*")],
            initialfile="leads_cnae.xlsx",
            title="Salvar leads",
        )
        if p:
            self._out_entry.delete(0, "end")
            self._out_entry.insert(0, p)

    # ═════════════════════════════════════════════════════════════════════════
    # RIGHT PANEL — dashboard + log
    # ═════════════════════════════════════════════════════════════════════════
    def _build_right(self):
        panel = ctk.CTkFrame(
            self, fg_color=SURFACE, corner_radius=16,
            border_color=LEADS_DIM, border_width=1,
        )
        panel.pack(side="left", fill="both", expand=True, pady=(0, 12))

        # Title bar
        title_bar = ctk.CTkFrame(panel, fg_color="transparent", height=44)
        title_bar.pack(fill="x", padx=16, pady=(14, 4))
        title_bar.pack_propagate(False)

        ctk.CTkLabel(
            title_bar, text="EXTRATOR DE LEADS  —  CNAE  /  CNPJ.ws",
            font=ctk.CTkFont(family=MONO, size=10, weight="bold"),
            text_color=LEADS,
        ).pack(side="left", pady=10)

        ctk.CTkButton(
            title_bar, text="Limpar log", height=24, width=80,
            fg_color=CARD, hover_color=BORDER2,
            text_color=TEXT_MUTED, corner_radius=6,
            font=ctk.CTkFont(family=SANS, size=9),
            command=self._clear_log,
        ).pack(side="right", pady=10)

        ctk.CTkButton(
            title_bar, text="Limpar base", height=24, width=90,
            fg_color=CARD, hover_color="#2a0a0a",
            text_color=RED, corner_radius=6,
            font=ctk.CTkFont(family=SANS, size=9),
            command=self._on_clear_db,
        ).pack(side="right", pady=10, padx=(0, 8))

        ctk.CTkFrame(panel, fg_color=BORDER2, height=1).pack(fill="x", padx=16)

        # Metric cards
        cards_row = ctk.CTkFrame(panel, fg_color="transparent")
        cards_row.pack(fill="x", padx=16, pady=(16, 8))

        self._lbl_total   = self._metric_card(cards_row, "TOTAL",     TEXT_SEC)
        self._lbl_email   = self._metric_card(cards_row, "COM E-MAIL", LEADS)
        self._lbl_phone   = self._metric_card(cards_row, "COM TEL.",   GREEN)
        self._lbl_no_cont = self._metric_card(cards_row, "SEM CONTATO", AMBER)

        # Progress
        prog_row = ctk.CTkFrame(panel, fg_color="transparent")
        prog_row.pack(fill="x", padx=16, pady=(0, 4))

        self._progress = ctk.CTkProgressBar(
            prog_row, height=6,
            fg_color=CARD, progress_color=LEADS, corner_radius=4,
        )
        self._progress.set(0)
        self._progress.pack(side="left", fill="x", expand=True)

        self._lbl_pct = ctk.CTkLabel(
            prog_row, text="0%",
            font=ctk.CTkFont(family=MONO, size=10),
            text_color=TEXT_MUTED,
        )
        self._lbl_pct.pack(side="right", padx=(10, 0))

        ctk.CTkFrame(panel, fg_color=BORDER2, height=1).pack(fill="x", padx=16, pady=(4, 0))

        # Console
        self._txt_log = ctk.CTkTextbox(
            panel, fg_color=CONSOLE_BG,
            font=ctk.CTkFont(family=MONO, size=11),
            corner_radius=10, border_color=LEADS_DIM, border_width=1,
            wrap="word", state="disabled",
        )
        self._txt_log.pack(fill="both", expand=True, padx=12, pady=12)

        for tag, color in [
            ("INFO",    LEADS),
            ("WARNING", AMBER),
            ("ERROR",   RED),
            ("SUCCESS", GREEN),
            ("DIM",     TEXT_MUTED),
        ]:
            self._txt_log.tag_config(tag, foreground=color)

        # Footer
        self._build_footer(panel)

    def _metric_card(self, parent, title, color):
        card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=12,
                            border_color=BORDER2, border_width=1)
        card.pack(side="left", fill="both", expand=True, padx=5)
        lbl = ctk.CTkLabel(
            card, text="0",
            font=ctk.CTkFont(family=MONO, size=28, weight="bold"),
            text_color=color,
        )
        lbl.pack(pady=(14, 2))
        ctk.CTkLabel(
            card, text=title,
            font=ctk.CTkFont(family=MONO, size=9, weight="bold"),
            text_color=TEXT_MUTED,
        ).pack(pady=(0, 12))
        return lbl

    def _build_footer(self, parent):
        footer = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=0, height=64)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)

        btn_area = ctk.CTkFrame(footer, fg_color="transparent")
        btn_area.pack(side="left", padx=16, pady=12)

        self._btn_start = ctk.CTkButton(
            btn_area, text="▶  Iniciar Extração",
            font=ctk.CTkFont(family=SANS, size=13, weight="bold"),
            fg_color=LEADS_GLOW, hover_color=LEADS_DIM,
            text_color="#ffffff", corner_radius=10, height=40, width=180,
            command=self._on_start,
        )
        self._btn_start.pack(side="left")

        self._btn_stop = ctk.CTkButton(
            btn_area, text="■  Parar",
            font=ctk.CTkFont(family=SANS, size=13),
            fg_color=SURFACE, hover_color="#2a0a0a",
            text_color=RED, border_color="#7f1d1d", border_width=1,
            corner_radius=10, height=40, width=110, state="disabled",
            command=self._on_stop,
        )
        self._btn_stop.pack(side="left", padx=(10, 0))

        self._btn_export = ctk.CTkButton(
            btn_area, text="📥  Exportar Excel",
            font=ctk.CTkFont(family=SANS, size=12),
            fg_color=SURFACE, hover_color=GREEN_DIM,
            text_color=GREEN, border_color=GREEN_DIM, border_width=1,
            corner_radius=10, height=40, width=155,
            command=self._on_export,
        )
        self._btn_export.pack(side="left", padx=(10, 0))

        right = ctk.CTkFrame(footer, fg_color="transparent")
        right.pack(side="right", padx=16, pady=12)

        self._lbl_counter = ctk.CTkLabel(
            right, text="0 leads na base",
            font=ctk.CTkFont(family=MONO, size=11),
            text_color=TEXT_MUTED,
        )
        self._lbl_counter.pack(side="right")

    # ═════════════════════════════════════════════════════════════════════════
    # Helpers de widget
    # ═════════════════════════════════════════════════════════════════════════
    def _sh(self, parent, text, pad_top=18):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", padx=0, pady=(pad_top, 8))
        ctk.CTkLabel(
            frame, text=text,
            font=ctk.CTkFont(family=MONO, size=10, weight="bold"),
            text_color=LEADS,
        ).pack(side="left")
        ctk.CTkFrame(frame, fg_color=LEADS_DIM, height=1).pack(
            side="left", fill="x", expand=True, padx=(8, 0), pady=(1, 0),
        )

    def _lbl(self, parent, text, size=11, color=TEXT, wraplength=0):
        kwargs = {}
        if wraplength:
            kwargs["wraplength"] = wraplength
        return ctk.CTkLabel(
            parent, text=text,
            font=ctk.CTkFont(family=SANS, size=size),
            text_color=color, anchor="w", **kwargs,
        )

    def _fl(self, parent, text):
        self._lbl(parent, text, size=10, color=TEXT_SEC).pack(
            anchor="w", padx=2, pady=(8, 2)
        )

    def _entry(self, parent, placeholder="", default="", secret=False, height=36):
        e = ctk.CTkEntry(
            parent, placeholder_text=placeholder,
            fg_color=CARD, border_color=BORDER2,
            text_color=TEXT, placeholder_text_color=TEXT_MUTED,
            height=height, corner_radius=8, show="*" if secret else "",
            font=ctk.CTkFont(family=SANS, size=11),
        )
        if default:
            e.insert(0, default)
        return e

    def _chk(self, parent, text):
        c = ctk.CTkCheckBox(
            parent, text=text,
            font=ctk.CTkFont(family=SANS, size=11),
            text_color=TEXT, fg_color=LEADS_GLOW,
            hover_color=LEADS_DIM, checkmark_color="#ffffff",
        )
        c.pack(anchor="w", padx=2, pady=(0, 6))
        return c

    # ═════════════════════════════════════════════════════════════════════════
    # Log helpers
    # ═════════════════════════════════════════════════════════════════════════
    def _log(self, msg: str, level: str = "INFO"):
        import datetime
        ts   = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"{ts}  {level:<8}  {msg}\n"
        self._txt_log.configure(state="normal")
        self._txt_log.insert("end", line, level)
        self._txt_log.configure(state="disabled")
        self._txt_log.see("end")
        self._log_cb(msg, level)

    def _clear_log(self):
        self._txt_log.configure(state="normal")
        self._txt_log.delete("1.0", "end")
        self._txt_log.configure(state="disabled")

    def _refresh_stats(self):
        try:
            from leads.db import get_stats, init_db
            init_db()
            s = get_stats()
            no_cont = max(0, s["total"] - max(s["with_email"], s["with_phone"]))
            self._lbl_total.configure(text=str(s["total"]))
            self._lbl_email.configure(text=str(s["with_email"]))
            self._lbl_phone.configure(text=str(s["with_phone"]))
            self._lbl_no_cont.configure(text=str(no_cont))
            self._lbl_counter.configure(text=f"{s['total']} leads na base")
        except Exception:
            pass

    # ═════════════════════════════════════════════════════════════════════════
    # Ações dos botões
    # ═════════════════════════════════════════════════════════════════════════
    def _on_start(self):
        token    = self._token_entry.get().strip()
        cnaes    = [e.get().strip() for _, e in self._cnae_rows if e.get().strip()]
        uf       = self._uf_entry.get().strip().upper()
        municipio = self._mun_entry.get().strip().upper()
        enrich   = self._chk_enrich.get() == 1

        try:
            max_r = max(1, int(self._max_entry.get() or 200))
        except ValueError:
            max_r = 200

        if not token:
            messagebox.showwarning(
                "Token obrigatório",
                "Informe o token gratuito do Brasil.io.\n\n"
                "Acesse: brasil.io/auth/tokens-api/",
            )
            return
        if not cnaes:
            messagebox.showwarning("CNAE obrigatório", "Informe ao menos um código CNAE.")
            return

        self._stop_event.clear()
        self._btn_start.configure(state="disabled", text="⏳  Extraindo...")
        self._btn_stop.configure(state="normal")
        self._progress.set(0)
        self._lbl_pct.configure(text="0%")

        cfg = {
            "token":    token,
            "cnaes":    cnaes,
            "uf":       uf,
            "municipio": municipio,
            "max_r":    max_r,
            "enrich":   enrich,
        }
        self._thread = threading.Thread(
            target=self._run_extraction, args=(cfg,), daemon=True
        )
        self._thread.start()

    def _on_stop(self):
        self._stop_event.set()
        self._log("Solicitação de parada recebida...", "WARNING")
        self._btn_stop.configure(state="disabled")

    def _on_export(self):
        def _run():
            try:
                import pandas as pd
                from leads.db import get_all_leads, init_db
                init_db()
                leads = get_all_leads()

                if not leads:
                    self.after(0, lambda: messagebox.showinfo(
                        "Sem dados", "Nenhum lead na base. Execute a extração primeiro."
                    ))
                    return

                output = self._out_entry.get().strip() or str(Path.home() / "leads_cnae.xlsx")
                fmt    = self._fmt_var.get()

                df = pd.DataFrame(leads)
                df["email"]    = df["email"].fillna("").astype(str)
                df["telefone"] = df["telefone"].fillna("").astype(str)

                if self._chk_only_email.get() == 1:
                    df = df[df["email"].str.strip() != ""]
                if self._chk_only_phone.get() == 1:
                    df = df[df["telefone"].str.strip() != ""]

                if fmt == "emkt":
                    out_df = pd.DataFrame({
                        "REPRESENTANTE": df.get("cnae_descricao", pd.Series([""] * len(df))).fillna(""),
                        "CLIENTE":       df["razao_social"].where(df["razao_social"].str.strip() != "", df.get("nome_fantasia", "")).fillna(""),
                        "EMAIL":         df["email"],
                        "TELEFONE":      df["telefone"],
                        "CNPJ":          df["cnpj"].fillna(""),
                        "MUNICIPIO":     df["municipio"].fillna(""),
                        "UF":            df["uf"].fillna(""),
                    })
                else:
                    out_df = df.drop(columns=["id", "created_at"], errors="ignore")

                out_df.to_excel(output, index=False)
                n = len(out_df)
                self.after(0, lambda: (
                    self._log(f"✓ {n} leads exportados → {output}", "SUCCESS"),
                    messagebox.showinfo("Exportado!", f"{n} leads salvos em:\n{output}"),
                ))

            except Exception as e:
                self.after(0, lambda err=str(e): self._log(f"Erro ao exportar: {err}", "ERROR"))

        threading.Thread(target=_run, daemon=True).start()

    def _on_clear_db(self):
        from leads.db import get_stats, init_db, clear_leads
        init_db()
        s = get_stats()
        if s["total"] == 0:
            messagebox.showinfo("Base vazia", "Nenhum lead na base.")
            return
        if messagebox.askyesno(
            "Limpar base?",
            f"{s['total']} leads serão removidos permanentemente.\nDeseja continuar?",
        ):
            n = clear_leads()
            self._log(f"Base limpa — {n} leads removidos.", "WARNING")
            self._refresh_stats()

    # ═════════════════════════════════════════════════════════════════════════
    # Pipeline de extração (roda em thread)
    # ═════════════════════════════════════════════════════════════════════════
    def _run_extraction(self, cfg: dict):
        import sys
        from pathlib import Path as _P
        sys.path.insert(0, str(_P(__file__).parent.parent))

        from leads.brasilio import search_by_cnae
        from leads.cnpjws   import enrich as cnpjws_enrich, normalize as cnpjws_norm
        from leads.db       import init_db, upsert_lead, get_stats

        init_db()
        cnaes      = cfg["cnaes"]
        total_cnaes = len(cnaes)

        self.after(0, lambda: self._log(
            f"Iniciando — {total_cnaes} CNAE(s) | "
            f"UF: {cfg['uf'] or 'Todas'} | "
            f"Município: {cfg['municipio'] or 'Todos'} | "
            f"Enriquecimento: {'Sim' if cfg['enrich'] else 'Não'}"
        ))

        try:
            for ci, cnae in enumerate(cnaes):
                if self._stop_event.is_set():
                    break

                self.after(0, lambda c=cnae: self._log(f"Buscando CNAE {c}..."))

                def _prog(found, total_est, c=cnae):
                    self.after(0, lambda: self._log(
                        f"  {c}: {found} / {total_est or '?'} encontrados", "DIM"
                    ))

                try:
                    companies = search_by_cnae(
                        cnae=cnae,
                        token=cfg["token"],
                        uf=cfg["uf"],
                        municipio=cfg["municipio"],
                        max_results=cfg["max_r"],
                        on_progress=_prog,
                        stop_event=self._stop_event,
                    )
                except ValueError as e:
                    self.after(0, lambda msg=str(e): self._log(msg, "ERROR"))
                    break

                n_found = len(companies)
                self.after(0, lambda c=cnae, n=n_found: self._log(
                    f"  CNAE {c}: {n} empresas encontradas."
                ))

                for i, company in enumerate(companies):
                    if self._stop_event.is_set():
                        break

                    cnpj = company.get("cnpj", "")
                    if not cnpj:
                        continue

                    if cfg["enrich"]:
                        raw = cnpjws_enrich(cnpj)
                        lead = cnpjws_norm(raw) if raw else self._fallback_lead(company, cnae)
                        time.sleep(0.8)  # ~3 req/min seguro
                    else:
                        lead = self._fallback_lead(company, cnae)

                    upsert_lead(lead)

                    # Atualiza UI a cada 5 leads
                    if i % 5 == 0 or i == n_found - 1:
                        s = get_stats()
                        pct_raw = ((ci * cfg["max_r"]) + i + 1) / (total_cnaes * cfg["max_r"])
                        pct     = min(pct_raw, 0.99)
                        self.after(0, lambda s=s, p=pct: (
                            self._lbl_total.configure(text=str(s["total"])),
                            self._lbl_email.configure(text=str(s["with_email"])),
                            self._lbl_phone.configure(text=str(s["with_phone"])),
                            self._lbl_no_cont.configure(
                                text=str(max(0, s["total"] - max(s["with_email"], s["with_phone"])))
                            ),
                            self._lbl_counter.configure(text=f"{s['total']} leads na base"),
                            self._progress.set(p),
                            self._lbl_pct.configure(text=f"{int(p * 100)}%"),
                        ))

                self.after(0, lambda c=cnae: self._log(f"✓ CNAE {c} concluído.", "SUCCESS"))

            # Finaliza
            s = get_stats()
            self.after(0, lambda s=s: (
                self._log(
                    f"Extração finalizada — "
                    f"Total: {s['total']}  |  "
                    f"Com e-mail: {s['with_email']}  |  "
                    f"Com telefone: {s['with_phone']}",
                    "SUCCESS",
                ),
                self._lbl_total.configure(text=str(s["total"])),
                self._lbl_email.configure(text=str(s["with_email"])),
                self._lbl_phone.configure(text=str(s["with_phone"])),
                self._lbl_no_cont.configure(
                    text=str(max(0, s["total"] - max(s["with_email"], s["with_phone"])))
                ),
                self._lbl_counter.configure(text=f"{s['total']} leads na base"),
                self._progress.set(1.0),
                self._lbl_pct.configure(text="100%"),
            ))

        except Exception as e:
            self.after(0, lambda err=str(e): self._log(f"Erro crítico: {err}", "ERROR"))

        finally:
            self.after(0, lambda: (
                self._btn_start.configure(state="normal", text="▶  Iniciar Extração"),
                self._btn_stop.configure(state="disabled"),
            ))

    @staticmethod
    def _fallback_lead(company: dict, cnae: str) -> dict:
        """Normaliza dados do Brasil.io quando não há enriquecimento CNPJ.ws."""
        ddd1 = str(company.get("ddd1", "") or "").strip()
        tel1 = str(company.get("telefone1", "") or "").strip()

        def _s(v):
            s = str(v or "").strip()
            return "" if s in ("nan", "None") else s

        return {
            "razao_social":   _s(company.get("nome_fantasia")),
            "nome_fantasia":  _s(company.get("nome_fantasia")),
            "cnpj":           _s(company.get("cnpj")),
            "email":          _s(company.get("email")).lower(),
            "telefone":       f"({ddd1}) {tel1}" if ddd1 and tel1 else tel1,
            "municipio":      _s(company.get("municipio")),
            "uf":             _s(company.get("uf")),
            "cep":            _s(company.get("cep")),
            "logradouro":     _s(company.get("logradouro")),
            "numero":         _s(company.get("numero")),
            "bairro":         _s(company.get("bairro")),
            "cnae_principal": cnae,
            "cnae_descricao": "",
            "situacao":       "ATIVA" if company.get("situacao_cadastral") == "02" else _s(company.get("situacao_cadastral")),
            "porte":          "",
            "capital_social": "",
            "data_inicio":    _s(company.get("data_inicio_atividade")),
            "socio_principal": "",
            "website":        "",
            "fonte":          "Brasil.io",
        }
