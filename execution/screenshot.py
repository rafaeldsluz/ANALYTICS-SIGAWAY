"""
Camada de Execução — Captura de screenshot da Torre de Controle (Sigaway).
Estratégia: login → busca empresa pelo nome no campo de pesquisa → screenshot.
Não requer companyId — usa apenas o nome da empresa do Excel.
"""

import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from playwright.async_api import (
    TimeoutError as PlaywrightTimeout,
    async_playwright,
)

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).parent.parent / ".tmp"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SIGAWAY_DASHBOARD = "https://app.sigaway.com.br/asset-classification/dashboard"

# Palavras genéricas removidas antes de buscar — sobra o nome distintivo
_GENERIC_WORDS = {
    "TRANSPORTES", "TRANSPORTADORA", "TRANSPORTE", "TRANS",
    "LOGISTICA", "LOGÍSTICAS", "LOG",
    "COMERCIO", "COMÉRCIO", "COMERCIAL",
    "INDUSTRIA", "INDÚSTRIA", "INDUSTRIAL",
    "SERVICOS", "SERVIÇOS", "SERVICO", "SERVIÇO",
    "RODOVIARIO", "RODOVIÁRIA", "RODOVIARIOS", "RODOVIÁRIAS",
    "LTDA", "LTDA.", "ME", "SA", "S.A.", "EIRELI", "EPP", "SS",
    "AGROPECUARIA", "AGROPECUÁRIA", "SUPRIMENTOS",
    "COMERCIO", "EXPORTACAO", "EXPORTAÇÃO", "REPRESENTACAO",
    "DE", "DA", "DO", "DAS", "DOS", "E", "&", "-",
    "LTDA", "CIA", "CIA.", "GRUPO",
}


def extract_search_key(nome: str) -> str:
    """
    Extrai a palavra mais distintiva do nome da empresa para usar na busca.

    Exemplos:
      'TRANSPORTES RODANZ LTDA'              → 'RODANZ'
      'SPRICIGO & GUIZONI TRANSPORTES LTDA'  → 'SPRICIGO'
      'R&R DIESEL TRANSPORTES LTDA'          → 'R&R'
      'RS COMERCIO TRANSPORTES LTDA'         → 'RS'
      'EAP TRANSPORTES LTDA'                 → 'EAP'
      'A L TRANSPORTES LTDA'                 → 'A L'
      'COMERCIAL NI DISTRIBUIDORA ALIMENTOS' → 'DISTRIBUIDORA'
    """
    upper = nome.upper()
    words_raw = upper.split()

    # Coleta tokens não-genéricos com 2+ letras
    distinctive = []
    for w in words_raw:
        clean = re.sub(r"[^\w]", "", w)
        if not clean:
            continue
        if clean in _GENERIC_WORDS:
            continue
        if len(clean) >= 2:
            distinctive.append(w)

    if distinctive:
        # Prefere primeiro token com 3+ chars (mais único); senão usa o primeiro disponível
        for w in distinctive:
            if len(re.sub(r"[^\w]", "", w)) >= 3:
                key = w
                break
        else:
            key = distinctive[0]
        logger.debug(f"Chave de busca: '{nome}' → '{key}'")
        return key

    # Sem token distintivo — tenta unir iniciais não-genéricas (ex: 'A L' → 'A L')
    non_generic = [
        w for w in words_raw
        if re.sub(r"[^\w]", "", w) and re.sub(r"[^\w]", "", w) not in _GENERIC_WORDS
    ]
    if non_generic:
        key = " ".join(non_generic[:2])
        logger.debug(f"Chave de busca (iniciais): '{nome}' → '{key}'")
        return key

    # Último recurso: primeira palavra com mais de 1 caractere
    for w in words_raw:
        if len(w) > 1:
            return w

    return nome

# Seletores candidatos para o campo de busca de empresa no Sigaway
_SEARCH_SELECTORS = [
    "input[placeholder*='empresa' i]",
    "input[placeholder*='buscar' i]",
    "input[placeholder*='pesquisar' i]",
    "input[placeholder*='search' i]",
    "input[placeholder*='company' i]",
    "input[placeholder*='cliente' i]",
    "[class*='company-search'] input",
    "[class*='empresa-search'] input",
    "[class*='search-company'] input",
    "[class*='filter'] input",
    "[class*='autocomplete'] input",
    "[class*='select-company'] input",
]

# Seletores para aguardar os gráficos circulares de pontuação
_CHART_SELECTORS = [
    "svg circle",
    "canvas",
    "[class*='gauge']",
    "[class*='score']",
    "[class*='chart']",
    "[class*='donut']",
    "[class*='circular']",
]


async def _wait_for_charts(page, timeout_ms: int = 30_000) -> None:
    """
    Aguarda gráficos circulares visíveis e verifica que os dados foram renderizados.
    Tolerante a timeout — captura o estado atual em caso de falha.
    """
    try:
        await page.wait_for_selector(", ".join(_CHART_SELECTORS), timeout=timeout_ms)
        logger.debug("Elementos de gráfico detectados. Aguardando dados renderizarem...")

        # Verifica se o elemento detectado está de fato visível (não apenas presente no DOM)
        for sel in _CHART_SELECTORS:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    logger.debug(f"Elemento visível confirmado: {sel}")
                    break
            except Exception:
                continue

        # Aguarda a rede estabilizar para garantir que os dados da API foram carregados
        try:
            await page.wait_for_load_state("networkidle", timeout=10_000)
            logger.debug("Rede idle — dados da Torre de Controle carregados.")
        except PlaywrightTimeout:
            logger.warning("Network idle timeout durante aguardo de dados. Usando delay adicional.")
            await page.wait_for_timeout(3_000)

        # Buffer final para renderização do canvas/SVG
        await page.wait_for_timeout(2_500)
        logger.debug("Gráficos circulares prontos para captura.")
    except PlaywrightTimeout:
        logger.warning("Timeout aguardando gráficos. Capturando estado atual.")


async def _set_period_week(page, timeout_ms: int) -> None:
    """
    Após selecionar a empresa, garante que o período seja os últimos 7 dias (WEEK).
    Extrai o companyId da URL atual e renavega com periodType=WEEK.
    """
    current_url = page.url
    if "companyId" not in current_url:
        logger.warning("companyId não encontrado na URL — filtro WEEK não aplicado.")
        return

    parsed = urlparse(current_url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params["periodType"] = ["WEEK"]
    new_query = urlencode({k: v[0] for k, v in params.items()})
    new_url = urlunparse(parsed._replace(query=new_query))

    if new_url == current_url:
        logger.debug("Período WEEK já aplicado na URL.")
        return

    logger.info("Aplicando filtro: últimos 7 dias (WEEK).")
    await page.goto(new_url, wait_until="domcontentloaded", timeout=timeout_ms)

    # Aguarda a rede estabilizar após a navegação antes de verificar os dados
    try:
        await page.wait_for_load_state("networkidle", timeout=15_000)
        logger.debug("Rede estabilizada após navegar para Torre de Controle (WEEK).")
    except PlaywrightTimeout:
        logger.warning("Network idle timeout após navegar para WEEK — continuando com delay fixo.")

    # Delay de 5 s para garantir renderização completa dos dados na tela
    logger.debug("Aguardando 5s para renderização dos dados da Torre de Controle...")
    await page.wait_for_timeout(5_000)


async def _login(page, url: str, username: str, password: str, timeout_ms: int) -> None:
    """Navega até a URL base e realiza o login."""
    logger.info(f"Acessando {url}")
    await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

    user_selectors = [
        'input[name="username"]', 'input[name="email"]',
        'input[type="email"]',   'input[name="login"]',
        'input[id*="user"]',     'input[id*="email"]',
    ]
    pass_selectors = [
        'input[name="password"]', 'input[type="password"]',
        'input[id*="pass"]',      'input[id*="senha"]',
    ]
    submit_selectors = [
        'button[type="submit"]', 'input[type="submit"]',
        'button:has-text("Entrar")', 'button:has-text("Login")',
        'button:has-text("Acessar")',
    ]

    user_field = None
    for sel in user_selectors:
        try:
            await page.wait_for_selector(sel, timeout=5_000)
            user_field = sel
            break
        except PlaywrightTimeout:
            continue

    if not user_field:
        raise RuntimeError("Campo de usuário não encontrado na página de login.")

    await page.fill(user_field, username)

    pass_field = None
    for sel in pass_selectors:
        if await page.query_selector(sel):
            pass_field = sel
            break
    if not pass_field:
        raise RuntimeError("Campo de senha não encontrado.")

    await page.fill(pass_field, password)

    for sel in submit_selectors:
        btn = await page.query_selector(sel)
        if btn:
            await btn.click()
            break
    else:
        raise RuntimeError("Botão de submit não encontrado.")

    await page.wait_for_load_state("networkidle", timeout=timeout_ms)
    logger.info("Login realizado com sucesso.")


async def _dismiss_modal(page) -> None:
    """Fecha qualquer modal/dialog do MUI que apareça após o login."""
    modal_sel = ".MuiDialog-root, [role='dialog']"
    try:
        await page.wait_for_selector(modal_sel, timeout=4_000)
        logger.debug("Modal detectado — tentando fechar...")
        # Tenta botão de fechar do MUI
        close_btn = await page.query_selector(
            ".MuiDialog-root button[aria-label*='close' i], "
            ".MuiDialog-root button[aria-label*='fechar' i], "
            ".MuiDialog-root button.MuiIconButton-root"
        )
        if close_btn:
            await close_btn.click()
        else:
            await page.keyboard.press("Escape")
        await page.wait_for_timeout(800)
        logger.debug("Modal fechado.")
    except PlaywrightTimeout:
        pass  # Nenhum modal — ok


async def _find_company_input(page, timeout_ms: int = 15_000):
    """
    Aguarda e retorna o input React Select de 'Filtrar por empresa'.
    Usa o placeholderText como critério estável, independente do ID numérico.
    """
    # Aguarda qualquer combobox estar presente
    await page.wait_for_selector("[role='combobox']", timeout=timeout_ms)
    await page.wait_for_timeout(800)

    # Descobre via JS qual combobox tem placeholderText com "empresa"
    found_id = await page.evaluate("""() => {
        const combos = document.querySelectorAll("[role='combobox']");
        for (const el of combos) {
            const phId = el.getAttribute("aria-describedby") || "";
            const phEl = phId ? document.getElementById(phId) : null;
            const txt = (phEl ? phEl.textContent : "").toLowerCase();
            if (txt.includes("empresa") || txt.includes("filtrar")) {
                return el.id || null;
            }
        }
        return null;
    }""")

    if found_id:
        logger.debug(f"Campo empresa encontrado: #{found_id}")
        return await page.query_selector(f"#{found_id}")

    # Fallback direto pelo ID histórico
    el = await page.query_selector("#react-select-6-input")
    if el and await el.is_visible():
        logger.debug("Campo empresa encontrado via ID fixo react-select-6-input.")
        return el

    raise RuntimeError(
        "Campo 'Filtrar por empresa' não encontrado após aguardar. "
        "O Sigaway pode ter mudado o layout — inspecione e atualize execution/screenshot.py."
    )


async def _search_company(page, cliente: str, timeout_ms: int) -> None:
    """
    Fecha modal pós-login, digita a chave de busca no campo
    'Filtrar por empresa' e seleciona o melhor resultado do autocomplete.
    """
    if not cliente or not cliente.strip():
        raise ValueError("Nome do cliente está vazio — verifique a coluna CLIENTE no Excel.")

    search_key = extract_search_key(cliente)
    logger.info(f"Buscando '{cliente}'  →  chave: '{search_key}'")

    await page.goto(SIGAWAY_DASHBOARD, wait_until="domcontentloaded", timeout=timeout_ms)
    await page.wait_for_timeout(2_000)

    # Fecha modal/popup que aparece após o login
    await _dismiss_modal(page)
    # Aguarda a página estabilizar após fechar o modal
    await page.wait_for_timeout(1_500)

    # Localiza o campo de busca de forma robusta
    search_input = await _find_company_input(page, timeout_ms=15_000)

    if not search_input:
        raise RuntimeError("Campo 'Filtrar por empresa' não retornado.")

    # Obtém o ID dinâmico do input (pode variar entre sessões do React)
    input_id = await search_input.get_attribute("id") or "react-select-6-input"
    logger.debug(f"ID do campo empresa: #{input_id}")

    # Clica no controle pai para abrir o dropdown antes de digitar
    await page.evaluate("""(inputId) => {
        const inp = document.getElementById(inputId);
        if (!inp) return false;
        let el = inp.parentElement;
        for (let i = 0; i < 5; i++) {
            if (el && el.classList && [...el.classList].some(c => c.includes('control'))) {
                el.click();
                return true;
            }
            el = el ? el.parentElement : null;
        }
        inp.click();
        return true;
    }""", input_id)
    await page.wait_for_timeout(400)

    # Digita a chave de busca usando o elemento encontrado dinamicamente
    await search_input.fill("")
    await search_input.type(search_key, delay=80)
    logger.debug(f"Digitado '{search_key}' em #{input_id}.")
    await page.wait_for_timeout(1_200)

    # Aguarda e seleciona o melhor resultado do React Select
    name_parts = [p for p in cliente.upper().split() if p not in _GENERIC_WORDS and len(p) > 2]

    def _score(text: str) -> int:
        t = text.upper()
        return sum(1 for p in name_parts if p in t)

    best_item = None
    best_score = 0

    base_option_id = input_id.replace("-input", "-option")
    options_sel = f"[class*='react-select__option'], [id*='{base_option_id}']"
    try:
        await page.wait_for_selector(options_sel, timeout=8_000)
        options = await page.query_selector_all(options_sel)
        for opt in options:
            text = (await opt.text_content() or "").strip()
            score = _score(text)
            logger.debug(f"  Opção (score={score}): {text[:70]}")
            if score > best_score:
                best_score = score
                best_item = opt
    except PlaywrightTimeout:
        logger.warning("Nenhuma opção apareceu no dropdown após digitar.")

    if best_item:
        await best_item.click()
        logger.info(f"Empresa selecionada (score {best_score}/{len(name_parts)}).")
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)
        await page.wait_for_timeout(1_500)
    else:
        await page.keyboard.press("Escape")
        raise RuntimeError(
            f"Nenhum resultado encontrado para '{cliente}' (chave: '{search_key}'). "
            "Verifique se o nome no Excel bate com o cadastro no Sigaway."
        )


async def capture_torre_de_controle(
    url: str,
    username: str,
    password: str,
    cliente: str,
    timeout_ms: int = 60_000,
) -> str:
    """
    Fluxo completo:
      1. Login no Sigaway
      2. Busca a empresa pelo nome no campo de pesquisa
      3. Aguarda gráficos circulares da Torre de Controle
      4. Captura screenshot full-page

    Retorna o caminho absoluto do PNG gerado.
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r"[^\w]", "_", cliente)[:40]
    output_path = OUTPUT_DIR / f"screenshot_{safe}_{ts}.png"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="pt-BR",
        )
        page = await context.new_page()

        try:
            await _login(page, url, username, password, timeout_ms)
            await _search_company(page, cliente, timeout_ms)
            await _set_period_week(page, timeout_ms)
            await _wait_for_charts(page, timeout_ms=30_000)

            await page.screenshot(path=str(output_path), full_page=True)
            logger.info(f"Screenshot salvo: {output_path.name}")

        except Exception:
            err_path = OUTPUT_DIR / f"error_{safe}_{ts}.png"
            try:
                await page.screenshot(path=str(err_path))
                logger.debug(f"Screenshot de erro salvo: {err_path.name}")
            except Exception:
                pass
            raise

        finally:
            await context.close()
            await browser.close()

    return str(output_path)


def run_capture(url: str, username: str, password: str, cliente: str) -> str:
    """Wrapper síncrono."""
    return asyncio.run(
        capture_torre_de_controle(url, username, password, cliente)
    )
