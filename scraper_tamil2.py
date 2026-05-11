"""
scraper_tamildhool.py — TamilDhool multi-channel scraper
Channels : Sun TV | Vijay TV | Zee Tamil
Saves output to:
  data/serials_tamil_suntv_YYYY-MM-DD.json
  data/serials_tamil_vijaytv_YYYY-MM-DD.json
  data/serials_tamil_zeetamil_YYYY-MM-DD.json
Run locally:  python scraper_tamildhool.py

Requirements:
  pip install requests beautifulsoup4 playwright
  playwright install chromium
"""

import re
import json
import time
import logging
import argparse
import os
from dataclasses import dataclass, asdict, field
from typing import Optional
from datetime import date, timedelta
from urllib.parse import urlparse as _urlparse
import glob

import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ─── Channel config ───────────────────────────────────────────────────────────

CHANNELS = {
    "suntv": {
        "label": "Sun TV",
        "pages": [
            "https://www.tamildhool.tech/sun-tv/sun-tv-serial/",
            "https://www.tamildhool.tech/sun-tv/sun-tv-serial/page/2/",
        ],
        "filename": "serials_tamil_suntv_{date}.json",
    },
    "vijaytv": {
        "label": "Vijay TV",
        "pages": [
            "https://www.tamildhool.tech/vijay-tv/vijay-tv-serial/",
            "https://www.tamildhool.tech/vijay-tv/vijay-tv-serial/page/2/",
        ],
        "filename": "serials_tamil_vijaytv_{date}.json",
    },
    "zeetamil": {
        "label": "Zee Tamil",
        "pages": [
            "https://www.tamildhool.tech/zee-tamil/zee-tamil-serial/",
            "https://www.tamildhool.tech/zee-tamil/zee-tamil-serial/page/2/",
        ],
        "filename": "serials_tamil_zeetamil_{date}.json",
    },
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.tamildhool.tech/",
}

DELAY   = 1.0
TIMEOUT = 15

# ─── HLS interception ────────────────────────────────────────────────────────
#
# We ONLY want:  coke.infamous.network/stream/variant/...
#
# The old pattern r"infamous\.network" was too broad — it also matched
# thumbnail/image requests served from the same CDN domain, so Playwright
# captured a thumbnail URL before the real m3u8 ever fired.
#
# Rules (applied in order inside the route handler):
#   1. URL must contain "infamous.network"  → it's from the right CDN
#   2. URL must contain "/stream/variant/"  → it's the variant playlist, not an image
#   3. URL must end with ".m3u8"            → belt-and-suspenders check
#
# groovy.monster entries are .ts/.mp4 segments — we don't need to capture
# those, only the playlist that references them.

def _is_variant_m3u8(url: str) -> bool:
    """
    Return True only for the HLS variant playlist we actually want.
    Rejects thumbnails, master playlists, and segment files from the same CDN.
    """
    u = url.lower()
    return (
        "infamous.network" in u
        and "/stream/variant/" in u
        and u.endswith(".m3u8")
    )

# How long to wait for the m3u8 request after page load (seconds)
PLAYWRIGHT_TIMEOUT_SEC = 25


# ─── Data model ───────────────────────────────────────────────────────────────

@dataclass
class Serial:
    title:           str
    href:            str
    srcset:          list = field(default_factory=list)   # [webp_url, jpg_url]
    dailymotion_id:  Optional[str] = None
    dailymotion_url: Optional[str] = None
    jwplayer_url:    Optional[str] = None                 # variant m3u8 playlist
    error:           Optional[str] = None


# ─── HTTP session ─────────────────────────────────────────────────────────────

session = requests.Session()
session.headers.update(HEADERS)


def get(url: str, retries: int = 2, extra_headers: dict = None) -> Optional[requests.Response]:
    headers = extra_headers or {}
    for attempt in range(retries + 1):
        try:
            r = session.get(url, timeout=TIMEOUT, allow_redirects=True, headers=headers)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            log.warning(f"  [attempt {attempt+1}] {url} → {e}")
            if attempt < retries:
                time.sleep(2)
    return None


# ─── Helpers ──────────────────────────────────────────────────────────────────

def target_date_str(for_date: date) -> str:
    """Return date as DD-MM-YYYY (format used in serial titles)."""
    return for_date.strftime("%d-%m-%Y")


# ─── Phase 1: scrape listing pages ───────────────────────────────────────────

def fetch_serials(channel_key: str, filter_date: date) -> list[Serial]:
    """
    Scrape both listing pages for the given channel and return serials
    matching the target date.
    """
    channel  = CHANNELS[channel_key]
    date_str = target_date_str(filter_date)
    log.info(f"\n[{channel['label']}] Scraping 2 pages — filtering for {date_str}")

    all_serials: list[Serial] = []
    seen_hrefs: set[str] = set()

    for page_url in channel["pages"]:
        log.info(f"  Fetching: {page_url}")
        r = get(page_url)
        if not r:
            log.warning(f"  Could not fetch {page_url}, skipping")
            continue

        soup = BeautifulSoup(r.text, "html.parser")

        for article in soup.select("article.regular-post"):
            thumb_a = article.select_one("div.post-thumb a[href]")
            if not thumb_a:
                continue

            href  = thumb_a["href"].strip()
            title = thumb_a.get("title", "").strip()
            if not title:
                h3 = article.select_one("h3.entry-title a")
                title = h3.get_text(strip=True) if h3 else href

            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)

            srcset_urls: list[str] = []
            picture = thumb_a.find("picture")
            if picture:
                source = picture.find("source", srcset=True)
                if source:
                    srcset_urls.append(source["srcset"].strip())
                img = picture.find("img", src=True)
                if img:
                    srcset_urls.append(img["src"].strip())

            all_serials.append(Serial(title=title, href=href, srcset=srcset_urls))

        time.sleep(DELAY)

    log.info(f"  Total cards across both pages: {len(all_serials)}")

    filtered = [s for s in all_serials if date_str in s.title]
    log.info(f"  After date filter ({date_str}): {len(filtered)} serials")
    for s in filtered:
        log.info(f"    ✓ {s.title}")

    return filtered


# ─── Phase 2: scrape episode page for video links ────────────────────────────

def _extract_dm_from_figure(figure) -> tuple[Optional[str], Optional[str]]:
    a = figure.select_one("a[href]")
    if a:
        m = re.search(r"[?&]video=([A-Za-z0-9]+)", a["href"])
        if m:
            return f"https://www.dailymotion.com/embed/video/{m.group(1)}", m.group(1)

    img = figure.select_one("img[src]")
    if img:
        m = re.search(r"/video/([A-Za-z0-9]+)", img["src"])
        if m:
            return f"https://www.dailymotion.com/embed/video/{m.group(1)}", m.group(1)

    return None, None


def _intercept_hls_with_playwright(jw_href: str, episode_url: str) -> Optional[str]:
    """
    Launch a headless browser, follow the JS redirect chain from the JW Player
    card link to the thrfive.io embed, and capture the variant m3u8 URL that
    HLS.js requests at runtime.

    What changed vs the previous version
    ─────────────────────────────────────
    OLD: HLS_INTERCEPT_PATTERNS included r"infamous\\.network" which matched
         ANY request to that CDN — including thumbnail images that load before
         the m3u8.  The route handler captured the first match (a thumbnail)
         and returned it, so jwplayer_url ended up as an image URL.

    NEW: The route handler calls _is_variant_m3u8(url) which requires ALL of:
           • "infamous.network" in the URL          (right CDN)
           • "/stream/variant/" in the URL          (right path — not an image)
           • URL ends with ".m3u8"                  (right file type)
         This means thumbnails (e.g. .jpg/.webp served from infamous.network)
         are explicitly ignored and only the real variant playlist is captured.

    Additionally, the final URL selection no longer uses min(key=len) — which
    would pick the shortest URL (often a thumbnail or redirect).  Instead it
    picks the longest URL among captured m3u8 candidates, which corresponds to
    the fully-signed variant playlist path.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        log.error(
            "Playwright is not installed.  "
            "Run:  pip install playwright && playwright install chromium"
        )
        return None

    captured: list[str] = []
    log.info(f"    PW: launching browser → {jw_href}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-web-security",
                "--autoplay-policy=no-user-gesture-required",
            ],
        )
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            viewport={"width": 1280, "height": 800},
        )

        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        # ── Route handler: only capture the variant m3u8 ─────────────────────
        # Runs at context level so iframe (thrfive.io) traffic is included.
        def handle_route(route, request):
            url = request.url

            if _is_variant_m3u8(url) and not captured:
                log.info(f"    PW: captured variant m3u8 → {url[:120]}…")
                captured.append(url)

            route.continue_()

        context.route("**/*", handle_route)
        page = context.new_page()

        try:
            # ── Step 1: load episode page first so Referer is set ────────────
            try:
                page.goto(episode_url, wait_until="domcontentloaded", timeout=15_000)
                log.info(f"    PW: loaded episode referer page")
            except PWTimeout:
                log.warning("    PW: episode page timed out — continuing anyway")

            # ── Step 2: navigate to jw_href (tamilbliss / teamstoday etc.) ───
            # The browser follows the JS redirect chain naturally:
            #   teamstoday.com → futuregentrends.com → thrfive.io iframe
            # requests cannot follow JS/meta-refresh redirects, so we must
            # use a real browser here.
            log.info(f"    PW: navigating to JW href → {jw_href}")
            try:
                page.goto(
                    jw_href,
                    wait_until="domcontentloaded",
                    timeout=PLAYWRIGHT_TIMEOUT_SEC * 1000,
                    referer=episode_url,
                )
            except PWTimeout:
                log.warning("    PW: domcontentloaded timed out — reading URL anyway")

            # ── Step 3: wait for JS redirect away from source host ───────────
            src_host = _urlparse(jw_href).netloc
            try:
                page.wait_for_function(
                    f"() => !window.location.href.includes({src_host!r})",
                    timeout=12_000,
                )
            except PWTimeout:
                pass

            final_url = page.url
            log.info(f"    PW: final landing URL → {final_url}")

            try:
                page.wait_for_load_state("domcontentloaded", timeout=10_000)
            except PWTimeout:
                pass

            # ── Step 4: dismiss the #slp-overlay "Continue" popup ────────────
            # This overlay intercepts the first video click and opens a
            # smartlink tab.  We click the button directly so the proxy
            # interceptors are removed and the player initialises freely.
            log.info("    PW: looking for #slp-continue overlay …")
            try:
                slp_btn = page.wait_for_selector("#slp-continue", timeout=6_000)
                if slp_btn:
                    slp_btn.click()
                    log.info("    PW: clicked #slp-continue — overlay dismissed")
                    time.sleep(1.0)
            except PWTimeout:
                log.info("    PW: #slp-continue not found — overlay absent")

            # ── Step 5: poll for variant m3u8 ────────────────────────────────
            # thrfive.io's HLS.js auto-initialises after the overlay is
            # dismissed.  The variant playlist request fires within a few
            # seconds of the iframe loading.
            log.info("    PW: polling for variant m3u8 …")
            deadline = time.time() + PLAYWRIGHT_TIMEOUT_SEC
            while not captured and time.time() < deadline:
                time.sleep(0.3)

            # ── Step 6: click iframe video if still nothing ───────────────────
            if not captured:
                log.info("    PW: no m3u8 yet — clicking thrfive iframe video …")
                try:
                    frame = page.frame_locator("iframe[src*='thrfive.io']")
                    frame.locator("video").first.click(timeout=5_000)
                    log.info("    PW: clicked iframe video")
                except Exception as ex:
                    log.warning(f"    PW: iframe click failed — {ex}")
                    try:
                        page.locator("video").first.click(timeout=3_000)
                        log.info("    PW: clicked top-level video element")
                    except Exception:
                        pass

                extra_deadline = time.time() + 12
                while not captured and time.time() < extra_deadline:
                    time.sleep(0.3)

        except PWTimeout:
            log.warning("    PW: navigation timed out")
        except Exception as ex:
            log.warning(f"    PW: unexpected error — {ex}")
        finally:
            context.close()
            browser.close()

    if captured:
        # All captured URLs are already filtered to variant m3u8 only.
        # Pick the longest in case multiple fired (e.g. after a quality switch);
        # the longest is the most fully-signed playlist path.
        chosen = max(captured, key=len)
        log.info(f"    PW: using → {chosen[:120]}…")
        return chosen

    log.warning("    PW: no variant m3u8 intercepted within timeout")
    return None


def fetch_video_links(serial: Serial) -> None:
    """
    Open the episode page and extract video links from the two figure cards.
    """
    log.info(f"  Fetching episode page: {serial.href}")
    r = get(serial.href)
    if not r:
        serial.error = "episode page unreachable"
        return

    soup = BeautifulSoup(r.text, "html.parser")

    jw_href: Optional[str] = None

    for figure in soup.select("figure.td-featured-thumb"):
        label_tag = figure.select_one("div.td-source-label")
        if not label_tag:
            continue
        label = label_tag.get_text(strip=True).lower()

        if "dailymotion" in label:
            embed_url, vid_id = _extract_dm_from_figure(figure)
            if embed_url:
                serial.dailymotion_id  = vid_id
                serial.dailymotion_url = embed_url
                log.info(f"  Dailymotion → {embed_url}")

        elif "jw" in label:
            a = figure.select_one("a[href]")
            if a:
                jw_href = a["href"].strip()
                log.info(f"  JW Player card href: {jw_href}")

    if not serial.dailymotion_url:
        log.info("  No Dailymotion — attempting Playwright HLS interception …")
        if jw_href:
            serial.jwplayer_url = _intercept_hls_with_playwright(jw_href, serial.href)
        else:
            log.warning("  No JW Player href found on episode page")

    if not serial.dailymotion_url and not serial.jwplayer_url:
        serial.error = "no video links found"
        log.warning(f"  ✗ No video links for: {serial.title}")


# ─── Orchestration ────────────────────────────────────────────────────────────

def run_channel(channel_key: str, filter_date: date, limit: int = 0) -> list[Serial]:
    serials = fetch_serials(channel_key, filter_date)

    if not serials:
        log.warning(f"  No serials found for {CHANNELS[channel_key]['label']} on {target_date_str(filter_date)}")
        return []

    if limit:
        serials = serials[:limit]

    log.info(f"\n  Phase 2: fetching video links for {len(serials)} serials …")
    for i, serial in enumerate(serials, 1):
        log.info(f"  [{i}/{len(serials)}] {serial.title}")
        fetch_video_links(serial)
        time.sleep(DELAY)

    return serials


# ─── Persistence ──────────────────────────────────────────────────────────────

def save_json(results: list[Serial], channel_key: str, output_dir: str = "data") -> str:
    os.makedirs(output_dir, exist_ok=True)
    today    = date.today().isoformat()
    filename = CHANNELS[channel_key]["filename"].format(date=today)
    filepath = os.path.join(output_dir, filename)

    payload = {
        "date":    today,
        "channel": CHANNELS[channel_key]["label"],
        "total":   len(results),
        "found":   sum(1 for s in results if s.dailymotion_url or s.jwplayer_url),
        "serials": [asdict(s) for s in results],
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    log.info(f"Saved → {filepath}")
    return filepath


def cleanup_old_files(output_dir: str = "data", keep_days: int = 30):
    cutoff  = date.today() - timedelta(days=keep_days)
    deleted = 0
    pattern = os.path.join(output_dir, "serials_tamil_*.json")
    for jf in glob.glob(pattern):
        fname = os.path.basename(jf)
        m = re.search(r"(\d{4}-\d{2}-\d{2})\.json$", fname)
        if not m:
            continue
        try:
            file_date = date.fromisoformat(m.group(1))
            if file_date < cutoff:
                os.remove(jf)
                log.info(f"Deleted old file: {fname}")
                deleted += 1
        except ValueError:
            pass
    log.info(f"Cleanup done — {deleted} files deleted")


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TamilDhool multi-channel serial scraper")
    parser.add_argument(
        "--channels",
        nargs="+",
        choices=list(CHANNELS.keys()) + ["all"],
        default=["all"],
        help="Which channels to scrape (default: all)",
    )
    parser.add_argument("--limit",  type=int, default=0,      help="Cap serials per channel for testing (0 = all)")
    parser.add_argument("--output", type=str, default="data", help="Output directory")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Target date as YYYY-MM-DD (default: yesterday)",
    )
    args = parser.parse_args()

    channels_to_run = list(CHANNELS.keys()) if "all" in args.channels else args.channels

    filter_date = (
        date.fromisoformat(args.date)
        if args.date
        else date.today() - timedelta(days=1)
    )

    log.info(f"Channels   : {', '.join(channels_to_run)}")
    log.info(f"Date filter: {target_date_str(filter_date)}")

    summary: dict[str, list[Serial]] = {}

    for channel_key in channels_to_run:
        results = run_channel(channel_key, filter_date=filter_date, limit=args.limit)
        summary[channel_key] = results
        if results:
            save_json(results, channel_key, output_dir=args.output)

    cleanup_old_files(output_dir=args.output)

    print(f"\n{'─'*55}")
    print(f"  Date: {target_date_str(filter_date)}")
    print(f"{'─'*55}")
    for channel_key, results in summary.items():
        found_dm = sum(1 for s in results if s.dailymotion_url)
        found_jw = sum(1 for s in results if s.jwplayer_url)
        print(f"\n  {CHANNELS[channel_key]['label']} — {len(results)} serials")
        print(f"    Dailymotion : {found_dm}")
        print(f"    JW Player   : {found_jw}  (Playwright HLS interception)")
        for s in results:
            icon = "✓" if (s.dailymotion_url or s.jwplayer_url) else "✗"
            src  = "DM" if s.dailymotion_url else ("JW" if s.jwplayer_url else "—")
            print(f"    {icon} [{src}] {s.title}")
            if s.dailymotion_url: print(f"           {s.dailymotion_url}")
            if s.jwplayer_url:    print(f"           {s.jwplayer_url}")
            if s.error:           print(f"           ERR: {s.error}")
    print()