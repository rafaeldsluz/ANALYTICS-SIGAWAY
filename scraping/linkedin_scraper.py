"""
LinkedIn company scraper — finds the company page via Google search,
then extracts company data using Playwright in stealth mode.
"""
import json
import logging
import random
import re
import time
from urllib.parse import quote_plus

_log = logging.getLogger("sigaway.linkedin")

_SKIP_SLUGS = {"about", "login", "signup", "feed", "jobs", "learning", "pulse"}


def _google_search_linkedin(company_name: str) -> str | None:
    """Return a LinkedIn company page URL found via Google, or None."""
    try:
        from playwright.sync_api import sync_playwright
        from scraping.anti_detection import random_ua, setup_stealth_page, human_delay

        query = f'"{company_name}" site:linkedin.com/company'
        search_url = f"https://www.google.com/search?q={quote_plus(query)}"

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            ctx = browser.new_context(user_agent=random_ua(), locale="pt-BR")
            page = ctx.new_page()
            setup_stealth_page(page)

            page.goto(search_url, timeout=20000, wait_until="domcontentloaded")
            human_delay(1.5, 3.0)

            html = page.content()
            browser.close()

        slugs = re.findall(r'linkedin\.com/company/([a-zA-Z0-9_\-]+)', html)
        valid = [s for s in slugs if s.lower() not in _SKIP_SLUGS]
        if valid:
            return f"https://www.linkedin.com/company/{valid[0]}/"
        return None

    except Exception as exc:
        _log.debug("Google→LinkedIn search failed for '%s': %s", company_name, exc)
        return None


def scrape_linkedin_company(url: str) -> dict:
    """
    Scrape a LinkedIn company page (public view — no login).
    Returns: nome, descricao, setor, tamanho, funcionarios, website, especialidades, url.
    """
    result = {
        "nome": "", "descricao": "", "setor": "", "tamanho": "",
        "funcionarios": "", "website": "", "especialidades": "", "url": url,
    }
    try:
        from playwright.sync_api import sync_playwright
        from scraping.anti_detection import random_ua, setup_stealth_page, human_delay

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            ctx = browser.new_context(user_agent=random_ua(), locale="pt-BR")
            page = ctx.new_page()
            setup_stealth_page(page)

            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            human_delay(2.0, 4.0)

            html = page.content()
            browser.close()

        # Company name
        og_title = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html)
        if og_title:
            result["nome"] = og_title.group(1).split("|")[0].split("–")[0].strip()

        # Description
        og_desc = re.search(
            r'<meta[^>]+(?:property="og:description"|name="description")[^>]+content="([^"]+)"',
            html,
        )
        if og_desc:
            result["descricao"] = og_desc.group(1)[:500]

        # JSON-LD structured data
        ld_match = re.search(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL,
        )
        if ld_match:
            try:
                data = json.loads(ld_match.group(1))
                result["nome"]         = result["nome"] or data.get("name", "")
                result["descricao"]    = result["descricao"] or str(data.get("description", ""))[:500]
                result["website"]      = data.get("url", "")
                result["setor"]        = data.get("industry", "")
                emp = data.get("numberOfEmployees", {})
                if isinstance(emp, dict):
                    result["funcionarios"] = str(emp.get("value", ""))
                elif isinstance(emp, (int, str)):
                    result["funcionarios"] = str(emp)
            except (json.JSONDecodeError, TypeError):
                pass

        # Fallbacks from raw HTML
        if not result["setor"]:
            m = re.search(r'"industry"\s*:\s*"([^"]+)"', html)
            if m:
                result["setor"] = m.group(1)

        if not result["tamanho"]:
            m = re.search(
                r'"employeeCountRange"\s*:\s*\{[^}]*"start"\s*:\s*(\d+)[^}]*"end"\s*:\s*(\d+)',
                html,
            )
            if m:
                result["tamanho"] = f"{m.group(1)}-{m.group(2)} funcionários"

        # Specialties
        spec_m = re.search(r'"specialties"\s*:\s*\[([^\]]+)\]', html)
        if spec_m:
            specs = re.findall(r'"([^"]+)"', spec_m.group(1))
            result["especialidades"] = ", ".join(specs[:10])

    except Exception as exc:
        _log.warning("LinkedIn scrape failed for %s: %s", url, exc)

    return result


def find_and_scrape(company_name: str, website: str = "") -> dict:
    """Find LinkedIn company URL via Google, then scrape the page."""
    url = _google_search_linkedin(company_name)
    if not url:
        _log.info("LinkedIn: page not found for '%s'", company_name)
        return {}

    time.sleep(random.uniform(2.0, 5.0))
    result = scrape_linkedin_company(url)
    result["url"] = url
    return result
