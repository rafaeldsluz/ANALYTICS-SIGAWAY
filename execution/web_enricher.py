"""
Website contact enricher.
Visits a company's website and extracts emails, phones, and social links.
"""
import re
import time
import urllib.parse

_EMAIL_RE  = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
_PHONE_RE  = re.compile(r'(?:\+?55\s?)?(?:\(?\d{2}\)?\s?)(?:9\d{4}|\d{4})[\s\-]?\d{4}')
_SOCIAL_RE = {
    "instagram": re.compile(r'instagram\.com/([A-Za-z0-9_.]{2,30})(?:/|\b)'),
    "linkedin":  re.compile(r'linkedin\.com/(?:company|in)/([A-Za-z0-9_\-]{2,60})'),
}

_SPAM_DOMAINS = {
    "example.com", "domain.com", "email.com", "wixpress.com",
    "sentry.io", "amazonaws.com", "google.com", "microsoft.com",
    "apple.com", "w3.org", "schema.org", "jquery.com",
}
_SPAM_PREFIXES = {"noreply", "no-reply", "donotreply", "mailer-daemon", "postmaster"}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}


def enrich_website(url: str, timeout: int = 8) -> dict:
    """Fetch a company website and extract contact/social data."""
    if not url or not url.startswith(("http://", "https://")):
        return {}

    import requests

    result = {"email": "", "instagram": "", "linkedin": ""}

    parsed = urllib.parse.urlparse(url)
    base   = f"{parsed.scheme}://{parsed.netloc}"
    pages  = [url] + [base + p for p in ("/contato", "/contact", "/sobre", "/about")]

    collected = ""
    for page_url in pages[:3]:
        try:
            r = requests.get(page_url, timeout=timeout, headers=_HEADERS, allow_redirects=True)
            if r.status_code == 200:
                collected += r.text + "\n"
        except Exception:
            pass
        time.sleep(0.3)

    if not collected:
        return result

    # Emails
    candidates = _EMAIL_RE.findall(collected)
    valid = []
    for e in dict.fromkeys(candidates):  # preserve order, deduplicate
        e_low = e.lower()
        domain = e_low.split("@")[-1]
        prefix = e_low.split("@")[0]
        if (
            domain not in _SPAM_DOMAINS
            and prefix not in _SPAM_PREFIXES
            and not e_low.endswith((".png", ".jpg", ".gif", ".svg", ".webp"))
            and "." in domain
        ):
            valid.append(e)
    if valid:
        result["email"] = valid[0]

    # Social links
    for platform, rx in _SOCIAL_RE.items():
        m = rx.search(collected)
        if m:
            result[platform] = f"https://{platform}.com/{m.group(1)}"

    return result
