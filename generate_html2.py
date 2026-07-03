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

Tab behaviour:
  [ Malayalam ]  [ Tamil ]
                   └─ subtab row (below, only when Tamil active):
                      [ Sun TV ]  [ Vijay TV ]  [ Zee Tamil ]

  • Malayalam tab  → show only Malayalam panel; hide subtab row.
  • Tamil tab      → show all 3 channels stacked & scrollable; subtab row
                     visible but NO subtab highlighted.
  • Subtab click   → show only that channel's panel; subtab row visible;
                     clicked subtab highlighted.

Tamil serial cards:
  - Two separate Play buttons: one for Dailymotion, one for JW Player (HLS)
  - No Copy URL button on Tamil cards
  - Malayalam cards retain: Play + Copy URL + VLC

Visit counter:
  - Powered by a Cloudflare Worker + KV store (visit_counter_worker.js)
  - Set COUNTER_WORKER below to your deployed worker URL
  - Each day page tracks independently; index page tracks as "index"
  - Daily count auto-resets (KV TTL 48h); total count is permanent
"""

import json
import os
import glob
from datetime import datetime, date as dt_date, timedelta

DATA_DIR = "data"
OUT_DIR  = "docs"

os.makedirs(OUT_DIR, exist_ok=True)

# ── Cloudflare Worker proxy URL ───────────────────────────────────────────────
# Deploy cloudflare_worker.js to Cloudflare Workers (free tier) and paste
# your worker URL here.  Tamil JW Player HLS URLs are routed through it
# so hls.js can fetch them without CORS errors.
PROXY_BASE = "https://empty-thunder-a07a.sharoncheers.workers.dev"

# ── Cloudflare Worker visit counter URL ──────────────────────────────────────
# Deploy visit_counter_worker.js to Cloudflare Workers and paste the URL here.
# The worker needs a KV namespace bound as VISITS.
# Example: "https://visit-counter.YOUR-NAME.workers.dev"
COUNTER_WORKER = "https://silent-snow-b30b.sharoncheers.workers.dev"

# ── Visit counter JS ──────────────────────────────────────────────────────────
def counter_js(page_id: str = "unknown", hit: bool = True) -> str:
    """
    Site-wide visit counter (single 'global' total + daily counter).
    Increments once per browser tab via sessionStorage; subsequent
    page loads in the same tab only read (don't increment).
    """
    return f"""<script>
(function () {{
  var WORKER = {repr(COUNTER_WORKER)};
  var PAGE = 'global';
  var SESSION_KEY = 'sv_global_hit';
  function fmt(n) {{
    if (n === undefined || n === null) return '\u2026';
    if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
    if (n >= 1000)    return (n / 1000).toFixed(1) + 'k';
    return String(n);
  }}
  function setEl(id, val) {{
    var el = document.getElementById(id);
    if (el) el.textContent = fmt(val);
  }}
  var alreadyHit = false;
  try {{ alreadyHit = sessionStorage.getItem(SESSION_KEY) === '1'; }} catch(e) {{}}
  var action = alreadyHit ? 'get' : 'hit';
  fetch(WORKER + '?action=' + action + '&page=' + PAGE, {{
    method: 'GET',
    cache:  'no-store'
  }})
  .then(function(r) {{ return r.ok ? r.json() : Promise.reject(r.status); }})
  .then(function(data) {{
    setEl('visits-day',   data.day);
    setEl('visits-total', data.total);
    if (!alreadyHit) {{
      try {{ sessionStorage.setItem(SESSION_KEY, '1'); }} catch(e) {{}}
    }}
  }})
  .catch(function(err) {{
    setEl('visits-day',   '\u2014');
    setEl('visits-total', '\u2014');
    console.warn('Visit counter error:', err);
  }});
}})();
</script>"""

# ── Shared CSS ─────────────────────────────────────────────────────────────────
CSS = r"""
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #0f0f0f; color: #e8e8e8; min-height: 100vh;
  }

  /* ── Header ── */
  header {
    background: #1a1a2e; padding: 14px 20px;
    display: flex; align-items: center; gap: 12px;
    border-bottom: 2px solid #e94560;
    position: sticky; top: 0; z-index: 50; min-height: 56px;
  }
  header a.back { color: #e94560; text-decoration: none; font-size: 1.3rem; flex-shrink: 0; }
  header h1 { font-size: 1rem; color: #e8e8e8; flex: 1; }

  /* visit counter badge */
  .visit-badge { display: flex; gap: 8px; align-items: center; flex-shrink: 0; }
  .visit-pill {
    background: #12122a; border: 1px solid #2a2a4a;
    border-radius: 20px; padding: 4px 10px;
    font-size: 0.72rem; color: #aaa; white-space: nowrap;
    display: flex; align-items: center; gap: 4px;
  }
  .visit-pill .vnum { color: #e94560; font-weight: 700; font-size: 0.82rem; }
  .visit-pill.vtotal .vnum { color: #f0a500; }

  .container { max-width: 960px; margin: 0 auto; padding: 24px 16px; }
  .summary { color: #777; font-size: 0.85rem; margin-bottom: 12px; }

  /* ── Main tab bar ── */
  .tab-bar {
    background: #12122a; border-bottom: 1px solid #2a2a4a;
    padding: 0 16px;
    display: flex; align-items: stretch; flex-wrap: nowrap;
    overflow-x: auto; gap: 0;
    position: sticky; top: 56px; z-index: 40; min-height: 48px;
  }
  .tab-bar::-webkit-scrollbar { height: 3px; }
  .tab-bar::-webkit-scrollbar-thumb { background: #e94560; border-radius: 2px; }

  .lang-tab-btn {
    background: none; border: none; color: #888;
    font-size: 0.88rem; font-weight: 600;
    padding: 0 20px; cursor: pointer; white-space: nowrap;
    border-bottom: 3px solid transparent;
    transition: color .2s, border-color .2s;
    letter-spacing: .3px; flex-shrink: 0;
  }
  .lang-tab-btn:hover { color: #ccc; }
  .lang-tab-btn.active { color: #e94560; border-bottom-color: #e94560; }

  /* ── Subtab row ── */
  .subtab-row {
    background: #0d0d20; border-bottom: 1px solid #1e1e3a;
    padding: 0 16px;
    display: none;
    align-items: stretch; flex-wrap: nowrap; overflow-x: auto;
    position: sticky; top: 104px; z-index: 39; min-height: 40px;
  }
  .subtab-row.visible { display: flex; }
  .subtab-row::-webkit-scrollbar { height: 3px; }
  .subtab-row::-webkit-scrollbar-thumb { background: #f0a500; border-radius: 2px; }

  .subtab-btn {
    background: none; border: none; color: #666;
    font-size: 0.80rem; font-weight: 500;
    padding: 0 16px; cursor: pointer; white-space: nowrap;
    border-bottom: 3px solid transparent;
    transition: color .2s, border-color .2s; flex-shrink: 0;
  }
  .subtab-btn:hover { color: #aaa; }
  .subtab-btn.active { color: #f0a500; border-bottom-color: #f0a500; }

  /* ── Content panels ── */
  .tab-panel { display: none; }
  .tab-panel.active { display: block; }

  .channel-block { margin-bottom: 36px; }
  .channel-heading {
    font-size: 0.75rem; font-weight: 700;
    letter-spacing: 1.2px; text-transform: uppercase;
    color: #f0a500; padding: 10px 0 8px;
    border-bottom: 1px solid #2a2a4a; margin-bottom: 10px;
  }

  /* ── Index date grid ── */
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

  /* ── Serial list ── */
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
  .btn-play    { background: #e94560; color: #fff; }
  .btn-play:hover { background: #c73652; }
  /* JW Player button — distinct amber colour so it's clearly different from DM */
  .btn-play-jw { background: #b86e00; color: #fff; }
  .btn-play-jw:hover { background: #8f5500; }
  .btn-copy { background: #2a2a4a; color: #ccc; }
  .btn-copy:hover { background: #3a3a6a; color: #fff; }
  .btn-vlc  { background: #ff6600; color: #fff; }
  .btn-vlc:hover  { background: #cc5200; }
  .no-link-tag { color: #555; font-size: 0.8rem; }

  /* Dailymotion embed */
  .dm-embed { width: 100%; aspect-ratio: 16/9; border: none; border-radius: 8px; background: #000; }

  /* ── Toast ── */
  #toast {
    position: fixed; bottom: 28px; left: 50%; transform: translateX(-50%);
    background: #222; color: #fff; padding: 10px 22px;
    border-radius: 8px; font-size: 0.85rem;
    opacity: 0; transition: opacity .3s;
    pointer-events: none; z-index: 9999; white-space: nowrap;
  }
  #toast.show { opacity: 1; }

  /* ── Modal ── */
  .modal-overlay {
    display: none; position: fixed; inset: 0;
    background: rgba(0,0,0,.88); z-index: 1000;
    align-items: center; justify-content: center;
  }
  .modal-overlay.active { display: flex; }
  .modal {
    background: #1a1a2e; border-radius: 12px;
    width: 92%; max-width: 880px; padding: 20px; position: relative;
  }
  .modal-title { font-size: 1rem; font-weight: 600; color: #e94560; padding-right: 36px; margin-bottom: 12px; }
  .modal video { width: 100%; border-radius: 8px; background: #000; max-height: 68vh; }
  .modal-close {
    position: absolute; top: 12px; right: 16px;
    background: none; border: none; color: #aaa; font-size: 1.5rem; cursor: pointer;
  }
  .modal-close:hover { color: #fff; }
  .modal-actions { margin-top: 12px; display: flex; gap: 8px; flex-wrap: wrap; }
  .modal-url { margin-top: 8px; font-size: 0.72rem; color: #444; word-break: break-all; }

  /* ── Mobile tweaks ── */
  @media (max-width: 500px) {
    header { padding: 10px 14px; min-height: 50px; }
    .tab-bar { top: 50px; min-height: 44px; }
    .subtab-row { top: 94px; }
    .lang-tab-btn { padding: 0 14px; font-size: 0.82rem; }
    .subtab-btn   { padding: 0 11px; font-size: 0.75rem; }
    .visit-pill   { font-size: 0.68rem; padding: 3px 8px; }
    .visit-pill .vnum { font-size: 0.76rem; }
  }
"""

# ── Tab bar HTML ───────────────────────────────────────────────────────────────
TAB_BAR_HTML = """
<div class="tab-bar">
  <button class="lang-tab-btn" data-lang="malayalam"
          onclick="switchLang('malayalam')">&#x1F3AC; Malayalam</button>
  <button class="lang-tab-btn" data-lang="tamil"
          onclick="switchLang('tamil')">&#x1F3AC; Tamil</button>
</div>
<div class="subtab-row" id="subtabRow">
  <button class="subtab-btn" data-channel="suntv"
          onclick="switchSubtab('suntv')">Sun TV</button>
  <button class="subtab-btn" data-channel="vijaytv"
          onclick="switchSubtab('vijaytv')">Vijay TV</button>
  <button class="subtab-btn" data-channel="zeetamil"
          onclick="switchSubtab('zeetamil')">Zee Tamil</button>
</div>
"""

# ── Tab switching JS ───────────────────────────────────────────────────────────
TAB_JS = """
<script>
function _hideAll() {
  document.querySelectorAll('.tab-panel').forEach(function(p){
    p.classList.remove('active');
  });
}
function _setLangBtn(lang) {
  document.querySelectorAll('.lang-tab-btn').forEach(function(b){
    b.classList.toggle('active', b.dataset.lang === lang);
  });
}
function _setSubtabRow(show) {
  var r = document.getElementById('subtabRow');
  if (r) r.classList.toggle('visible', show);
}
function _setSubtabBtn(ch) {
  document.querySelectorAll('.subtab-btn').forEach(function(b){
    b.classList.toggle('active', !!ch && b.dataset.channel === ch);
  });
}

function switchLang(lang) {
  _hideAll();
  _setLangBtn(lang);
  if (lang === 'malayalam') {
    _setSubtabRow(false);
    _setSubtabBtn('');
    var p = document.getElementById('panel-malayalam');
    if (p) p.classList.add('active');
    try { sessionStorage.setItem('activeLang','malayalam');
          sessionStorage.removeItem('activeChannel'); } catch(e){}
  } else {
    switchSubtab('suntv');
    return;
  }
}

function switchSubtab(ch) {
  _hideAll();
  _setLangBtn('tamil');
  _setSubtabRow(true);
  _setSubtabBtn(ch);
  var p = document.getElementById('panel-ch-' + ch);
  if (p) p.classList.add('active');
  try { sessionStorage.setItem('activeLang','tamil');
        sessionStorage.setItem('activeChannel', ch); } catch(e){}
}

document.addEventListener('DOMContentLoaded', function() {
  try {
    var lang = sessionStorage.getItem('activeLang') || 'malayalam';
    var ch   = sessionStorage.getItem('activeChannel') || 'suntv';
    if (lang === 'tamil') { switchSubtab(ch); }
    else { switchLang('malayalam'); }
  } catch(e) { switchLang('malayalam'); }
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
  t.textContent = msg; t.classList.add('show');
  setTimeout(function(){ t.classList.remove('show'); }, 2200);
}

/* ── Play Dailymotion (Tamil or Malayalam) ── */
function playDailymotion(ns, idx) {
  var arr = window.SERIALS[ns]; if (!arr) return;
  var s = arr[idx];             if (!s || !s.dm_id) return;
  _openDailymotionEmbed(s.name, s.dm_id, s.dm_url);
}

/* ── Play JW/HLS (Tamil only) ── */
function playJw(ns, idx) {
  var arr = window.SERIALS[ns]; if (!arr) return;
  var s = arr[idx];             if (!s || !s.jw_url) return;
  _openHlsPlayer(s.name, s.jw_url, true, true);
}

/* ── Malayalam unified play: prefers DM, falls back to video_url ── */
function playSerial(ns, idx) {
  var arr = window.SERIALS[ns]; if (!arr) return;
  var s = arr[idx];             if (!s) return;
  if (s.dm_id) { _openDailymotionEmbed(s.name, s.dm_id, s.dm_url); return; }
  if (s.url)   { _openHlsPlayer(s.name, s.url, false, false); }
}

function _openHlsPlayer(name, url, useCredentials, forceHls) {
  currentUrl = url;
  document.getElementById('modalTitle').textContent = name;
  document.getElementById('modalUrlDisplay').textContent = url;
  var c = document.getElementById('modalVideoContainer');

  var isRumble = url.indexOf('rumble.com/embed') !== -1;
    if (isRumble) {
      c.innerHTML = '<iframe class="dm-embed" src="' + url + '" allowfullscreen allow="autoplay"></iframe>';
      if (hlsPlayer) { hlsPlayer.destroy(); hlsPlayer = null; }
      document.getElementById('modalHlsActions').style.display = 'none';
      document.getElementById('playerModal').classList.add('active');
      return;
    }

  c.innerHTML = '<video id="modalVideo" controls autoplay playsinline></video>';
  var video = document.getElementById('modalVideo');

  if (hlsPlayer) { hlsPlayer.destroy(); hlsPlayer = null; }

  var isHls = forceHls
    || url.indexOf('.m3u8') !== -1
    || url.indexOf('m3u8')  !== -1;

  if (isHls) {
    if (typeof Hls !== 'undefined' && Hls.isSupported()) {
      hlsPlayer = new Hls({
        xhrSetup: function(xhr, xhrUrl) {
          if (useCredentials) { xhr.withCredentials = true; }
        }
      });
      hlsPlayer.loadSource(url);
      hlsPlayer.attachMedia(video);
      hlsPlayer.on(Hls.Events.ERROR, function(event, data) {
        if (data.fatal) {
          showToast('Stream error: ' + data.type);
          console.error('HLS fatal error', data);
        }
      });
    } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = url;
    }
  } else {
    video.src = url;
  }

  document.getElementById('modalHlsActions').style.display = '';
  document.getElementById('playerModal').classList.add('active');
}

function _openDailymotionEmbed(name, dmId, dmUrl) {
  currentUrl = dmUrl || '';
  document.getElementById('modalTitle').textContent = name;
  document.getElementById('modalUrlDisplay').textContent = dmUrl || '';
  var c = document.getElementById('modalVideoContainer');
  c.innerHTML = '<iframe class="dm-embed" src="https://www.dailymotion.com/embed/video/'
    + dmId + '?autoplay=1" allowfullscreen allow="autoplay"></iframe>';
  document.getElementById('modalHlsActions').style.display = 'none';
  document.getElementById('playerModal').classList.add('active');
}

function closePlayer() {
  var c = document.getElementById('modalVideoContainer');
  c.innerHTML = '<video id="modalVideo" controls autoplay playsinline></video>';
  if (hlsPlayer) { hlsPlayer.destroy(); hlsPlayer = null; }
  document.getElementById('modalHlsActions').style.display = '';
  document.getElementById('playerModal').classList.remove('active');
  currentUrl = '';
}

function copyUrl(ns, idx) {
  var arr = window.SERIALS[ns]; if (!arr) return;
  var s = arr[idx]; if (!s) return;
  var url = s.dm_url || s.url || ''; if (url) doCopy(url);
}

function doCopy(text) {
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text)
      .then(function(){ showToast('URL copied!'); })
      .catch(function(){ legacyCopy(text); });
  } else { legacyCopy(text); }
}

function legacyCopy(text) {
  var ta = document.createElement('textarea');
  ta.value = text;
  ta.style.cssText = 'position:fixed;opacity:0;top:0;left:0';
  document.body.appendChild(ta);
  ta.focus(); ta.select();
  try { document.execCommand('copy'); showToast('URL copied!'); }
  catch(e) { showToast('Long-press the URL below to copy'); }
  document.body.removeChild(ta);
}

function openVlc(ns, idx) {
  var url = '';
  if (idx === -1) { url = currentUrl; }
  else {
    var arr = window.SERIALS[ns]; if (!arr) return;
    var s = arr[idx]; if (!s) return;
    url = s.url || s.dm_url || '';
  }
  if (!url) return;
  var ua = navigator.userAgent || '';
  var isIOS = /iPad|iPhone|iPod/.test(ua) && !window.MSStream;
  window.location.href = isIOS
    ? 'vlc-x-callback://x-callback-url/stream?url=' + encodeURIComponent(url)
    : 'vlc://' + url.replace(/^https?:\/\//, '');
  setTimeout(function(){ showToast("VLC not opening? Install VLC or copy the URL."); }, 1800);
}

document.addEventListener('DOMContentLoaded', function() {
  var ov = document.getElementById('playerModal');
  if (ov) ov.addEventListener('click', function(e){ if (e.target===this) closePlayer(); });
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
      <button class="btn btn-vlc"  onclick="openVlc('', -1)">&#x1F4FA; Open in VLC</button>
    </div>
    <div class="modal-url" id="modalUrlDisplay"></div>
  </div>
</div>
"""

# ── Visit badge HTML ───────────────────────────────────────────────────────────
def visit_badge_day() -> str:
    """Badge showing today's visits + total visits (for day pages)."""
    return """<div class="visit-badge">
    <span class="visit-pill">&#x1F4C5;&nbsp;Today&nbsp;<span class="vnum" id="visits-day">\u2026</span></span>
    <span class="visit-pill vtotal">&#x1F310;&nbsp;Total&nbsp;<span class="vnum" id="visits-total">\u2026</span></span>
  </div>"""

def visit_badge_index() -> str:
    """Badge showing only total visits (for the index page)."""
    return """<div class="visit-badge">
    <span class="visit-pill vtotal">&#x1F310;&nbsp;Total visits&nbsp;<span class="vnum" id="visits-total">\u2026</span></span>
  </div>"""

# ── Page builder ───────────────────────────────────────────────────────────────
def build_page(title: str, body: str, serials_js: str, page_id: str = "unknown") -> str:
    """
    Assembles a complete HTML page.
    page_id is passed to counter_js() so each page tracks independently.
    """
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
{counter_js(page_id)}
</body></html>"""

# ── Data helpers ───────────────────────────────────────────────────────────────
def fmt_date(d: str) -> str:
    try: return datetime.strptime(d, "%Y-%m-%d").strftime("%d %b %Y")
    except: return d

def serial_name(s: dict) -> str:
    return s.get("name") or s.get("title") or "Unknown"

def serial_url(s: dict) -> str:
    """Malayalam legacy video_url field."""
    return s.get("video_url") or ""

def serial_dm_id(s: dict) -> str:
    return s.get("dailymotion_id") or ""

def serial_dm_url(s: dict) -> str:
    return s.get("dailymotion_url") or ""

def serial_jw_url(s: dict) -> str:
    """Tamil HLS variant playlist captured by Playwright."""
    return s.get("jwplayer_url") or ""

def has_playable(s: dict) -> bool:
    return bool(serial_url(s) or serial_dm_id(s) or serial_jw_url(s))

def _sort_serials(serials: list) -> list:
    playable = sorted([s for s in serials if has_playable(s)],     key=lambda x: serial_name(x))
    missing  = sorted([s for s in serials if not has_playable(s)], key=lambda x: serial_name(x))
    return playable + missing

# ── JS data builders ──────────────────────────────────────────────────────────

def build_js_data_malayalam(serials: list) -> list:
    """Malayalam: video_url + dailymotion."""
    out = []
    for s in _sort_serials(serials):
        entry = {"name": serial_name(s)}
        url    = serial_url(s)
        dm_id  = serial_dm_id(s)
        dm_url = serial_dm_url(s)
        if url:   entry["url"]    = url
        if dm_id: entry["dm_id"] = dm_id; entry["dm_url"] = dm_url
        out.append(entry)
    return out

def build_js_data_tamil(serials: list) -> list:
    """Tamil: dailymotion_url + jwplayer_url (both independent).
    jw_url is routed through the Cloudflare proxy so hls.js can fetch it
    without CORS errors.
    """
    from urllib.parse import quote as _quote
    out = []
    for s in _sort_serials(serials):
        entry  = {"name": serial_name(s)}
        dm_id  = serial_dm_id(s)
        dm_url = serial_dm_url(s)
        jw_url = serial_jw_url(s)
        if dm_id:  entry["dm_id"] = dm_id; entry["dm_url"] = dm_url
        if jw_url:
            if PROXY_BASE:
                connector = "&url=" if "?" in PROXY_BASE else "?url="
                entry["jw_url"] = f"{PROXY_BASE.rstrip('/')}{connector}{_quote(jw_url, safe='')}"
            else:
                entry["jw_url"] = jw_url
        out.append(entry)
    return out

# ── HTML row builders ─────────────────────────────────────────────────────────

def build_serial_rows_malayalam(serials: list, namespace: str) -> str:
    """Malayalam cards: Play + Copy URL + VLC."""
    rows = ""
    for idx, s in enumerate(_sort_serials(serials)):
        name   = serial_name(s)
        url    = serial_url(s)
        dm_id  = serial_dm_id(s)
        if url or dm_id:
            rows += f"""
      <div class="serial-card">
        <span class="serial-name">{name}</span>
        <div class="btn-row">
          <button class="btn btn-play" onclick="playSerial('{namespace}',{idx})">&#x25B6; Play</button>
          <button class="btn btn-copy" onclick="copyUrl('{namespace}',{idx})">&#x1F4CB; Copy</button>"""
            if url:
                rows += f"""
          <button class="btn btn-vlc" onclick="openVlc('{namespace}',{idx})">&#x1F4FA; VLC</button>"""
            rows += "\n        </div>\n      </div>"
        else:
            err = s.get("error") or "no link"
            rows += f"""
      <div class="serial-card">
        <span class="serial-name no-link">{name}</span>
        <span class="no-link-tag">&#x274C; {err}</span>
      </div>"""
    return rows

def build_serial_rows_tamil(serials: list, namespace: str) -> str:
    """Tamil cards: separate Play buttons for Dailymotion and JW Player.
    No Copy URL button.
    """
    rows = ""
    for idx, s in enumerate(_sort_serials(serials)):
        name   = serial_name(s)
        dm_id  = serial_dm_id(s)
        jw_url = serial_jw_url(s)

        if dm_id or jw_url:
            rows += f"""
      <div class="serial-card">
        <span class="serial-name">{name}</span>
        <div class="btn-row">"""
            if dm_id:
                rows += f"""
          <button class="btn btn-play" onclick="playDailymotion('{namespace}',{idx})">&#x25B6; Player1</button>"""
            if jw_url:
                rows += f"""
          <button class="btn btn-play-jw" onclick="playJw('{namespace}',{idx})">&#x25B6; Player2</button>"""
            rows += "\n        </div>\n      </div>"
        else:
            err = s.get("error") or "no link"
            rows += f"""
      <div class="serial-card">
        <span class="serial-name no-link">{name}</span>
        <span class="no-link-tag">&#x274C; {err}</span>
      </div>"""
    return rows

# ── Load data ──────────────────────────────────────────────────────────────────
TAMIL_CHANNELS = {
    "suntv":    "Sun TV",
    "vijaytv":  "Vijay TV",
    "zeetamil": "Zee Tamil",
}

def load_by_date(pattern):
    result = {}
    for jf in glob.glob(os.path.join(DATA_DIR, pattern)):
        with open(jf, encoding="utf-8") as f:
            data = json.load(f)
        result[data["date"]] = data
    return result

mal_by_date    = load_by_date("serials_malayalam_*.json")
tamil_suntv    = load_by_date("serials_tamil_suntv_*.json")
tamil_vijaytv  = load_by_date("serials_tamil_vijaytv_*.json")
tamil_zeetamil = load_by_date("serials_tamil_zeetamil_*.json")

tamil_by_channel = {
    "suntv":    tamil_suntv,
    "vijaytv":  tamil_vijaytv,
    "zeetamil": tamil_zeetamil,
}

all_dates_set    = (set(mal_by_date) | set(tamil_suntv) |
                    set(tamil_vijaytv) | set(tamil_zeetamil))
all_dates_sorted = sorted(all_dates_set, reverse=True)

# ── Per-day pages ──────────────────────────────────────────────────────────────
today_str     = dt_date.today().isoformat()
index_entries = []

for d in all_dates_sorted:

    # ── Malayalam panel ──────────────────────────────────────────────────────
    mal_data  = mal_by_date.get(d)
    mal_found = mal_total = 0
    mal_js    = []
    mal_rows  = '<p style="color:#555;padding:20px 0">No Malayalam data for this date.</p>'
    if mal_data:
        serials   = mal_data["serials"]
        mal_found = mal_data.get("found", sum(1 for s in serials if has_playable(s)))
        mal_total = mal_data.get("total", len(serials))
        mal_js    = build_js_data_malayalam(serials)
        mal_rows  = build_serial_rows_malayalam(serials, "malayalam")

    mal_panel = f"""
<div class="tab-panel" id="panel-malayalam">
  <div class="container">
    <p class="summary">{mal_found} of {mal_total} links found</p>
    <div class="serial-list">{mal_rows}
    </div>
  </div>
</div>"""

    # ── Tamil: per-channel rows & JS data ─────────────────────────────────────
    tamil_js    = {}
    tamil_stats = {}
    ch_rows     = {}

    for ch_key, ch_label in TAMIL_CHANNELS.items():
        ch_data    = tamil_by_channel[ch_key].get(d)
        ch_serials = ch_data["serials"] if ch_data else []
        found = sum(1 for s in ch_serials if serial_dm_id(s) or serial_jw_url(s))
        total = len(ch_serials)
        tamil_stats[ch_key] = (found, total)
        ns = f"tamil_{ch_key}"
        tamil_js[ch_key] = build_js_data_tamil(ch_serials)
        ch_rows[ch_key]  = (
            build_serial_rows_tamil(ch_serials, ns) if ch_serials
            else '<p style="color:#555;padding:20px 0">No data for this channel.</p>'
        )

    # ── panel-tamil-all: all 3 channels stacked ───────────────────────────────
    all_inner = ""
    for ch_key, ch_label in TAMIL_CHANNELS.items():
        found, total = tamil_stats[ch_key]
        all_inner += f"""
    <div class="channel-block">
      <div class="channel-heading">&#x1F4FA; {ch_label} &mdash; {found} of {total} links</div>
      <div class="serial-list">{ch_rows[ch_key]}
      </div>
    </div>"""

    tamil_all_panel = f"""
<div class="tab-panel" id="panel-tamil-all">
  <div class="container">{all_inner}
  </div>
</div>"""

    # ── Individual channel panels ─────────────────────────────────────────────
    ch_panels = ""
    for ch_key, ch_label in TAMIL_CHANNELS.items():
        found, total = tamil_stats[ch_key]
        ch_panels += f"""
<div class="tab-panel" id="panel-ch-{ch_key}">
  <div class="container">
    <p class="summary">{ch_label} &mdash; {found} of {total} links found</p>
    <div class="serial-list">{ch_rows[ch_key]}
    </div>
  </div>
</div>"""

    # ── Assemble page body ────────────────────────────────────────────────────
    body = f"""
<header>
  <a class="back" href="index.html">&#x2B05;</a>
  <h1>&#x1F4FA; Serials &mdash; {fmt_date(d)}</h1>
  {visit_badge_day()}
</header>
{TAB_BAR_HTML}
{mal_panel}
{tamil_all_panel}
{ch_panels}"""

    js_data = json.dumps({
        "malayalam":      mal_js,
        "tamil_suntv":    tamil_js["suntv"],
        "tamil_vijaytv":  tamil_js["vijaytv"],
        "tamil_zeetamil": tamil_js["zeetamil"],
    }, ensure_ascii=False)

    out_path = os.path.join(OUT_DIR, f"{d}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(build_page(
            f"Serials — {fmt_date(d)}",
            body,
            js_data,
            page_id=d,          # e.g. "2025-05-10" — each day tracked independently
        ))
    print(f"  ✓ {out_path}")

    tamil_total_found = sum(v[0] for v in tamil_stats.values())
    tamil_total_count = sum(v[1] for v in tamil_stats.values())
    index_entries.append({
        "date": d, "label": fmt_date(d),
        "mal_found": mal_found, "mal_total": mal_total,
        "tam_found": tamil_total_found, "tam_total": tamil_total_count,
    })

# ── Index page ─────────────────────────────────────────────────────────────────
def build_date_cards(entries, lang_filter):
    cards = ""
    for entry in entries:
        d     = entry["date"]
        cls   = "date-card today" if d == today_str else "date-card"
        badge = " &#x1F534; Today" if d == today_str else ""
        meta  = (f"{entry['mal_found']}/{entry['mal_total']} links"
                 if lang_filter == "malayalam"
                 else f"{entry['tam_found']}/{entry['tam_total']} links")
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
  {visit_badge_index()}
</header>
{TAB_BAR_HTML}

<div class="tab-panel" id="panel-malayalam">
  <div class="container">
    <p class="summary">{len(index_entries)} days archived</p>
    <div class="date-grid">{mal_cards}
    </div>
  </div>
</div>

<div class="tab-panel" id="panel-tamil-all">
  <div class="container">
    <p class="summary">{len(index_entries)} days archived &mdash; all channels</p>
    <div class="date-grid">{tam_cards}
    </div>
  </div>
</div>

<div class="tab-panel" id="panel-ch-suntv">
  <div class="container">
    <p class="summary">Sun TV &mdash; {len(index_entries)} days archived</p>
    <div class="date-grid">{tam_cards}
    </div>
  </div>
</div>
<div class="tab-panel" id="panel-ch-vijaytv">
  <div class="container">
    <p class="summary">Vijay TV &mdash; {len(index_entries)} days archived</p>
    <div class="date-grid">{tam_cards}
    </div>
  </div>
</div>
<div class="tab-panel" id="panel-ch-zeetamil">
  <div class="container">
    <p class="summary">Zee Tamil &mdash; {len(index_entries)} days archived</p>
    <div class="date-grid">{tam_cards}
    </div>
  </div>
</div>"""

# ── Index page HTML ────────────────────────────────────────────────────────────
# Note: index page does not use build_page() because it has no SERIALS data
# or player modal. Counter is injected manually before </body>.
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
{counter_js("index")}
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