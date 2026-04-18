"""
scraper.py — DDMalar scraper
Saves output to: data/serials_YYYY-MM-DD.json
Run locally:  python scraper.py
Run by GitHub Actions automatically every day.
"""

import re
import json
import time
import logging
import argparse
import os
from dataclasses import dataclass, asdict
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.ddmalar.online/",
}

BASE_URL = "https://www.ddmalar.online/"
DELAY    = 1.0
TIMEOUT  = 15


@dataclass
class Serial:
    name:        str
    serial_page: str
    watch_page:  Optional[str] = None
    video_url:   Optional[str] = None
    error:       Optional[str] = None


session = requests.Session()
session.headers.update(HEADERS)


def get(url: str, retries: int = 2) -> Optional[requests.Response]:
    for attempt in range(retries + 1):
        try:
            r = session.get(url, timeout=TIMEOUT, allow_redirects=True)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            log.warning(f"  [attempt {attempt+1}] {url} → {e}")
            if attempt < retries:
                time.sleep(2)
    return None


def fetch_serials() -> list[Serial]:
    log.info(f"Fetching home page: {BASE_URL}")
    r = get(BASE_URL)
    if not r:
        raise RuntimeError("Could not fetch home page")

    soup = BeautifulSoup(r.text, "html.parser")
    serials: list[Serial] = []

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if "pakkitv" in href or re.search(r"/page-\d+/\d+/", href):
            name = a.get_text(strip=True) or a.get("title", "").strip() or "Unknown"
            if name and href not in [s.serial_page for s in serials]:
                serials.append(Serial(name=name, serial_page=href))

    if not serials:
        for card in soup.select("[href]"):
            href = card.get("href", "").strip()
            if href and href != BASE_URL and href != "#":
                title = card.get("title") or card.get_text(strip=True) or href
                serials.append(Serial(name=title, serial_page=href))

    log.info(f"Found {len(serials)} serials")
    return serials


def fetch_watch_page_url(serial: Serial) -> None:
    log.info(f"  [{serial.name}] Fetching serial page …")
    r = get(serial.serial_page)
    if not r:
        serial.error = "serial page unreachable"
        return

    soup = BeautifulSoup(r.text, "html.parser")
    watch_link = None

    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True).lower()
        if "click here" in text or "watch" in text or "play" in text:
            watch_link = a["href"].strip()
            break

    if not watch_link:
        iframe = soup.find("iframe", src=True)
        if iframe:
            watch_link = iframe["src"].strip()

    if not watch_link:
        player_domains = ("jwplayer", "player", "embed", "stream", "video", "watch")
        for a in soup.find_all("a", href=True):
            if any(d in a["href"].lower() for d in player_domains):
                watch_link = a["href"].strip()
                break

    if watch_link:
        if watch_link.startswith("//"):
            watch_link = "https:" + watch_link
        elif watch_link.startswith("/"):
            from urllib.parse import urlparse
            base = "{uri.scheme}://{uri.netloc}".format(uri=urlparse(serial.serial_page))
            watch_link = base + watch_link
        serial.watch_page = watch_link
    else:
        serial.error = "watch link not found"


def fetch_video_url_browser(serial: Serial) -> None:
    """Fallback for serials where video URL is inside obfuscated JS."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.error("Playwright not installed — run: pip install playwright && playwright install chromium")
        return

    log.info(f"  [{serial.name}] Trying browser fallback (obfuscated JS detected) …")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page    = browser.new_page()
            found   = []

            def on_request(req):
                url = req.url
                if ".m3u8" in url or (".mp4" in url and "cdn" in url):
                    found.append(url)

            page.on("request", on_request)
            page.goto(serial.watch_page, wait_until="networkidle", timeout=30000)
            browser.close()

        if found:
            serial.video_url = found[0]
            log.info(f"  [{serial.name}] Video URL (browser) → {serial.video_url}")
        else:
            serial.error = (serial.error or "") + "; browser fallback also found nothing"
            log.warning(f"  [{serial.name}] Browser fallback found no video URL")

    except Exception as e:
        serial.error = f"browser error: {e}"
        log.error(f"  [{serial.name}] Browser fallback error: {e}")


def fetch_video_url(serial: Serial) -> None:
    if not serial.watch_page:
        return

    log.info(f"  [{serial.name}] Fetching player page …")
    r = get(serial.watch_page)
    if not r:
        serial.error = "player page unreachable"
        return

    text = r.text

    patterns = [
        r'["\']file["\']\s*:\s*["\'](https?://[^"\']+\.(?:m3u8|mp4|ts)[^"\']*)["\']',
        r'sources\s*:\s*\[\s*\{[^}]*["\']file["\']\s*:\s*["\'](https?://[^"\']+)["\']',
        r'jwplayer\([^)]+\)\.setup\([^)]*["\']file["\']\s*:\s*["\'](https?://[^"\']+)["\']',
        r'(?:src|source|file)\s*[:=]\s*["\'](https?://[^"\']+\.(?:m3u8|mp4|ts)[^"\']*)["\']',
        r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)',
        r'(https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*)',
    ]

    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            serial.video_url = m.group(1)
            log.info(f"  [{serial.name}] Video URL → {serial.video_url}")
            return

    soup = BeautifulSoup(text, "html.parser")
    for script in soup.find_all("script"):
        src = script.string or ""
        m = re.search(r'["\'](https?://[^"\']+\.(?:m3u8|mp4))["\']', src)
        if m:
            serial.video_url = m.group(1)
            log.info(f"  [{serial.name}] Video URL (script) → {serial.video_url}")
            return

    serial.error = (serial.error or "") + "; video URL not found"
    log.warning(f"  [{serial.name}] No video URL extracted")
    fetch_video_url_browser(serial) 


def process_serial(serial: Serial) -> Serial:
    fetch_watch_page_url(serial)
    if serial.watch_page:
        time.sleep(DELAY)
        fetch_video_url(serial)
    return serial


def run_scraper(workers: int = 3, limit: int = 0) -> list[Serial]:
    serials = fetch_serials()
    if limit:
        serials = serials[:limit]

    log.info(f"Processing {len(serials)} serials with {workers} workers …")
    results: list[Serial] = []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(process_serial, s): s for s in serials}
        for fut in as_completed(futures):
            results.append(fut.result())
            time.sleep(DELAY)

    return results


def save_json(results: list[Serial], output_dir: str = "data") -> str:
    os.makedirs(output_dir, exist_ok=True)
    today     = date.today().isoformat()
    filename  = f"serials_{today}.json"
    filepath  = os.path.join(output_dir, filename)

    payload = {
        "date":    today,
        "total":   len(results),
        "found":   sum(1 for s in results if s.video_url),
        "serials": [asdict(s) for s in results],
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    log.info(f"Saved → {filepath}")
    return filepath


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--limit",   type=int, default=0)
    parser.add_argument("--output",  type=str, default="data")
    args = parser.parse_args()

    results = run_scraper(workers=args.workers, limit=args.limit)
    save_json(results, output_dir=args.output)

    found = sum(1 for s in results if s.video_url)
    print(f"\n✓ {found}/{len(results)} video URLs extracted\n")