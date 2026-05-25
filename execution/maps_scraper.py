"""
Google Maps scraper using Playwright.
Searches businesses by keyword + location and extracts contact data.
"""
import asyncio
import hashlib
import re
from typing import Callable, Optional


def maps_id(name: str, address: str) -> str:
    """Generate a stable pseudo-CNPJ for Maps records (no real CNPJ available)."""
    h = hashlib.md5(f"{name}|{address}".lower().encode()).hexdigest()[:14]
    return f"MAPS_{h}"


def scrape_maps(
    keyword: str,
    location: str,
    max_results: int = 50,
    on_result: Optional[Callable] = None,
    on_progress: Optional[Callable] = None,
    stop_event=None,
) -> list[dict]:
    """Synchronous wrapper — runs the async scraper in a new event loop."""
    try:
        return asyncio.run(
            _async_scrape(keyword, location, max_results, on_result, on_progress, stop_event)
        )
    except Exception as e:
        raise RuntimeError(f"Maps scraping failed: {e}") from e


async def _async_scrape(keyword, location, max_results, on_result, on_progress, stop_event):
    from playwright.async_api import async_playwright

    results = []
    query   = f"{keyword} {location}".strip()
    url     = "https://www.google.com/maps/search/" + query.replace(" ", "+")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
        )
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="pt-BR",
        )
        page = await ctx.new_page()

        try:
            await page.goto(url, timeout=30000, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            # Dismiss cookie/consent dialogs (Google may show these)
            for sel in [
                'button[aria-label*="ccept"]',
                'button[aria-label*="ceitar"]',
                '#L2AGLb',
                'form[action*="consent"] button',
            ]:
                try:
                    btn = page.locator(sel).first
                    if await btn.is_visible(timeout=1500):
                        await btn.click()
                        await page.wait_for_timeout(1000)
                        break
                except Exception:
                    pass

            seen      = set()
            no_new    = 0
            max_blank = 5

            while len(results) < max_results and no_new < max_blank:
                if stop_event and stop_event.is_set():
                    break

                cards = await page.query_selector_all('div[role="article"]')
                found_new = False

                for card in cards:
                    if len(results) >= max_results:
                        break
                    if stop_event and stop_event.is_set():
                        break

                    try:
                        name = await _card_name(card)
                        if not name or name in seen:
                            continue
                        seen.add(name)
                        found_new = True

                        await card.click()
                        await page.wait_for_timeout(1800)

                        biz = await _detail(page, name)
                        results.append(biz)

                        if on_result:
                            on_result(biz)
                        if on_progress:
                            on_progress(len(results), max_results)

                        await page.wait_for_timeout(400)
                    except Exception:
                        continue

                no_new = 0 if found_new else no_new + 1

                # Check for natural end-of-results marker
                try:
                    end_p = await page.query_selector("p.fontBodyMedium")
                    if end_p:
                        txt = (await end_p.text_content() or "").lower()
                        if "fim" in txt or "end of" in txt:
                            break
                except Exception:
                    pass

                # Scroll results panel
                try:
                    feed = await page.query_selector('div[role="feed"]')
                    if feed:
                        await feed.evaluate("el => el.scrollBy(0, 800)")
                    else:
                        await page.keyboard.press("End")
                    await page.wait_for_timeout(1500)
                except Exception:
                    no_new = max_blank  # give up

        finally:
            await browser.close()

    return results


async def _card_name(card) -> str:
    for sel in [".qBF1Pd", "h3", "div.fontHeadlineSmall", '[aria-label]']:
        try:
            el = await card.query_selector(sel)
            if el:
                t = (await el.text_content() or "").strip()
                if t:
                    return t
        except Exception:
            pass
    return ""


async def _text(page, selectors: list) -> str:
    for sel in selectors:
        try:
            el = await page.query_selector(sel)
            if el:
                t = (await el.text_content() or "").strip()
                if t:
                    return t
        except Exception:
            pass
    return ""


async def _detail(page, name: str) -> dict:
    biz = {
        "razao_social":  name,
        "nome_fantasia": name,
        "fonte":         "Google Maps",
        "source_type":   "maps",
        "cnpj":          "",
        "email":         "",
        "telefone":      "",
        "website":       "",
        "logradouro":    "",
        "municipio":     "",
        "uf":            "",
        "cep":           "",
        "bairro":        "",
        "numero":        "",
        "cnae_principal":"",
        "cnae_descricao":"",
        "situacao":      "",
        "porte":         "",
        "capital_social":"",
        "data_inicio":   "",
        "socio_principal":"",
        "campanha":      "",
        "google_rating": "",
        "google_reviews":"",
        "categoria":     "",
        "latitude":      "",
        "longitude":     "",
        "instagram":     "",
        "linkedin":      "",
    }

    try:
        rating = await _text(page, ["div.fontDisplayLarge", "span.ceNzKf", ".F7nice > span"])
        if rating and re.match(r'[\d,.]', rating):
            biz["google_rating"] = rating
    except Exception:
        pass

    try:
        for btn in await page.query_selector_all("button"):
            label = (await btn.get_attribute("aria-label") or "")
            m = re.search(r'([\d.,]+)\s*avalia', label, re.I)
            if m:
                biz["google_reviews"] = m.group(1)
                break
    except Exception:
        pass

    try:
        cat = await _text(page, ["button.DkEaL", "[jsaction*='category']"])
        if cat:
            biz["categoria"] = cat
    except Exception:
        pass

    try:
        for el in await page.query_selector_all('[data-item-id^="phone"]'):
            t = await _text_from(el)
            if t:
                biz["telefone"] = t
                break
    except Exception:
        pass

    try:
        for el in await page.query_selector_all('[data-item-id="address"]'):
            t = await _text_from(el)
            if t:
                biz["logradouro"] = t
                m = re.search(r'\d{5}-?\d{3}', t)
                if m:
                    biz["cep"] = m.group(0)
                break
    except Exception:
        pass

    try:
        site_el = await page.query_selector('a[data-item-id="authority"]')
        if site_el:
            href = (await site_el.get_attribute("href") or "").strip()
            if href and not href.startswith("https://www.google"):
                biz["website"] = href
    except Exception:
        pass

    try:
        m = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', page.url)
        if m:
            biz["latitude"]  = m.group(1)
            biz["longitude"] = m.group(2)
    except Exception:
        pass

    # Generate pseudo-CNPJ from name + address (needed for DB upsert)
    biz["cnpj"] = maps_id(name, biz.get("logradouro", ""))
    return biz


async def _text_from(el) -> str:
    for sel in ["div.rogA2c", "div.Io6YTe", "span.Io6YTe", "div[aria-label]", "span"]:
        try:
            child = await el.query_selector(sel)
            if child:
                t = (await child.text_content() or "").strip()
                if t and len(t) > 2:
                    return t
        except Exception:
            pass
    return ""
