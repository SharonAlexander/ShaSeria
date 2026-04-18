"""
generate_html.py
Reads all data/serials_YYYY-MM-DD.json files and builds:
  docs/index.html      — date list (home page)
  docs/YYYY-MM-DD.html — per-day page with playable HLS links

Fixes:
  - Serial data stored in window.SERIALS array, buttons use index (no strings in onclick)
  - Copy URL works on http/https and mobile via fallback
  - VLC button uses vlc:// protocol (desktop + Android VLC app + iOS VLC)
"""

import json
import os
import glob
from datetime import datetime, date as dt_date

DATA_DIR = "data"
OUT_DIR  = "docs"

os.makedirs(OUT_DIR, exist_ok=True)

# ── Shared CSS ─────────────────────────────────────────────────────────────────
CSS = """
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #0f0f0f; color: #e8e8e8; min-height: 100vh;
  }
  header {
    background: #1a1a2e; padding: 16px 24px;
    display: flex; align-items: center; gap: 16px;
    border-bottom: 2px solid #e94560;
    position: sticky; top: 0; z-index: 50;
  }
  header a.back { color: #e94560; text-decoration: none; font-size: 1.4rem; }
  header h1 { font-size: 1.1rem; color: #e8e8e8; }
  .container { max-width: 960px; margin: 0 auto; padding: 24px 16px; }
  .summary { color: #777; font-size: 0.85rem; margin-bottom: 12px; }

  /* Index grid */
  .date-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
    gap: 12px; margin-top: 16px;
  }
  .date-card {
    background: #1a1a2e; border: 1px solid #2a2a4a;
    border-radius: 10px; padding: 16px; text-align: center;
    text-decoration: none; color: #e8e8e8;
    transition: border-color .2s, transform .15s;
  }
  .date-card:hover { border-color: #e94560; transform: translateY(-2px); }
  .date-card.today { border-color: #e94560; }
  .date-card .date-label { font-size: 1rem; font-weight: 600; }
  .date-card .date-meta  { font-size: 0.78rem; color: #888; margin-top: 4px; }

  /* Serial list */
  .serial-list { display: flex; flex-direction: column; gap: 8px; }
  .serial-card {
    background: #1a1a2e; border: 1px solid #2a2a4a;
    border-radius: 10px; padding: 14px 16px;
    display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  }
  .serial-name { font-size: 0.95rem; font-weight: 500; flex: 1; min-width: 120px; }
  .serial-name.no-link { color: #555; }
  .btn-row { display: flex; gap: 6px; flex-wrap: wrap; }
  .btn {
    padding: 7px 14px; border-radius: 6px; border: none;
    cursor: pointer; font-size: 0.82rem; font-weight: 600;
    white-space: nowrap; display: inline-block; text-decoration: none;
  }
  .btn-play { background: #e94560; color: #fff; }
  .btn-play:hover { background: #c73652; }
  .btn-copy { background: #2a2a4a; color: #ccc; }
  .btn-copy:hover { background: #3a3a6a; color: #fff; }
  .btn-vlc  { background: #ff6600; color: #fff; }
  .btn-vlc:hover  { background: #cc5200; }
  .no-link-tag { color: #555; font-size: 0.8rem; }

  /* Toast */
  #toast {
    position: fixed; bottom: 28px; left: 50%; transform: translateX(-50%);
    background: #222; color: #fff; padding: 10px 22px;
    border-radius: 8px; font-size: 0.85rem;
    opacity: 0; transition: opacity .3s;
    pointer-events: none; z-index: 9999; white-space: nowrap;
  }
  #toast.show { opacity: 1; }

  /* Modal */
  .modal-overlay {
    display: none; position: fixed; inset: 0;
    background: rgba(0,0,0,.88); z-index: 1000;
    align-items: center; justify-content: center;
  }
  .modal-overlay.active { display: flex; }
  .modal {
    background: #1a1a2e; border-radius: 12px;
    width: 92%; max-width: 880px; padding: 20px;
    position: relative;
  }
  .modal-title {
    font-size: 1rem; font-weight: 600;
    color: #e94560; padding-right: 36px; margin-bottom: 12px;
  }
  .modal video {
    width: 100%; border-radius: 8px;
    background: #000; max-height: 68vh;
  }
  .modal-close {
    position: absolute; top: 12px; right: 16px;
    background: none; border: none;
    color: #aaa; font-size: 1.5rem; cursor: pointer;
  }
  .modal-close:hover { color: #fff; }
  .modal-actions { margin-top: 12px; display: flex; gap: 8px; flex-wrap: wrap; }
  .modal-url {
    margin-top: 8px; font-size: 0.72rem; color: #444;
    word-break: break-all;
  }
"""

# ── Shared JS ──────────────────────────────────────────────────────────────────
# window.SERIALS is injected per-page as a JSON array.
# All buttons reference items by numeric index — no URL strings in onclick attrs.
JS = """
<script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
<script>
var hlsPlayer = null;
var currentUrl = '';

/* ── Toast ── */
function showToast(msg) {
  var t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(function() { t.classList.remove('show'); }, 2200);
}

/* ── Play in modal ── */
function playSerial(idx) {
  var s = window.SERIALS[idx];
  if (!s || !s.url) return;
  currentUrl = s.url;
  document.getElementById('modalTitle').textContent = s.name;
  document.getElementById('modalUrlDisplay').textContent = s.url;

  var video = document.getElementById('modalVideo');
  if (hlsPlayer) { hlsPlayer.destroy(); hlsPlayer = null; }

  if (s.url.indexOf('.m3u8') !== -1) {
    if (typeof Hls !== 'undefined' && Hls.isSupported()) {
      hlsPlayer = new Hls();
      hlsPlayer.loadSource(s.url);
      hlsPlayer.attachMedia(video);
    } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = s.url;   // Safari native HLS
    }
  } else {
    video.src = s.url;
  }
  document.getElementById('playerModal').classList.add('active');
}

function closePlayer() {
  var video = document.getElementById('modalVideo');
  video.pause(); video.src = '';
  if (hlsPlayer) { hlsPlayer.destroy(); hlsPlayer = null; }
  document.getElementById('playerModal').classList.remove('active');
  currentUrl = '';
}

/* ── Copy URL ── */
function copyUrl(idx) {
  var s = window.SERIALS[idx];
  if (!s || !s.url) return;
  doCopy(s.url);
}

function copyModalUrl() { if (currentUrl) docopy(currentUrl); }

function doCopy(text) {
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text)
      .then(function() { showToast('URL copied!'); })
      .catch(function() { legacyCopy(text); });
  } else {
    legacyCopy(text);
  }
}

function legacyCopy(text) {
  var ta = document.createElement('textarea');
  ta.value = text;
  ta.style.cssText = 'position:fixed;opacity:0;top:0;left:0';
  document.body.appendChild(ta);
  ta.focus(); ta.select();
  try {
    document.execCommand('copy');
    showToast('URL copied!');
  } catch(e) {
    showToast('Long-press the URL below to copy');
  }
  document.body.removeChild(ta);
}

/* ── VLC ──
   Desktop (Win/Mac/Linux): vlc:// opens VLC media player directly.
   Android: vlc:// opens VLC for Android if installed.
   iOS: vlc-x-callback://x-callback-url/stream?url=<encoded> for VLC iOS app.
*/
function openVlc(idx) {
  var s = window.SERIALS[idx];
  if (!s || !s.url) return;
  var ua = navigator.userAgent || '';
  var isIOS = /iPad|iPhone|iPod/.test(ua) && !window.MSStream;
  if (isIOS) {
    // VLC iOS uses its own scheme
    window.location.href = 'vlc-x-callback://x-callback-url/stream?url=' + encodeURIComponent(s.url);
  } else {
    // Windows / Mac / Linux / Android VLC
    window.location.href = 'vlc://' + s.url.replace(/^https?:\\/\\//, '');
  }
  setTimeout(function() {
    showToast("VLC not opening? Install VLC or copy the URL and open it manually.");
  }, 1800);
}

/* Close modal on backdrop click */
document.addEventListener('DOMContentLoaded', function() {
  var overlay = document.getElementById('playerModal');
  if (overlay) {
    overlay.addEventListener('click', function(e) {
      if (e.target === this) closePlayer();
    });
  }
});
</script>
"""

MODAL_HTML = """
<div id="toast"></div>
<div class="modal-overlay" id="playerModal">
  <div class="modal">
    <button class="modal-close" onclick="closePlayer()">&#x2715;</button>
    <div class="modal-title" id="modalTitle"></div>
    <video id="modalVideo" controls autoplay playsinline></video>
    <div class="modal-actions">
      <button class="btn btn-copy" onclick="doCopy(currentUrl)">&#x1F4CB; Copy URL</button>
      <button class="btn btn-vlc"  onclick="openVlc(-1)">&#x1F4FA; Open in VLC</button>
    </div>
    <div class="modal-url" id="modalUrlDisplay"></div>
  </div>
</div>
"""

# Special VLC button inside modal uses currentUrl directly
MODAL_HTML = """
<div id="toast"></div>
<div class="modal-overlay" id="playerModal">
  <div class="modal">
    <button class="modal-close" onclick="closePlayer()">&#x2715;</button>
    <div class="modal-title" id="modalTitle"></div>
    <video id="modalVideo" controls autoplay playsinline></video>
    <div class="modal-actions">
      <button class="btn btn-copy" onclick="doCopy(currentUrl)">&#x1F4CB; Copy URL</button>
      <button class="btn btn-vlc" onclick="(function(){
        var ua=navigator.userAgent||'';
        var ios=/iPad|iPhone|iPod/.test(ua)&&!window.MSStream;
        window.location.href = ios
          ? 'vlc-x-callback://x-callback-url/stream?url='+encodeURIComponent(currentUrl)
          : 'vlc://'+currentUrl.replace(/^https?:\\/\\//,'');
        setTimeout(function(){showToast('VLC not opening? Install VLC or copy URL.');},1800);
      })()">&#x1F4FA; Open in VLC</button>
    </div>
    <div class="modal-url" id="modalUrlDisplay"></div>
  </div>
</div>
"""


def build_page(title: str, body: str, serials_js: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>{CSS}</style>
</head>
<body>
{body}
{MODAL_HTML}
<script>window.SERIALS = {serials_js};</script>
{JS}
</body></html>"""


def fmt_date(d: str) -> str:
    try:
        return datetime.strptime(d, "%Y-%m-%d").strftime("%d %b %Y")
    except Exception:
        return d


# ── Per-day pages ──────────────────────────────────────────────────────────────
json_files = sorted(glob.glob(os.path.join(DATA_DIR, "serials_*.json")), reverse=True)
all_dates  = []

for jf in json_files:
    with open(jf, encoding="utf-8") as f:
        data = json.load(f)

    d       = data["date"]
    serials = data["serials"]
    found   = data.get("found", sum(1 for s in serials if s.get("video_url")))
    total   = data.get("total", len(serials))
    all_dates.append({"date": d, "label": fmt_date(d), "found": found, "total": total})

    serials_sorted = sorted(serials, key=lambda x: x["name"])

    # Build JS data array — name + url only, no other fields needed in browser
    js_data = json.dumps(
        [{"name": s["name"], "url": s.get("video_url") or ""} for s in serials_sorted],
        ensure_ascii=False,
    )

    # Build HTML rows — buttons reference index only, never embed URL in onclick
    rows = ""
    for idx, s in enumerate(serials_sorted):
        name = s["name"]
        url  = s.get("video_url")
        if url:
            rows += f"""
      <div class="serial-card">
        <span class="serial-name">{name}</span>
        <div class="btn-row">
          <button class="btn btn-play" onclick="playSerial({idx})">&#x25B6; Play</button>
          <button class="btn btn-copy" onclick="copyUrl({idx})">&#x1F4CB; Copy</button>
          <button class="btn btn-vlc"  onclick="openVlc({idx})">&#x1F4FA; VLC</button>
        </div>
      </div>"""
        else:
            err = s.get("error") or "no link"
            rows += f"""
      <div class="serial-card">
        <span class="serial-name no-link">{name}</span>
        <span class="no-link-tag">&#x274C; {err}</span>
      </div>"""

    body = f"""
<header>
  <a class="back" href="index.html">&#x2B05;</a>
  <h1>&#x1F4FA; Serials &mdash; {fmt_date(d)}</h1>
</header>
<div class="container">
  <p class="summary">{found} of {total} links found</p>
  <div class="serial-list">{rows}
  </div>
</div>"""

    out_path = os.path.join(OUT_DIR, f"{d}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(build_page(f"Serials — {fmt_date(d)}", body, js_data))
    print(f"  ✓ {out_path}")


# ── Index page ─────────────────────────────────────────────────────────────────
today_str = dt_date.today().isoformat()

cards = ""
for entry in all_dates:
    cls   = "date-card today" if entry["date"] == today_str else "date-card"
    badge = " &#x1F534; Today" if entry["date"] == today_str else ""
    cards += f"""
    <a href="{entry['date']}.html" class="{cls}">
      <div class="date-label">{entry['label']}{badge}</div>
      <div class="date-meta">{entry['found']}/{entry['total']} links</div>
    </a>"""

index_body = f"""
<header>
  <h1>&#x1F4FA; ShaSeria Serials Archive</h1>
</header>
<div class="container">
  <p class="summary">{len(all_dates)} days archived</p>
  <div class="date-grid">{cards}
  </div>
</div>"""

# Index doesn't need SERIALS data or modal
index_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ShaSeria Serials Archive</title>
<style>{CSS}</style>
</head>
<body>
{index_body}
</body></html>"""

with open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8") as f:
    f.write(index_html)

print(f"\n✓ index.html + {len(all_dates)} day pages built in docs/")