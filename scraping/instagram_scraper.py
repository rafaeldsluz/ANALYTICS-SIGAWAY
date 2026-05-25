"""
Instagram scraper — finds the official Instagram handle via Google search,
then extracts public profile data using Playwright in stealth mode.
"""
import logging
import random
import re
import time
from urllib.parse import quote_plus

_log = logging.getLogger("sigaway.instagram")

# Instagram handles that are navigation/meta pages, not company profiles
_SKIP_HANDLES = {
    "p", "reel", "reels", "explore", "accounts", "about",
    "help", "legal", "privacy", "blog", "press", "api",
    "developer", "download", "direct", "stories",
}


def _google_search_instagram(company_name: str, website: str = "") -> str | None:
    """Return an Instagram handle found via Google, or None."""
    try:
        from playwright.sync_api import sync_playwright
        from scraping.anti_detection import random_ua, setup_stealth_page, human_delay

        query = f'"{company_name}" site:instagram.com'
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

        handles = re.findall(r'instagram\.com/([a-zA-Z0-9_.]{3,30})(?:[/"?]|$)', html)
        valid = [h for h in handles if h.lower() not in _SKIP_HANDLES and not h.startswith("_")]
        return valid[0] if valid else None

    except Exception as exc:
        _log.debug("Google→Instagram search failed for '%s': %s", company_name, exc)
        return None


def scrape_instagram_profile(handle: str) -> dict:
    """
    Scrape a public Instagram profile.
    Returns: username, nome, bio, seguidores, seguindo, posts,
             email, whatsapp, website, categoria, verificado.
    """
    result = {
        "username": handle, "nome": "", "bio": "",
        "seguidores": 0, "seguindo": 0, "posts": 0,
        "email": "", "whatsapp": "", "website": "",
        "categoria": "", "verificado": False,
    }
    try:
        from playwright.sync_api import sync_playwright
        from scraping.anti_detection import random_ua, setup_stealth_page, human_delay

        url = f"https://www.instagram.com/{handle}/"

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            ctx = browser.new_context(user_agent=random_ua(), locale="pt-BR")
            page = ctx.new_page()
            setup_stealth_page(page)

            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            human_delay(2.0, 4.0)

            html = page.content()
            browser.close()

        # og:description → "X Seguidores, Y Seguindo, Z publicações — bio text"
        og_desc = re.search(r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"', html)
        if og_desc:
            desc = og_desc.group(1)
            m = re.search(r'([\d,. kKmM]+)\s*[Ss]eguidores', desc)
            if m:
                result["seguidores"] = _parse_abbrev(m.group(1))
            m = re.search(r'([\d,. kKmM]+)\s*[Ss]eguindo', desc)
            if m:
                result["seguindo"] = _parse_abbrev(m.group(1))
            m = re.search(r'([\d,. kKmM]+)\s*[Pp]ubli', desc)
            if m:
                result["posts"] = _parse_abbrev(m.group(1))

        og_title = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html)
        if og_title:
            result["nome"] = og_title.group(1).split("•")[0].split("(")[0].strip()

        # E-mail in page content
        emails = re.findall(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', html)
        emails = [e for e in emails if not e.endswith((".png", ".jpg", ".gif", ".svg"))]
        if emails:
            result["email"] = emails[0]

        # WhatsApp link
        wa = re.search(r'wa\.me/([0-9]{8,15})', html)
        if wa:
            result["whatsapp"] = wa.group(1)

        # External website link
        ext = re.search(r'"external_url"\s*:\s*"([^"]+)"', html)
        if ext:
            result["website"] = ext.group(1)

        # Category
        cat = re.search(r'"category"\s*:\s*"([^"]+)"', html)
        if cat:
            result["categoria"] = cat.group(1)

        # Verified
        result["verificado"] = (
            '"is_verified":true' in html or
            '"is_verified": true' in html or
            '"isVerified":true' in html
        )

    except Exception as exc:
        _log.warning("Instagram scrape failed for @%s: %s", handle, exc)

    return result


def find_and_scrape(company_name: str, website: str = "") -> dict:
    """Find the Instagram handle via Google, then scrape the profile."""
    handle = _google_search_instagram(company_name, website)
    if not handle:
        _log.info("Instagram: handle not found for '%s'", company_name)
        return {}

    time.sleep(random.uniform(2.0, 5.0))
    return scrape_instagram_profile(handle)


def _parse_abbrev(s: str) -> int:
    """Parse numbers like '1.2K', '3,5M', '12.000' → int."""
    s = s.strip().replace(",", ".").upper()
    try:
        if "M" in s:
            return int(float(s.replace("M", "")) * 1_000_000)
        if "K" in s:
            return int(float(s.replace("K", "")) * 1_000)
        return int(float(s.replace(".", "")))
    except (ValueError, TypeError):
        return 0
