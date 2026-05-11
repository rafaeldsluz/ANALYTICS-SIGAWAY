"""
Fila de disparo WhatsApp — fluxo humanizado de 2 mensagens por contato.
Rotação automática de saudações e validações com delays variáveis e pausas de bloco.
"""
import logging
import random
import threading
import time
import uuid
from datetime import datetime
from typing import Callable

# ── Pools de mensagens ─────────────────────────────────────────────────────────

_GREETINGS_MANHA = ["Bom dia", "Bom dia!", "Olá, bom dia", "Oi, bom dia!"]
_GREETINGS_TARDE = ["Boa tarde", "Olá, boa tarde", "Oi, boa tarde!"]
_GREETINGS_NOITE = ["Boa noite", "Olá, boa noite"]
_GREETINGS_NEUTRO = ["Olá", "Oi, tudo certo?", "Olá, tudo bem?", "Oi!"]

_VALIDATIONS = [
    "Esse contato é da empresa {empresa}?",
    "Falo com a {empresa}?",
    "Esse número pertence à {empresa}?",
    "Consigo falar com alguém da {empresa}?",
    "É da {empresa}?",
    "Falo com a equipe da {empresa}?",
]


def _pick_greeting() -> str:
    h = datetime.now().hour
    if 5 <= h < 12:
        pool = _GREETINGS_MANHA + _GREETINGS_NEUTRO
    elif 12 <= h < 18:
        pool = _GREETINGS_TARDE + _GREETINGS_NEUTRO
    else:
        pool = _GREETINGS_NOITE + _GREETINGS_NEUTRO
    return random.choice(pool)

from execution.whatsapp_db import (
    cancel_pending,
    get_stats,
    init_db,
    insert_contacts,
    mark_failed,
    mark_sent,
    next_pending,
)
from execution.whatsapp_sender import send_whatsapp

logger = logging.getLogger(__name__)


class WhatsAppQueue:
    """
    Processa disparos WhatsApp sem intervalo entre mensagens.

    Callbacks (todos opcionais):
      on_stats(dict)        — stats atualizadas após cada envio
      on_log(msg, level)    — mensagem de log para a UI
      on_done(error: bool)  — disparo finalizado
      on_tick(remaining: int) — segundos restantes durante countdown
    """

    def __init__(
        self,
        on_stats: Callable[[dict], None] | None = None,
        on_log: Callable[[str, str], None] | None = None,
        on_done: Callable[[bool], None] | None = None,
        on_tick: Callable[[int], None] | None = None,
    ) -> None:
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._thread: threading.Thread | None = None
        self.campaign_id: str | None = None
        self._on_stats = on_stats or (lambda s: None)
        self._on_log   = on_log   or (lambda m, lv: None)
        self._on_done  = on_done  or (lambda err: None)
        self._on_tick  = on_tick  or (lambda r: None)
        init_db()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def is_paused(self) -> bool:
        return self._pause.is_set()

    def start(self, contacts: list[dict], config: dict) -> str:
        """
        Inicia a campanha.

        contacts: lista de {"nome": str, "phone": str}
        config: {"base_url": str, "api_key": str, "instance": str, "message": str}
        Retorna campaign_id gerado.
        """
        if self.is_running:
            raise RuntimeError("Já existe um disparo em andamento.")
        if not contacts:
            raise ValueError("Lista de contatos está vazia.")

        self.campaign_id = (
            f"wz_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        )
        n_pending, n_skipped = insert_contacts(self.campaign_id, contacts)
        if n_skipped:
            self._log(
                f"  ⏭  {n_skipped} contato(s) ignorado(s) — já receberam mensagem anteriormente."
            )
        self._stop.clear()
        self._pause.clear()

        self._thread = threading.Thread(
            target=self._run,
            args=(self.campaign_id, config),
            daemon=True,
        )
        self._thread.start()
        return self.campaign_id

    def pause(self) -> None:
        """Pausa o disparo após o envio atual terminar."""
        self._pause.set()
        self._log("  ⏸  Pausando após envio atual...", "WARNING")

    def resume(self) -> None:
        """Retoma o disparo pausado."""
        self._pause.clear()
        self._log("  ▶  Disparo retomado.")

    def stop(self) -> None:
        self._stop.set()
        self._pause.clear()  # desbloqueia o loop se estiver pausado

    # ── Worker ────────────────────────────────────────────────────────────────

    def _run(self, campaign_id: str, cfg: dict) -> None:
        total = get_stats(campaign_id)["total"]
        self._log(f"Campanha {campaign_id} iniciada — {total} contatos na fila.")
        self._log("Modo humanizado: saudação → validação por empresa → delay variável.", "INFO")

        custom_msg      = cfg.get("message", "").strip()
        sent_in_block   = 0
        next_block_size = random.randint(15, 30)

        try:
            while not self._stop.is_set():
                # ── Pausa do usuário ─────────────────────────────────────────
                while self._pause.is_set() and not self._stop.is_set():
                    time.sleep(0.5)
                if self._stop.is_set():
                    break

                contact = next_pending(campaign_id)
                if not contact:
                    break

                cid     = contact["id"]
                nome    = contact["nome"] or contact["phone"]
                phone   = contact["phone"]
                empresa = contact.get("empresa") or nome

                stats_now = get_stats(campaign_id)
                pos = stats_now["sent"] + stats_now["failed"] + 1
                self._log(f"[{pos}/{total}]  {nome} · {empresa} ({phone})")

                try:
                    # ── Msg 1: saudação curta e natural ─────────────────────
                    greeting = _pick_greeting()
                    self._log(f"  → Saudação: \"{greeting}\"")
                    send_whatsapp(
                        base_url=cfg["base_url"], api_key=cfg["api_key"],
                        instance=cfg["instance"], phone=phone, message=greeting,
                    )

                    # ── Delay entre mensagens: 20-45s ────────────────────────
                    if not self._stop.is_set():
                        inter = random.randint(20, 45)
                        self._log(f"  ⏱  Aguardando {inter}s antes da validação...")
                        self._countdown(inter)

                    if self._stop.is_set():
                        mark_failed(cid, "Interrompido durante envio")
                        break

                    # ── Msg 2: validação com nome da empresa ─────────────────
                    validation = random.choice(_VALIDATIONS).replace("{empresa}", empresa)
                    self._log(f"  → Validação: \"{validation}\"")
                    send_whatsapp(
                        base_url=cfg["base_url"], api_key=cfg["api_key"],
                        instance=cfg["instance"], phone=phone, message=validation,
                    )

                    # ── Msg 3: mensagem adicional opcional ───────────────────
                    if custom_msg and not self._stop.is_set():
                        extra_delay = random.randint(15, 30)
                        self._log(f"  ⏱  Aguardando {extra_delay}s antes da mensagem adicional...")
                        self._countdown(extra_delay)
                        if not self._stop.is_set():
                            msg3 = (custom_msg
                                    .replace("{nome}", nome).replace("{NOME}", nome)
                                    .replace("{empresa}", empresa).replace("{EMPRESA}", empresa))
                            send_whatsapp(
                                base_url=cfg["base_url"], api_key=cfg["api_key"],
                                instance=cfg["instance"], phone=phone, message=msg3,
                            )

                    mark_sent(cid)
                    self._log(f"  ✓ Fluxo concluído para {nome}", "SUCCESS")

                except Exception as e:
                    mark_failed(cid, str(e))
                    self._log(f"  ✗ Falha ({nome}): {e}", "ERROR")

                self._emit_stats(campaign_id)
                sent_in_block += 1

                if not next_pending(campaign_id) or self._stop.is_set():
                    break

                # ── Pausa de bloco: a cada 15-30 contatos, 5-20 min ─────────
                if sent_in_block >= next_block_size:
                    block_secs = random.randint(300, 1200)
                    self._log(
                        f"  🛑  Pausa de bloco após {sent_in_block} envios — "
                        f"retomando em {block_secs // 60}min {block_secs % 60}s...", "WARNING"
                    )
                    self._countdown(block_secs)
                    sent_in_block   = 0
                    next_block_size = random.randint(15, 30)
                    if self._stop.is_set():
                        break

                # ── Delay entre contatos: 40-120s ────────────────────────────
                iv_min   = max(int(cfg.get("interval_min", 40)), 40)
                iv_max   = max(int(cfg.get("interval_max", 120)), iv_min)
                interval = random.randint(iv_min, iv_max)
                self._log(f"  ⏱  Próximo contato em {interval}s...")
                self._countdown(interval)

            if self._stop.is_set():
                cancel_pending(campaign_id)
                self._log("Disparo interrompido pelo usuário.", "WARNING")

            final = get_stats(campaign_id)
            self._log(
                f"Concluído — Enviados: {final['sent']}  "
                f"Falhas: {final['failed']}  Total: {final['total']}"
            )
            self._emit_stats(campaign_id)
            self._on_done(False)

        except Exception as e:
            logger.exception("Erro crítico na fila WhatsApp")
            self._log(f"Erro crítico: {e}", "ERROR")
            self._on_done(True)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _countdown(self, seconds: int) -> None:
        """Sleep interrompível que emite ticks para o countdown da UI."""
        deadline = time.monotonic() + seconds
        while not self._stop.is_set():
            remaining = int(deadline - time.monotonic())
            if remaining <= 0:
                break
            self._on_tick(remaining)
            time.sleep(1)
        self._on_tick(0)

    def _log(self, msg: str, level: str = "INFO") -> None:
        logger.log(logging.getLevelName(level), f"[WZ] {msg}")
        self._on_log(msg, level)

    def _emit_stats(self, campaign_id: str) -> None:
        try:
            self._on_stats(get_stats(campaign_id))
        except Exception:
            pass
