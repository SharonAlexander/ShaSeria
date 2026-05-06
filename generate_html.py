"""
generate_html.py
Reads:
  data/serials_malayalam_YYYY-MM-DD.json
  data/serials_tamil_suntv_YYYY-MM-DD.json
  data/serials_tamil_vijaytv_YYYY-MM-DD.json
  data/serials_tamil_zeetamil_YYYY-MM-DD.json
and builds:
  docs/index.html      — date list (home page) with language tabs
  docs/YYYY-MM-DD.html — per-day page with playable HLS links + language/channel tabs

Tabs layout:
  [ Malayalam ]  [ Tamil › Sun TV | Vijay TV | Zee Tamil ]
  Always fully visible — no dropdowns, no extra clicks.
"""

import json
import os
import glob
from datetime import datetime, date as dt_date, timedelta

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

  /* ── Tab bar ── */
  .tab-bar {
    background: #12122a;
    border-bottom: 1px solid #2a2a4a;
    padding: 0 16px;
    display: flex;
    align-items: stretch;
    flex-wrap: nowrap;
    overflow-x: auto;
    gap: 0;
    position: sticky;
    top: 60px;   /* below header */
    z-index: 40;
  }
  .tab-bar::-webkit-scrollbar { height: 3px; }
  .tab-bar::-webkit-scrollbar-thumb { background: #e94560; border-radius: 2px; }

  /* Primary language tabs */
  .lang-tab {
    display: flex;
    align-items: center;
    gap: 0;
    flex-shrink: 0;
  }

  .lang-tab-btn {
    background: none;
    border: none;
    color: #888;
    font-size: 0.88rem;
    font-weight: 600;
    padding: 12px 18px;
    cursor: pointer;
    white-space: nowrap;
    border-bottom: 3px solid transparent;
    transition: color .2s, border-color .2s;
    letter-spacing: .3px;
  }
  .lang-tab-btn:hover { color: #ccc; }
  .lang-tab-btn.active { color: #e94560; border-bottom-color: #e94560; }

  /* Divider between lang label and subtabs */
  .tab-divider {
    width: 1px;
    background: #2a2a4a;
    margin: 8px 0;
    flex-shrink: 0;
  }

  /* Tamil subtabs — always visible inline */
  .subtab-group {
    display: flex;
    align-items: stretch;
    flex-shrink: 0;
  }
  .subtab-btn {
    background: none;
    border: none;
    color: #666;
    font-size: 0.80rem;
    font-weight: 500;
    padding: 12px 13px;
    cursor: pointer;
    white-space: nowrap;
    border-bottom: 3px solid transparent;
    transition: color .2s, border-color .2s;
  }
  .subtab-btn:hover { color: #aaa; }
  .subtab-btn.active { color: #f0a500; border-bottom-color: #f0a500; }

  /* ── Content panels ── */
  .tab-panel { display: none; }
  .tab-panel.active { display: block; }

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

  /* Dailymotion embed */
  .dm-embed {
    width: 100%; aspect-ratio: 16/9;
    border: none; border-radius: 8px;
    background: #000;
  }
  .embed-wrapper {
    width: 100%; margin-top: 12px;
  }

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

  /* Mobile tweaks */
  @media (max-width: 500px) {
    .lang-tab-btn { padding: 12px 12px; font-size: 0.83rem; }
    .subtab-btn   { padding: 12px 9px;  font-size: 0.75rem; }
  }
"""

# ── Tab switching JS ───────────────────────────────────────────────────────────
TAB_JS = """
<script>
/* ── Tab switching ── */
function switchLang(lang) {
  // Deactivate all lang buttons and panels
  document.querySelectorAll('.lang-tab-btn').forEach(function(b) {
    b.classList.remove('active');
  });
  document.querySelectorAll('.tab-panel[data-lang]').forEach(function(p) {
    p.classList.remove('active');
  });

  // Activate chosen lang button
  var btn = document.querySelector('.lang-tab-btn[data-lang="' + lang + '"]');
  if (btn) btn.classList.add('active');

  // If Tamil, activate the currently-selected subtab panel; else activate the lang panel
  if (lang === 'tamil') {
    var active = document.querySelector('.subtab-btn.active');
    var ch = active ? active.dataset.channel : 'suntv';
    showChannel(ch);
  } else {
    var panel = document.querySelector('.tab-panel[data-lang="' + lang + '"]');
    if (panel) panel.classList.add('active');
  }

  // Persist selection
  try { sessionStorage.setItem('activeLang', lang); } catch(e) {}
}

function switchSubtab(channel) {
  // First make sure Tamil lang tab is active
  switchLang('tamil');

  // Then highlight the right subtab
  showChannel(channel);
}

function showChannel(channel) {
  document.querySelectorAll('.subtab-btn').forEach(function(b) {
    b.classList.toggle('active', b.dataset.channel === channel);
  });
  document.querySelectorAll('.tab-panel[data-channel]').forEach(function(p) {
    p.classList.toggle('active', p.dataset.channel === channel);
  });
  try { sessionStorage.setItem('activeChannel', channel); } catch(e) {}
}

// Restore tab state on load
document.addEventListener('DOMContentLoaded', function() {
  try {
    var lang = sessionStorage.getItem('activeLang') || 'malayalam';
    var ch   = sessionStorage.getItem('activeChannel') || 'suntv';
    // Activate subtab first so showChannel works
    document.querySelectorAll('.subtab-btn').forEach(function(b) {
      if (b.dataset.channel === ch) b.classList.add('active');
    });
    switchLang(lang);
  } catch(e) {
    switchLang('malayalam');
  }
});
</script>
"""

# ── Player JS ─────────────────────────────────────────────────────────────────
JS = """
<script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
<script>
var hlsPlayer = null;
var currentUrl = '';

function showToast(msg) {
  var t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(function() { t.classList.remove('show'); }, 2200);
}

function playSerial(namespace, idx) {
  var arr = window.SERIALS[namespace];
  if (!arr) return;
  var s = arr[idx];
  if (!s) return;

  // Tamil serials: use dailymotion embed instead of HLS modal
  if (s.dm_id) {
    openDailymotion(s.name, s.dm_id, s.dm_url);
    return;
  }

  if (!s.url) return;
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
      video.src = s.url;
    }
  } else {
    video.src = s.url;
  }
  document.getElementById('playerModal').classList.add('active');
}

function openDailymotion(name, dmId, dmUrl) {
  document.getElementById('modalTitle').textContent = name;
  document.getElementById('modalUrlDisplay').textContent = dmUrl || '';
  currentUrl = dmUrl || '';

  // Replace the video element with a DM iframe
  var container = document.getElementById('modalVideoContainer');
  container.innerHTML =
    '<iframe class="dm-embed" src="https://www.dailymotion.com/embed/video/' + dmId +
    '?autoplay=1" allowfullscreen allow="autoplay"></iframe>';

  // Hide HLS-specific actions
  document.getElementById('modalHlsActions').style.display = 'none';
  document.getElementById('playerModal').classList.add('active');
}

function closePlayer() {
  var container = document.getElementById('modalVideoContainer');
  // Restore video element (kills iframe / stops playback)
  container.innerHTML = '<video id="modalVideo" controls autoplay playsinline></video>';
  if (hlsPlayer) { hlsPlayer.destroy(); hlsPlayer = null; }
  document.getElementById('modalHlsActions').style.display = '';
  document.getElementById('playerModal').classList.remove('active');
  currentUrl = '';
}

function copyUrl(namespace, idx) {
  var arr = window.SERIALS[namespace];
  if (!arr) return;
  var s = arr[idx];
  if (!s) return;
  var url = s.dm_url || s.url || '';
  if (url) doCopy(url);
}

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

function openVlc(namespace, idx) {
  var url = '';
  if (idx === -1) {
    url = currentUrl;
  } else {
    var arr = window.SERIALS[namespace];
    if (!arr) return;
    var s = arr[idx];
    if (!s) return;
    url = s.url || s.dm_url || '';
  }
  if (!url) return;
  var ua = navigator.userAgent || '';
  var isIOS = /iPad|iPhone|iPod/.test(ua) && !window.MSStream;
  if (isIOS) {
    window.location.href = 'vlc-x-callback://x-callback-url/stream?url=' + encodeURIComponent(url);
  } else {
    window.location.href = 'vlc://' + url.replace(/^https?:\\/\\//, '');
  }
  setTimeout(function() {
    showToast("VLC not opening? Install VLC or copy the URL.");
  }, 1800);
}

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
    <div id="modalVideoContainer">
      <video id="modalVideo" controls autoplay playsinline></video>
    </div>
    <div class="modal-actions" id="modalHlsActions">
      <button class="btn btn-copy" onclick="doCopy(currentUrl)">&#x1F4CB; Copy URL</button>
      <button class="btn btn-vlc" onclick="openVlc('', -1)">&#x1F4FA; Open in VLC</button>
    </div>
    <div class="modal-url" id="modalUrlDisplay"></div>
  </div>
</div>
"""

# ── Tab bar HTML (shared across index + day pages) ────────────────────────────
TAB_BAR_HTML = """
<div class="tab-bar">
  <!-- Malayalam primary tab -->
  <div class="lang-tab">
    <button class="lang-tab-btn" data-lang="malayalam"
            onclick="switchLang('malayalam')">&#x1F3AC; Malayalam</button>
  </div>

  <div class="tab-divider"></div>

  <!-- Tamil primary tab label -->
  <div class="lang-tab">
    <button class="lang-tab-btn" data-lang="tamil"
            onclick="switchLang('tamil')">&#x1F3AC; Tamil</button>
  </div>

  <!-- Tamil subtabs — always visible -->
  <div class="tab-divider"></div>
  <div class="subtab-group">
    <button class="subtab-btn" data-channel="suntv"
            onclick="switchSubtab('suntv')">Sun TV</button>
    <button class="subtab-btn" data-channel="vijaytv"
            onclick="switchSubtab('vijaytv')">Vijay TV</button>
    <button class="subtab-btn" data-channel="zeetamil"
            onclick="switchSubtab('zeetamil')">Zee Tamil</button>
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
{TAB_JS}
</body></html>"""


def fmt_date(d: str) -> str:
    try:
        return datetime.strptime(d, "%Y-%m-%d").strftime("%d %b %Y")
    except Exception:
        return d


def serial_name(s: dict) -> str:
    """Return display name for either Malayalam or Tamil serial entry."""
    return s.get("name") or s.get("title") or "Unknown"


def serial_url(s: dict) -> str:
    """Return HLS/direct URL for Malayalam serials (Tamil uses dailymotion_id instead)."""
    return s.get("video_url") or ""


def serial_dm_id(s: dict) -> str:
    """Return Dailymotion video ID for Tamil serials."""
    return s.get("dailymotion_id") or ""


def serial_dm_url(s: dict) -> str:
    """Return Dailymotion embed URL for Tamil serials."""
    return s.get("dailymotion_url") or ""


def has_playable(s: dict) -> bool:
    """True if the serial has any playable source."""
    return bool(serial_url(s) or serial_dm_id(s))


def build_js_data(serials: list) -> list:
    """Build the JS SERIALS array — works for both Malayalam and Tamil entries."""
    out = []
    for s in sorted(serials, key=lambda x: serial_name(x)):
        entry = {"name": serial_name(s)}
        url   = serial_url(s)
        dm_id = serial_dm_id(s)
        dm_url = serial_dm_url(s)
        if url:
            entry["url"] = url
        if dm_id:
            entry["dm_id"]  = dm_id
            entry["dm_url"] = dm_url
        out.append(entry)
    return out


def build_serial_rows(serials: list, namespace: str) -> str:
    """Build HTML rows — handles both Malayalam (HLS) and Tamil (Dailymotion) entries."""
    serials_sorted = sorted(serials, key=lambda x: serial_name(x))
    rows = ""
    for idx, s in enumerate(serials_sorted):
        name   = serial_name(s)
        url    = serial_url(s)
        dm_id  = serial_dm_id(s)
        dm_url = serial_dm_url(s)
        playable = url or dm_id

        if playable:
            # Copy button uses HLS URL for Malayalam, DM embed URL for Tamil
            rows += f"""
      <div class="serial-card">
        <span class="serial-name">{name}</span>
        <div class="btn-row">
          <button class="btn btn-play" onclick="playSerial('{namespace}',{idx})">&#x25B6; Play</button>
          <button class="btn btn-copy" onclick="copyUrl('{namespace}',{idx})">&#x1F4CB; Copy</button>"""
            # VLC only makes sense for direct HLS streams, not Dailymotion embeds
            if url:
                rows += f"""
          <button class="btn btn-vlc"  onclick="openVlc('{namespace}',{idx})">&#x1F4FA; VLC</button>"""
            rows += """
        </div>
      </div>"""
        else:
            err = s.get("error") or "no link"
            rows += f"""
      <div class="serial-card">
        <span class="serial-name no-link">{name}</span>
        <span class="no-link-tag">&#x274C; {err}</span>
      </div>"""
    return rows


# ── Collect all dates from all source files ────────────────────────────────────
TAMIL_CHANNELS = {
    "suntv":    "Sun TV",
    "vijaytv":  "Vijay TV",
    "zeetamil": "Zee Tamil",
}

def load_by_date(pattern):
    """Glob pattern → {date_str: parsed_json}"""
    result = {}
    for jf in glob.glob(os.path.join(DATA_DIR, pattern)):
        with open(jf, encoding="utf-8") as f:
            data = json.load(f)
        result[data["date"]] = data
    return result

mal_by_date      = load_by_date("serials_malayalam_*.json")
tamil_suntv      = load_by_date("serials_tamil_suntv_*.json")
tamil_vijaytv    = load_by_date("serials_tamil_vijaytv_*.json")
tamil_zeetamil   = load_by_date("serials_tamil_zeetamil_*.json")

tamil_by_channel = {
    "suntv":    tamil_suntv,
    "vijaytv":  tamil_vijaytv,
    "zeetamil": tamil_zeetamil,
}

all_dates_set = (set(mal_by_date) | set(tamil_suntv) |
                 set(tamil_vijaytv) | set(tamil_zeetamil))
all_dates_sorted = sorted(all_dates_set, reverse=True)


# ── Per-day pages ──────────────────────────────────────────────────────────────
today_str = dt_date.today().isoformat()
index_entries = []

for d in all_dates_sorted:
    # ---- Malayalam panel ----
    mal_data  = mal_by_date.get(d)
    mal_found = mal_total = 0
    mal_js    = []
    mal_rows  = '<p style="color:#555;padding:20px 0">No Malayalam data for this date.</p>'

    if mal_data:
        serials   = mal_data["serials"]
        mal_found = mal_data.get("found", sum(1 for s in serials if has_playable(s)))
        mal_total = mal_data.get("total", len(serials))
        mal_js    = build_js_data(serials)
        mal_rows  = build_serial_rows(serials, "malayalam")

    mal_panel = f"""
<div class="tab-panel" data-lang="malayalam" id="panel-malayalam">
  <div class="container">
    <p class="summary">{mal_found} of {mal_total} links found</p>
    <div class="serial-list">{mal_rows}
    </div>
  </div>
</div>"""

    # ---- Tamil panels — one per channel ----
    tamil_panels = ""
    tamil_js     = {}
    tamil_stats  = {}

    for ch_key, ch_label in TAMIL_CHANNELS.items():
        ch_data    = tamil_by_channel[ch_key].get(d)
        ch_serials = ch_data["serials"] if ch_data else []

        found = sum(1 for s in ch_serials if has_playable(s))
        total = len(ch_serials)
        tamil_stats[ch_key] = (found, total)

        ns   = f"tamil_{ch_key}"
        rows = (build_serial_rows(ch_serials, ns) if ch_serials
                else '<p style="color:#555;padding:20px 0">No data for this channel.</p>')
        tamil_js[ch_key] = build_js_data(ch_serials)

        tamil_panels += f"""
<div class="tab-panel" data-channel="{ch_key}" id="panel-{ch_key}">
  <div class="container">
    <p class="summary">{ch_label} &mdash; {found} of {total} links found</p>
    <div class="serial-list">{rows}
    </div>
  </div>
</div>"""

    # ---- Assemble page body ----
    body = f"""
<header>
  <a class="back" href="index.html">&#x2B05;</a>
  <h1>&#x1F4FA; Serials &mdash; {fmt_date(d)}</h1>
</header>
{TAB_BAR_HTML}
{mal_panel}
{tamil_panels}"""

    # ---- JS data object ----
    js_data = json.dumps({
        "malayalam":      mal_js,
        "tamil_suntv":    tamil_js["suntv"],
        "tamil_vijaytv":  tamil_js["vijaytv"],
        "tamil_zeetamil": tamil_js["zeetamil"],
    }, ensure_ascii=False)

    out_path = os.path.join(OUT_DIR, f"{d}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(build_page(f"Serials — {fmt_date(d)}", body, js_data))
    print(f"  ✓ {out_path}")

    # Summary for index
    tamil_total_found = sum(v[0] for v in tamil_stats.values())
    tamil_total_count = sum(v[1] for v in tamil_stats.values())
    index_entries.append({
        "date":  d,
        "label": fmt_date(d),
        "mal_found": mal_found, "mal_total": mal_total,
        "tam_found": tamil_total_found, "tam_total": tamil_total_count,
    })


# ── Index page ─────────────────────────────────────────────────────────────────
def build_date_cards(entries, lang_filter):
    cards = ""
    for entry in entries:
        d   = entry["date"]
        cls = "date-card today" if d == today_str else "date-card"
        badge = " &#x1F534; Today" if d == today_str else ""
        if lang_filter == "malayalam":
            meta = f"{entry['mal_found']}/{entry['mal_total']} links"
        else:
            meta = f"{entry['tam_found']}/{entry['tam_total']} links"
        cards += f"""
    <a href="{d}.html" class="{cls}">
      <div class="date-label">{entry['label']}{badge}</div>
      <div class="date-meta">{meta}</div>
    </a>"""
    return cards


mal_cards = build_date_cards(index_entries, "malayalam")
tam_cards = build_date_cards(index_entries, "tamil")

index_body = f"""
<header>
  <h1>&#x1F4FA; ShaSeria Serials Archive</h1>
</header>
{TAB_BAR_HTML}

<!-- Malayalam dates -->
<div class="tab-panel" data-lang="malayalam" id="panel-malayalam">
  <div class="container">
    <p class="summary">{len(index_entries)} days archived</p>
    <div class="date-grid">{mal_cards}
    </div>
  </div>
</div>

<!-- Tamil date grids -->
<div class="tab-panel" data-channel="suntv" id="panel-suntv">
  <div class="container">
    <p class="summary">Sun TV &mdash; {len(index_entries)} days archived</p>
    <div class="date-grid">{tam_cards}
    </div>
  </div>
</div>
<div class="tab-panel" data-channel="vijaytv" id="panel-vijaytv">
  <div class="container">
    <p class="summary">Vijay TV &mdash; {len(index_entries)} days archived</p>
    <div class="date-grid">{tam_cards}
    </div>
  </div>
</div>
<div class="tab-panel" data-channel="zeetamil" id="panel-zeetamil">
  <div class="container">
    <p class="summary">Zee Tamil &mdash; {len(index_entries)} days archived</p>
    <div class="date-grid">{tam_cards}
    </div>
  </div>
</div>"""

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
{TAB_JS}
</body></html>"""

with open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8") as f:
    f.write(index_html)
print("  ✓ docs/index.html")


# ── Prune pages older than 30 days ────────────────────────────────────────────
cutoff = dt_date.today() - timedelta(days=30)
for html_file in glob.glob(os.path.join(OUT_DIR, "????-??-??.html")):
    fname = os.path.basename(html_file).replace(".html", "")
    try:
        if dt_date.fromisoformat(fname) < cutoff:
            os.remove(html_file)
            print(f"  🗑 Deleted old page: {fname}.html")
    except ValueError:
        pass

print(f"\n✓ index.html + {len(all_dates_sorted)} day pages built in docs/")