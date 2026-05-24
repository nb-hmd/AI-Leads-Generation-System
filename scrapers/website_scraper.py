"""
Full website crawler.
Crawls up to MAX_PAGES per domain, prioritises /contact, /about, /team pages.
Extracts: email, phone, social links (Facebook, Instagram, Twitter/X, LinkedIn),
and collects full visible text for AI analysis.
"""

import re
import time
import logging
import requests
from collections import deque
from urllib.parse import urljoin, urlparse, urlunparse
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

MAX_PAGES   = 12      # Max pages to crawl per domain
MAX_TEXT    = 6000    # Max characters of text to keep for AI
TIMEOUT     = 12      # Seconds per request
CRAWL_DELAY = 0.8     # Polite delay between requests (seconds)

# URL fragments that strongly suggest a contact/about page
PRIORITY_KEYWORDS = [
    "contact", "about", "team", "reach", "touch", "connect",
    "info", "support", "help", "location", "office", "email",
]

# User-Agents to rotate through (avoids basic bot detection)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

# ─────────────────────────────────────────────────────────────────────────────
# Extraction Helpers
# ─────────────────────────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", re.I
)
# Phone: must start at a word boundary to avoid capturing stray leading digits
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?1[\s\-.]?)?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}(?!\d)"
)

# Extensions that are definitely not HTML pages
_SKIP_EXTS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp",
    ".zip", ".mp4", ".mp3", ".doc", ".docx", ".xls", ".xlsx",
    ".css", ".js", ".ico", ".xml", ".json",
}


def _get_headers(ua_index=0):
    return {
        "User-Agent":      USER_AGENTS[ua_index % len(USER_AGENTS)],
        "Accept":          "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Connection":      "keep-alive",
    }


def _normalise_url(url):
    """Strip fragments and trailing slashes for consistent de-duplication."""
    p = urlparse(url)
    # Drop fragments, normalise scheme to lowercase
    clean = urlunparse((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), "", "", ""))
    return clean


def _is_same_domain(url, base_netloc):
    return urlparse(url).netloc.lower().lstrip("www.") == base_netloc.lstrip("www.")


def _priority_score(url):
    """Higher score = crawl sooner. Contact/about pages get priority."""
    path = urlparse(url).path.lower()
    for kw in PRIORITY_KEYWORDS:
        if kw in path:
            return 1   # High priority
    return 0           # Normal priority


def _extract_emails(soup, text):
    """Find all valid emails in both href=mailto: links and page text."""
    emails = set()

    # mailto: links are most reliable
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("mailto:"):
            addr = href.replace("mailto:", "").split("?")[0].strip().lower()
            if addr and _EMAIL_RE.match(addr):
                emails.add(addr)

    # Fallback: regex on full page text
    for match in _EMAIL_RE.findall(text):
        addr = match.lower()
        # Filter out obvious false-positives (image files, example emails)
        if not any(addr.endswith(ext) for ext in (".png", ".jpg", ".gif", ".webp")):
            if "example" not in addr and "sentry" not in addr:
                emails.add(addr)

    return emails


def _extract_phones(soup, text):
    """Find phone numbers in tel: links and page text."""
    phones = set()

    # tel: links
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("tel:"):
            number = re.sub(r"[^\d+\-() ]", "", href.replace("tel:", "")).strip()
            if number:
                phones.add(number)

    # Regex on text
    for match in _PHONE_RE.findall(text):
        phones.add(match.strip())

    return phones


def _extract_socials(soup):
    """Scan all anchor hrefs for known social media domains."""
    socials = {
        "facebook":  None,
        "instagram": None,
        "twitter":   None,
        "linkedin":  None,
    }
    for a in soup.find_all("a", href=True):
        href = a["href"].lower()
        if "facebook.com" in href and not socials["facebook"]:
            socials["facebook"] = a["href"]
        elif "instagram.com" in href and not socials["instagram"]:
            socials["instagram"] = a["href"]
        elif ("twitter.com" in href or "x.com" in href) and not socials["twitter"]:
            socials["twitter"] = a["href"]
        elif "linkedin.com" in href and not socials["linkedin"]:
            socials["linkedin"] = a["href"]
    return socials


def _visible_text(soup):
    """Extract clean, visible text from a parsed page."""
    for tag in soup(["script", "style", "noscript", "meta", "head"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return re.sub(r" {2,}", " ", text)


def _collect_links(soup, current_url, base_netloc):
    """Return all internal links found on the page."""
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        full = urljoin(current_url, href)
        parsed = urlparse(full)
        # Must be http(s) and same domain
        if parsed.scheme not in ("http", "https"):
            continue
        ext = re.search(r"\.\w+$", parsed.path)
        if ext and ext.group(0).lower() in _SKIP_EXTS:
            continue
        if _is_same_domain(full, base_netloc):
            links.append(full)
    return links

# ─────────────────────────────────────────────────────────────────────────────
# Main Crawler
# ─────────────────────────────────────────────────────────────────────────────

def scrape_website(start_url: str) -> dict:
    """
    Crawl the website starting at `start_url`.
    Prioritises contact/about pages.
    Returns a dict with keys:
        success, text, email, phone, socials {facebook, instagram, twitter, linkedin}
    """
    # ── Sanitize input URL ────────────────────────────────────────────────
    if not start_url:
        return _empty(success=False)

    start_url = re.sub(r"\s+", "", start_url).strip()
    if not start_url.startswith("http"):
        start_url = "https://" + start_url

    parsed_root = urlparse(start_url)
    if not parsed_root.netloc:
        logger.error(f"Invalid URL: {start_url}")
        return _empty(success=False)

    base_netloc = parsed_root.netloc.lower().lstrip("www.")
    logger.info(f"Crawling website: {start_url}  (max {MAX_PAGES} pages)")

    # BFS queue: list of (priority, url)
    # priority 1 = contact/about page, 0 = normal page
    visited  = set()
    queue    = deque()
    queue.append((1, start_url))   # homepage goes in first

    # Accumulated results
    all_emails  = set()
    all_phones  = set()
    all_socials = {"facebook": None, "instagram": None, "twitter": None, "linkedin": None}
    all_text    = []
    pages_done  = 0
    ua_index    = 0

    while queue and pages_done < MAX_PAGES:
        # Sort queue so priority-1 items are processed first
        sorted_q = sorted(queue, key=lambda x: -x[0])
        queue = deque(sorted_q)
        _, url = queue.popleft()

        norm = _normalise_url(url)
        if norm in visited:
            continue
        visited.add(norm)

        try:
            resp = requests.get(
                url,
                headers=_get_headers(ua_index),
                timeout=TIMEOUT,
                allow_redirects=True,
            )
            ua_index += 1

            if resp.status_code == 403:
                # Try a different UA
                resp = requests.get(
                    url,
                    headers=_get_headers(ua_index + 1),
                    timeout=TIMEOUT,
                    allow_redirects=True,
                )

            if resp.status_code != 200:
                logger.debug(f"  Skipping {url} (HTTP {resp.status_code})")
                time.sleep(CRAWL_DELAY)
                continue

            # Only process HTML content
            ct = resp.headers.get("Content-Type", "")
            if "html" not in ct:
                continue

            soup = BeautifulSoup(resp.text, "lxml")
            text = _visible_text(soup)

            # Accumulate
            all_emails  |= _extract_emails(soup, text)
            all_phones  |= _extract_phones(soup, text)
            page_socials = _extract_socials(soup)
            for k, v in page_socials.items():
                if v and not all_socials[k]:
                    all_socials[k] = v

            all_text.append(text[:1500])   # Partial text per page
            pages_done += 1

            logger.debug(f"  Crawled [{pages_done}/{MAX_PAGES}]: {url}")

            # Discover new links and enqueue
            for link in _collect_links(soup, url, base_netloc):
                norm_link = _normalise_url(link)
                if norm_link not in visited:
                    priority = _priority_score(link)
                    queue.append((priority, link))

            time.sleep(CRAWL_DELAY)

        except requests.exceptions.RequestException as e:
            logger.warning(f"  Request error on {url}: {e}")
            time.sleep(CRAWL_DELAY)
            continue

    if pages_done == 0:
        logger.error(f"Failed to crawl any page from {start_url}")
        return _empty(success=False, error="No pages could be fetched")

    # ── Pick best email (prefer non-noreply) ──────────────────────────────
    chosen_email = _best_email(all_emails)

    # ── Pick best phone ───────────────────────────────────────────────────
    chosen_phone = next(iter(all_phones), None)

    # ── Merge all text ────────────────────────────────────────────────────
    merged_text = " ".join(all_text)[:MAX_TEXT]

    social_found = [k for k, v in all_socials.items() if v]
    logger.info(
        f"  Done. {pages_done} pages crawled | "
        f"Email:{chosen_email} | Phone:{chosen_phone} | "
        f"Socials:{social_found}"
    )

    return {
        "success":   True,
        "text":      merged_text,
        "email":     chosen_email,
        "phone":     chosen_phone,
        "socials":   all_socials,
    }


def _best_email(emails: set) -> str | None:
    """Prefer business emails, deprioritise noreply/support/info."""
    if not emails:
        return None
    lowpri = {"noreply", "no-reply", "donotreply", "mailer-daemon"}
    normal = [e for e in emails if not any(x in e for x in lowpri)]
    return next(iter(normal or emails), None)


def _empty(success=False, error=""):
    return {
        "success": success,
        "text":    "",
        "email":   None,
        "phone":   None,
        "socials": {"facebook": None, "instagram": None, "twitter": None, "linkedin": None},
        "error":   error,
    }
