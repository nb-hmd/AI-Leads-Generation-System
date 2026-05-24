"""
Scrape Google Maps using Playwright (bundled Chromium).
Supports continuous scrolling to load 50+ results.
No system Chrome installation required.
"""

import re
import time
import logging
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _safe_text(page, selector, timeout=3000, default=""):
    """Return inner text of first matching element or default."""
    try:
        elem = page.wait_for_selector(selector, timeout=timeout)
        return elem.inner_text().strip() if elem else default
    except Exception:
        return default


def _safe_attr(page, selector, attr, timeout=3000, default=None):
    """Return attribute value of first matching element or default."""
    try:
        elem = page.wait_for_selector(selector, timeout=timeout)
        return elem.get_attribute(attr) if elem else default
    except Exception:
        return default


def extract_rating(page):
    """
    Extract star rating from the open business detail panel.
    Tries multiple selectors and both aria-label and text content.
    Returns float between 1.0–5.0, or 0.0 if not found.
    """
    selectors = [
        "div.fontDisplayLarge",
        "span.ceNzKf",
        "div[role='img'][aria-label*='stars']",
        "span[aria-label*='stars']",
        "span[aria-label*='star']",
    ]
    for sel in selectors:
        try:
            elements = page.query_selector_all(sel)
            for elem in elements:
                # Try aria-label first: e.g. "4.7 stars"
                aria = elem.get_attribute("aria-label") or ""
                m = re.search(r"(\d+[.,]\d+|\d+)\s*stars?", aria, re.I)
                if m:
                    return float(m.group(1).replace(",", "."))
                # Try visible text: e.g. "4.7"
                text = (elem.inner_text() or "").strip().replace(",", ".")
                if re.match(r"^\d+\.?\d*$", text):
                    val = float(text)
                    if 1.0 <= val <= 5.0:
                        return val
        except Exception:
            continue
    return 0.0


def extract_website(page):
    """
    Extract the business website from the open detail panel.
    Skips internal Google URLs.
    """
    selectors = [
        "a[data-item-id='authority']",
        "div[data-item-id='authority'] a",
        "a[aria-label*='website' i]",
        "a[data-tooltip*='website' i]",
    ]
    for sel in selectors:
        try:
            elements = page.query_selector_all(sel)
            for elem in elements:
                href = elem.get_attribute("href") or ""
                if href.startswith("http") and "google" not in href:
                    return href
                # Visible domain text fallback
                text = (elem.inner_text() or "").strip()
                if text and "." in text and " " not in text:
                    return f"https://{text}"
        except Exception:
            continue
    return None


def extract_phone(page):
    """Extract phone number from the business details panel."""
    for sel in [
        "button[data-item-id^='phone']",
        "button[aria-label*='phone' i]",
    ]:
        text = _safe_text(page, sel, timeout=2000)
        if text:
            return text
    return None


def extract_address(page):
    """Extract street address from the business details panel."""
    for sel in [
        "button[data-item-id^='address']",
        "button[data-tooltip*='address' i]",
        "div[data-item-id^='address']",
    ]:
        text = _safe_text(page, sel, timeout=2000)
        if text:
            return text
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar Scroll — Deep scroll to load ALL results
# ─────────────────────────────────────────────────────────────────────────────

def _count_sidebar_cards(page):
    """Count unique result cards currently loaded in the sidebar."""
    anchors = page.query_selector_all("div[role='feed'] a[href*='/maps/place/']")
    seen = set()
    for a in anchors:
        href = a.get_attribute("href") or ""
        key = href.split("?")[0]
        if key:
            seen.add(key)
    return len(seen)


def _is_end_of_list(page):
    """
    Detect if Google Maps shows the 'end of list' indicator.
    This appears as a span with specific text or a themed divider
    at the bottom of the feed after all results are loaded.
    """
    try:
        # Google shows "You've reached the end of the list." in various selectors
        end_markers = page.query_selector_all(
            "span.HlvSq, p.fontBodyMedium, div[role='feed'] > div:last-child"
        )
        for el in end_markers:
            text = (el.inner_text() or "").strip().lower()
            if any(phrase in text for phrase in [
                "end of the list", "you've reached", "no more results",
                "end of list", "can't find"
            ]):
                return True
    except Exception:
        pass
    return False


def scroll_sidebar(page, target_count=10, max_scrolls=80):
    """
    Scroll the results sidebar repeatedly to load up to `target_count` results.

    Google Maps lazy-loads results in batches (~7-20 per batch). This function:
    1. Scrolls the feed container by large increments
    2. Waits for new results to appear
    3. Detects the "end of list" marker to stop early
    4. Stops if no new results appear after several scroll attempts (stale)
    """
    feed_sel = "div[role='feed']"
    try:
        feed = page.query_selector(feed_sel)
        if not feed:
            logger.warning("Could not find results feed element.")
            return

        prev_count = 0
        stale_rounds = 0
        MAX_STALE = 6  # Stop after 6 scrolls with no new results

        for scroll_i in range(max_scrolls):
            current_count = _count_sidebar_cards(page)

            if current_count >= target_count:
                logger.info(f"  Reached target: {current_count} results loaded.")
                break

            if _is_end_of_list(page):
                logger.info(
                    f"  End of list reached after {current_count} results."
                )
                break

            # Check for stale scrolling (no new results appearing)
            if current_count == prev_count:
                stale_rounds += 1
                if stale_rounds >= MAX_STALE:
                    logger.info(
                        f"  No new results after {MAX_STALE} scrolls. "
                        f"Stopping at {current_count} results."
                    )
                    break
            else:
                stale_rounds = 0

            prev_count = current_count

            # Scroll down by a large chunk
            feed.evaluate("el => el.scrollBy(0, 1200)")
            time.sleep(1.5)

            # Every 5th scroll, do a bigger jump to trigger batch loading
            if scroll_i % 5 == 4:
                feed.evaluate("el => el.scrollTo(0, el.scrollHeight)")
                time.sleep(2.0)

        final = _count_sidebar_cards(page)
        logger.info(f"  Sidebar scroll complete: {final} unique results loaded.")

    except Exception as e:
        logger.warning(f"Sidebar scroll error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Main Scraper
# ─────────────────────────────────────────────────────────────────────────────

def scrape_google_maps(search_query: str, max_results: int = 10) -> list[dict]:
    """
    Scrape Google Maps for businesses matching `search_query` using Playwright.
    Uses the bundled Chromium — no system Chrome required.

    Now supports scrolling to load 50+ results when available.

    Returns a list of dicts with keys:
        name, email, website, phone, address, rating,
        linkedin, twitter, instagram
    """
    logger.info(f"Starting Google Maps scrape for query: '{search_query}'")
    leads = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--lang=en-US",
                "--window-size=1920,1080",
            ],
        )

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()

        # Hide webdriver flag
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        try:
            url = f"https://www.google.com/maps/search/{search_query.replace(' ', '+')}"
            page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # Accept cookies popup if it appears (EU users)
            try:
                accept_btn = page.wait_for_selector(
                    "button[aria-label*='Accept' i], form[action*='consent'] button",
                    timeout=4000,
                )
                if accept_btn:
                    accept_btn.click()
                    time.sleep(1)
            except Exception:
                pass

            # Wait for the results sidebar feed
            try:
                page.wait_for_selector("div[role='feed']", timeout=20000)
                logger.info("Results sidebar loaded.")
            except PlaywrightTimeout:
                logger.error("Timed out waiting for Google Maps results feed.")
                return leads

            # ── Deep scroll to load ALL available results ──────────────────
            logger.info(
                f"Scrolling sidebar to load up to {max_results} results..."
            )
            scroll_sidebar(page, target_count=max_results, max_scrolls=80)

            # Collect unique sidebar result links (scoped strictly to the feed)
            all_anchors = page.query_selector_all(
                "div[role='feed'] a[href*='/maps/place/']"
            )

            # De-duplicate by URL prefix (before query params) and collect stable URLs
            seen_keys = set()
            unique_places = []
            for anchor in all_anchors:
                href = anchor.get_attribute("href") or ""
                key = href.split("?")[0]
                if key and key not in seen_keys:
                    seen_keys.add(key)
                    unique_places.append(href)

            logger.info(f"Found {len(unique_places)} unique sidebar result cards.")

            if not unique_places:
                logger.warning(
                    "No sidebar cards found. Google Maps layout may have changed."
                )
                return leads

            # Process each result
            for i in range(min(len(unique_places), max_results)):
                target_href = unique_places[i]
                target_key = target_href.split("?")[0]
                
                try:
                    # Re-query all anchors freshly from the DOM to avoid stale references (DOM detachment)
                    current_anchors = page.query_selector_all(
                        "div[role='feed'] a[href*='/maps/place/']"
                    )
                    
                    # Find the fresh ElementHandle matching our target place key
                    anchor = None
                    for a in current_anchors:
                        href = a.get_attribute("href") or ""
                        if href.split("?")[0] == target_key:
                            anchor = a
                            break
                            
                    if not anchor:
                        # Fallback: scroll feed container slightly to reveal element if virtual scrolling hid it
                        feed = page.query_selector("div[role='feed']")
                        if feed:
                            # Scroll container to estimated position
                            feed.evaluate(f"el => el.scrollTo(0, {max(0, (i - 2) * 150)})")
                            time.sleep(1.0)
                            
                        # Try re-querying one more time after scrolling
                        current_anchors = page.query_selector_all(
                            "div[role='feed'] a[href*='/maps/place/']"
                        )
                        for a in current_anchors:
                            href = a.get_attribute("href") or ""
                            if href.split("?")[0] == target_key:
                                anchor = a
                                break
                                
                    if not anchor:
                        logger.warning(f"Could not find element for result {i+1} in DOM, skipping.")
                        continue

                    # Scroll the card into view and click
                    anchor.scroll_into_view_if_needed()
                    time.sleep(0.4)
                    anchor.click()

                    # Wait for the business name h1 in the detail panel
                    detail_name_sel = "h1.DUwDvf, h1"
                    try:
                        page.wait_for_selector(detail_name_sel, timeout=12000)
                    except PlaywrightTimeout:
                        logger.warning(
                            f"Detail panel did not load for result {i+1}, skipping."
                        )
                        page.keyboard.press("Escape")
                        time.sleep(1)
                        continue

                    time.sleep(2)  # Allow all async fields to render

                    # ── Extract data ──────────────────────────────────────
                    name = _safe_text(page, "h1.DUwDvf") or _safe_text(page, "h1")

                    # Skip invalid / placeholder names
                    if not name or name.strip().lower() in ("results", ""):
                        logger.warning(
                            f"Skipping result {i+1}: invalid name '{name}'"
                        )
                        page.keyboard.press("Escape")
                        time.sleep(1)
                        continue

                    rating  = extract_rating(page)
                    website = extract_website(page)
                    phone   = extract_phone(page)
                    address = extract_address(page)

                    lead = {
                        "name":      name,
                        "email":     None,   # Extracted later from the website
                        "website":   website,
                        "phone":     phone,
                        "address":   address,
                        "rating":    rating,
                        "linkedin":  None,
                        "twitter":   None,
                        "instagram": None,
                    }

                    logger.info(
                        f"  [{i+1}/{min(len(unique_places), max_results)}] "
                        f"{name} | Rating:{rating} | URL:{website}"
                    )
                    leads.append(lead)

                except Exception as e:
                    logger.error(f"Error processing result {i+1}: {e}")
                finally:
                    # Close detail panel and return to sidebar list
                    try:
                        page.keyboard.press("Escape")
                        time.sleep(1.2)
                    except Exception:
                        pass

        except Exception as e:
            logger.error(f"Fatal error during Google Maps scraping: {e}")
        finally:
            browser.close()

    logger.info(f"Scraped {len(leads)} leads from Google Maps.")
    return leads


# ─────────────────────────────────────────────────────────────────────────────
# Multi-Query Geographic Expansion
# Google Maps caps results at ~20 per query.
# To reach 50–100+ leads, we split the city into sub-areas automatically
# and run a separate search for each sub-area, then merge & deduplicate.
# ─────────────────────────────────────────────────────────────────────────────

# Known sub-areas for major cities. Extend as needed.
_GEO_EXPANSIONS: dict[str, list[str]] = {
    # UK
    "london":           ["Central London", "East London", "West London",
                         "North London", "South London", "Canary Wharf",
                         "Shoreditch", "Kensington", "Camden", "Hackney",
                         "Brixton", "Greenwich", "Islington", "Fulham",
                         "Hammersmith", "Stratford", "Croydon"],
    "manchester":       ["Central Manchester", "Salford", "Trafford",
                         "Stockport", "Bury", "Bolton", "Oldham"],
    "birmingham":       ["Central Birmingham", "Solihull", "Coventry",
                         "Wolverhampton", "Walsall"],
    "leeds":            ["Central Leeds", "Bradford", "Wakefield",
                         "Harrogate", "Huddersfield"],
    "glasgow":          ["Central Glasgow", "East Glasgow", "West Glasgow",
                         "Paisley", "Hamilton"],
    "edinburgh":        ["Central Edinburgh", "Leith", "Morningside",
                         "Portobello"],
    # US
    "new york":         ["Manhattan", "Brooklyn", "Queens", "Bronx",
                         "Staten Island", "Hoboken NJ", "Jersey City NJ"],
    "los angeles":      ["Hollywood", "Beverly Hills", "Santa Monica",
                         "Downtown Los Angeles", "Burbank", "Pasadena",
                         "Long Beach", "Glendale"],
    "dallas":           ["Uptown Dallas TX", "North Dallas TX",
                         "Downtown Dallas TX", "Irving TX",
                         "Plano TX", "Frisco TX", "McKinney TX",
                         "Arlington TX", "Garland TX"],
    "houston":          ["Downtown Houston TX", "Katy TX", "Sugar Land TX",
                         "Pearland TX", "The Woodlands TX"],
    "chicago":          ["Downtown Chicago", "Lincoln Park Chicago",
                         "Hyde Park Chicago", "Evanston IL", "Oak Park IL"],
    "miami":            ["Downtown Miami", "Coral Gables FL", "Brickell Miami",
                         "Miami Beach FL", "Doral FL", "Hialeah FL"],
    "phoenix":          ["Downtown Phoenix AZ", "Scottsdale AZ", "Tempe AZ",
                         "Mesa AZ", "Chandler AZ", "Glendale AZ"],
    "san francisco":    ["Downtown San Francisco", "Oakland CA",
                         "Berkeley CA", "San Jose CA", "Palo Alto CA"],
    "seattle":          ["Downtown Seattle", "Bellevue WA", "Redmond WA",
                         "Kirkland WA", "Tacoma WA"],
    "atlanta":          ["Downtown Atlanta", "Buckhead Atlanta",
                         "Marietta GA", "Sandy Springs GA", "Decatur GA"],
    # Canada
    "toronto":          ["Downtown Toronto", "Mississauga", "Brampton",
                         "Scarborough", "North York", "Etobicoke"],
    "vancouver":        ["Downtown Vancouver", "Burnaby", "Surrey",
                         "Richmond BC", "North Vancouver"],
    # Australia
    "sydney":           ["CBD Sydney", "Parramatta", "Bondi",
                         "Chatswood", "Hornsby"],
    "melbourne":        ["CBD Melbourne", "St Kilda", "Fitzroy",
                         "Richmond Melbourne", "Docklands"],
}

# Common business-type synonym groups
_SYNONYMS: dict[str, list[str]] = {
    "real estate":          ["estate agents", "property agents", "realtors",
                             "property consultants"],
    "estate agents":        ["real estate agents", "property agents",
                             "property consultants"],
    "roofers":              ["roofing contractors", "roofing company",
                             "roof repair"],
    "plumbers":             ["plumbing contractors", "plumbing services"],
    "dentists":             ["dental clinics", "dental practice"],
    "lawyers":              ["law firms", "solicitors", "legal services"],
    "accountants":          ["accounting firms", "chartered accountants",
                             "bookkeepers"],
    "gyms":                 ["fitness centres", "health clubs"],
    "restaurants":          ["cafes", "bistros", "eateries"],
    "architects":           ["architecture firms", "architectural services"],
    "interior designers":   ["interior design studios", "home designers"],
    "digital marketing":    ["marketing agencies", "seo agencies",
                             "advertising agencies"],
    "electricians":         ["electrical contractors", "electrical services"],
    "builders":             ["construction companies", "building contractors"],
    "photographers":        ["photography studios", "wedding photographers"],
}


def _get_sub_areas(location: str) -> list[str]:
    """Return a list of sub-area search strings for the given location."""
    key = location.lower().strip()
    # Strip country codes like ", UK" or ", TX" for matching
    base = key.split(",")[0].strip()
    for city_key, areas in _GEO_EXPANSIONS.items():
        if city_key in base or base in city_key:
            return areas
    # Unknown city — use generic directional split
    city = location.split(",")[0].strip()
    return [
        f"Central {city}",
        f"East {city}",
        f"West {city}",
        f"North {city}",
        f"South {city}",
    ]


def _get_synonyms(business_type: str) -> list[str]:
    """Return synonym search terms for a given business type."""
    key = business_type.lower().strip()
    for biz_key, syns in _SYNONYMS.items():
        if biz_key in key or key in biz_key:
            return syns
    return []


def scrape_with_expansion(
    business_type: str,
    location: str,
    max_results: int = 20,
) -> list[dict]:
    """
    Scrape Google Maps for up to `max_results` leads by automatically
    running multiple queries across geographic sub-areas.

    Strategy:
    1. Run the original query  (e.g. "Real Estate in London")
    2. If still short, run sub-area queries  (e.g. "Real Estate in East London")
    3. If still short, run business synonym queries  (e.g. "Estate Agents in London")
    4. Merge and deduplicate all results by website URL

    Returns a deduplicated list of up to `max_results` lead dicts.
    """
    seen_websites: set[str] = set()
    all_leads: list[dict] = []

    def _add_leads(new_leads: list[dict]) -> None:
        for lead in new_leads:
            if len(all_leads) >= max_results:
                break
            key = (lead.get("website") or lead.get("name") or "").lower().strip()
            # Normalise URL key (strip trailing slash and params)
            key = key.split("?")[0].rstrip("/")
            if key and key not in seen_websites:
                seen_websites.add(key)
                all_leads.append(lead)

    def _remaining() -> int:
        return max_results - len(all_leads)

    # ── Round 1: Original query ────────────────────────────────────────────
    original_query = f"{business_type} in {location}"
    logger.info(f"[Expansion] Round 1 — Original query: '{original_query}'")
    r1 = scrape_google_maps(original_query, max_results=min(_remaining() + 5, 20))
    _add_leads(r1)
    logger.info(f"[Expansion] After Round 1: {len(all_leads)}/{max_results} leads")

    if len(all_leads) >= max_results:
        return all_leads

    # ── Round 2: Geographic sub-areas ─────────────────────────────────────
    sub_areas = _get_sub_areas(location)
    logger.info(
        f"[Expansion] Round 2 — {len(sub_areas)} geographic sub-areas for '{location}'"
    )
    for area in sub_areas:
        if _remaining() <= 0:
            break
        query = f"{business_type} in {area}"
        logger.info(f"[Expansion]   Sub-area query: '{query}' (need {_remaining()} more)")
        leads = scrape_google_maps(query, max_results=min(_remaining() + 5, 20))
        _add_leads(leads)
        logger.info(f"[Expansion]   Running total: {len(all_leads)}/{max_results}")

    if len(all_leads) >= max_results:
        return all_leads

    # ── Round 3: Business type synonyms ───────────────────────────────────
    synonyms = _get_synonyms(business_type)
    if synonyms:
        logger.info(
            f"[Expansion] Round 3 — {len(synonyms)} synonym queries for '{business_type}'"
        )
        for syn in synonyms:
            if _remaining() <= 0:
                break
            query = f"{syn} in {location}"
            logger.info(f"[Expansion]   Synonym query: '{query}' (need {_remaining()} more)")
            leads = scrape_google_maps(query, max_results=min(_remaining() + 5, 20))
            _add_leads(leads)
            logger.info(f"[Expansion]   Running total: {len(all_leads)}/{max_results}")

    logger.info(
        f"[Expansion] Complete — {len(all_leads)} unique leads collected "
        f"(target was {max_results})"
    )
    return all_leads
