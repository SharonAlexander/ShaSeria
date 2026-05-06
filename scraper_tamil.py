"""
scraper_tamildhool.py — TamilDhool multi-channel scraper
Channels : Sun TV | Vijay TV | Zee Tamil
Saves output to:
  data/serials_tamil_suntv_YYYY-MM-DD.json
  data/serials_tamil_vijaytv_YYYY-MM-DD.json
  data/serials_tamil_zeetamil_YYYY-MM-DD.json
Run locally:  python scraper_tamildhool.py
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
            "https://www.tamildhool.tech/sun-tv/sun-tv-serial/page/3/",
        ],
        "filename": "serials_tamil_suntv_{date}.json",
    },
    "vijaytv": {
        "label": "Vijay TV",
        "pages": [
            "https://www.tamildhool.tech/vijay-tv/vijay-tv-serial/",
            "https://www.tamildhool.tech/vijay-tv/vijay-tv-serial/page/2/",
            "https://www.tamildhool.tech/vijay-tv/vijay-tv-serial/page/3/",
        ],
        "filename": "serials_tamil_vijaytv_{date}.json",
    },
    "zeetamil": {
        "label": "Zee Tamil",
        "pages": [
            "https://www.tamildhool.tech/zee-tamil/zee-tamil-serial/",
            "https://www.tamildhool.tech/zee-tamil/zee-tamil-serial/page/2/",
            "https://www.tamildhool.tech/zee-tamil/zee-tamil-serial/page/3/",
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


# ─── Data model ───────────────────────────────────────────────────────────────

@dataclass
class Serial:
    title:           str
    href:            str
    srcset:          list = field(default_factory=list)  # [webp_url, jpg_url]
    dailymotion_id:  Optional[str] = None
    dailymotion_url: Optional[str] = None
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


# ─── Helpers ─────────────────────────────────────────────────────────────────

def target_date_str(for_date: date) -> str:
    """Return date as DD-MM-YYYY (format used in serial titles)."""
    return for_date.strftime("%d-%m-%Y")


# ─── Phase 1: scrape listing pages ───────────────────────────────────────────

def fetch_serials(channel_key: str, filter_date: date) -> list[Serial]:
    """
    Scrape both listing pages for the given channel and return serials
    matching the target date.

    Confirmed HTML structure:
      <article class="regular-post …">
        <div class="post-thumb">
          <a href="…/episode-url/" title="Serial Name DD-MM-YYYY Channel Serial">
            <picture>
              <source srcset="….webp" type="image/webp">
              <img src="….jpg" …>
            </picture>
          </a>
        </div>
        <h3 class="entry-title"><a href="…">…title…</a></h3>
      </article>
    """
    channel   = CHANNELS[channel_key]
    date_str  = target_date_str(filter_date)
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

            # Collect srcset images from <picture>
            srcset_urls: list[str] = []
            picture = thumb_a.find("picture")
            if picture:
                source = picture.find("source", srcset=True)
                if source:
                    srcset_urls.append(source["srcset"].strip())  # .webp
                img = picture.find("img", src=True)
                if img:
                    srcset_urls.append(img["src"].strip())        # .jpg

            all_serials.append(Serial(title=title, href=href, srcset=srcset_urls))

        time.sleep(DELAY)

    log.info(f"  Total cards across both pages: {len(all_serials)}")

    # Keep only serials matching the target date
    filtered = [s for s in all_serials if date_str in s.title]
    log.info(f"  After date filter ({date_str}): {len(filtered)} serials")
    for s in filtered:
        log.info(f"    ✓ {s.title}")

    return filtered


# ─── Phase 2: scrape episode page for Dailymotion link ───────────────────────

def fetch_video_links(serial: Serial) -> None:
    """
    Parse the episode page for the Dailymotion figure block.

    Confirmed HTML structure:
      <figure class="td-featured-thumb">
        <div class="td-source-label">Dailymotion</div>
        <a href="https://tamilbliss.com/?video=k5msIGc7wOTfv8FQP6a" …>
          <img src="https://www.dailymotion.com/thumbnail/…/video/k5msIGc7wOTfv8FQP6a" …>
        </a>
      </figure>

    Dailymotion video ID is extracted from:
      1. The tamilbliss URL  ?video=<ID>
      2. The thumbnail img src  /video/<ID>
    """
    log.info(f"  Fetching episode page: {serial.href}")
    r = get(serial.href)
    if not r:
        serial.error = "episode page unreachable"
        return

    soup = BeautifulSoup(r.text, "html.parser")
    found = False

    for figure in soup.select("figure.td-featured-thumb"):
        label_tag = figure.select_one("div.td-source-label")
        if not label_tag:
            continue
        label = label_tag.get_text(strip=True).lower()

        if "dailymotion" not in label:
            continue

        # Extract video ID from the tamilbliss href
        a = figure.select_one("a[href]")
        if a:
            m = re.search(r"[?&]video=([A-Za-z0-9]+)", a["href"])
            if m:
                serial.dailymotion_id  = m.group(1)
                serial.dailymotion_url = f"https://www.dailymotion.com/embed/video/{m.group(1)}"
                log.info(f"  Dailymotion → {serial.dailymotion_url}")
                found = True
                break

        # Fallback: extract from thumbnail img src
        if not found:
            img = figure.select_one("img[src]")
            if img:
                m = re.search(r"/video/([A-Za-z0-9]+)", img["src"])
                if m:
                    serial.dailymotion_id  = m.group(1)
                    serial.dailymotion_url = f"https://www.dailymotion.com/embed/video/{m.group(1)}"
                    log.info(f"  Dailymotion (img fallback) → {serial.dailymotion_url}")
                    found = True
                    break

    if not found:
        serial.error = "dailymotion link not found"
        log.warning(f"  No Dailymotion link found for: {serial.title}")


# ─── Orchestration ────────────────────────────────────────────────────────────

def run_channel(channel_key: str, filter_date: date, limit: int = 0) -> list[Serial]:
    """Run full scrape for one channel: listing pages → episode pages."""
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
        "found":   sum(1 for s in results if s.dailymotion_url),
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
        # filenames: serials_tamil_suntv_2026-05-05.json
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
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Target date as YYYY-MM-DD (default: yesterday)",
    )
    args = parser.parse_args()

    # Resolve channels
    channels_to_run = list(CHANNELS.keys()) if "all" in args.channels else args.channels

    # Resolve target date
    filter_date = (
        date.fromisoformat(args.date)
        if args.date
        else date.today() - timedelta(days=1)
    )

    log.info(f"Channels  : {', '.join(channels_to_run)}")
    log.info(f"Date filter: {target_date_str(filter_date)}")

    summary: dict[str, list[Serial]] = {}

    for channel_key in channels_to_run:
        results = run_channel(channel_key, filter_date=filter_date, limit=args.limit)
        summary[channel_key] = results
        if results:
            save_json(results, channel_key, output_dir=args.output)

    cleanup_old_files(output_dir=args.output)

    # ── Final summary ──
    print(f"\n{'─'*55}")
    print(f"  Date: {target_date_str(filter_date)}")
    print(f"{'─'*55}")
    for channel_key, results in summary.items():
        found = sum(1 for s in results if s.dailymotion_url)
        print(f"\n  {CHANNELS[channel_key]['label']} — {found}/{len(results)} with Dailymotion links")
        for s in results:
            icon = "✓" if s.dailymotion_url else "✗"
            print(f"    {icon} {s.title}")
            if s.dailymotion_url:
                print(f"        {s.dailymotion_url}")
            if s.error:
                print(f"        ERR: {s.error}")
    print() 