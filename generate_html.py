"""
generate_html.py
Reads all data/serials_YYYY-MM-DD.json files and builds:
  docs/index.html      — date list (home page)
  docs/YYYY-MM-DD.html — per-day page with playable HLS links
"""

import json
import os
import glob
from datetime import datetime

DATA_DIR = "data"
OUT_DIR  = "docs"

os.makedirs(OUT_DIR, exist_ok=True)

# ── Common styles + HLS player (hls.js) ───────────────────────────────────────
HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #0f0f0f; color: #e8e8e8; min-height: 100vh;
  }}
  header {{
    background: #1a1a2e; padding: 16px 24px;
    display: flex; align-items: center; gap: 16px;
    border-bottom: 2px solid #e94560;
  }}
  header a {{ color: #e94560; text-decoration: none; font-size: 1.4rem; }}
  header h1 {{ font-size: 1.2rem; color: #e8e8e8; }}
  .container {{ max-width: 960px; margin: 0 auto; padding: 24px 16px; }}
  .date-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 12px; margin-top: 16px;
  }}
  .date-card {{
    background: #1a1a2e; border: 1px solid #2a2a4a;
    border-radius: 10px; padding: 16px; text-align: center;
    text-decoration: none; color: #e8e8e8;
    transition: border-color .2s, transform .2s;
  }}
  .date-card:hover {{ border-color: #e94560; transform: translateY(-2px); }}
  .date-card .date-label {{ font-size: 1rem; font-weight: 600; }}
  .date-card .date-meta  {{ font-size: 0.78rem; color: #888; margin-top: 4px; }}
  .date-card.today {{ border-color: #e94560; }}

  .serial-list {{ margin-top: 16px; display: flex; flex-direction: column; gap: 10px; }}
  .serial-card {{
    background: #1a1a2e; border: 1px solid #2a2a4a;
    border-radius: 10px; padding: 16px;
    display: flex; align-items: center; justify-content: space-between;
    gap: 12px;
  }}
  .serial-name {{ font-size: 0.98rem; font-weight: 500; flex: 1; }}
  .serial-name.no-link {{ color: #555; }}
  .btn {{
    padding: 8px 18px; border-radius: 6px; border: none;
    cursor: pointer; font-size: 0.85rem; font-weight: 600;
    text-decoration: none; white-space: nowrap;
  }}
  .btn-play {{ background: #e94560; color: #fff; }}
  .btn-play:hover {{ background: #c73652; }}
  .btn-copy {{ background: #2a2a4a; color: #aaa; margin-left: 6px; }}
  .btn-copy:hover {{ background: #3a3a6a; color: #fff; }}
  .no-link-tag {{ color: #555; font-size: 0.8rem; }}

  /* Modal player */
  .modal-overlay {{
    display: none; position: fixed; inset: 0;
    background: rgba(0,0,0,.85); z-index: 1000;
    align-items: center; justify-content: center;
  }}
  .modal-overlay.active {{ display: flex; }}
  .modal {{
    background: #1a1a2e; border-radius: 12px;
    width: 90%; max-width: 860px; padding: 20px;
    position: relative;
  }}
  .modal-title {{
    font-size: 1rem; font-weight: 600; margin-bottom: 12px;
    color: #e94560;
  }}
  .modal video {{ width: 100%; border-radius: 8px; background: #000; }}
  .modal-close {{
    position: absolute; top: 12px; right: 16px;
    background: none; border: none; color: #aaa;
    font-size: 1.4rem; cursor: pointer;
  }}
  .modal-close:hover {{ color: #fff; }}
  .modal-fallback {{
    margin-top: 10px; font-size: 0.82rem; color: #666; word-break: break-all;
  }}
  .modal-fallback a {{ color: #e94560; }}

  .back-link {{ display: inline-block; margin-bottom: 20px; color: #e94560; text-decoration: none; }}
  .back-link:hover {{ text-decoration: underline; }}
  .summary {{ color: #666; font-size: 0.85rem; margin-bottom: 4px; }}
</style>
</head>
<body>
"""

FOOT = """
<!-- Modal player -->
<div class="modal-overlay" id="playerModal">
  <div class="modal">
    <button class="modal-close" onclick="closePlayer()">✕</button>
    <div class="modal-title" id="modalTitle"></div>
    <video id="modalVideo" controls autoplay playsinline></video>
    <div class="modal-fallback">
      Can't play inline?
      <a id="modalVlcLink" href="#">Open in VLC</a> &nbsp;|&nbsp;
      <span id="modalUrlText" style="color:#888"></span>
    </div>
  </div>
</div>

<script>
var hls = null;

function playSerial(name, url) {
  document.getElementById('modalTitle').textContent = name;
  document.getElementById('modalUrlText').textContent = url;
  document.getElementById('modalVlcLink').href = 'vlc://' + url;
  var video = document.getElementById('modalVideo');

  if (hls) { hls.destroy(); hls = null; }

  if (url.endsWith('.m3u8') || url.includes('.m3u8')) {
    if (Hls.isSupported()) {
      hls = new Hls();
      hls.loadSource(url);
      hls.attachMedia(video);
    } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
      // Safari native HLS
      video.src = url;
    }
  } else {
    video.src = url;
  }

  document.getElementById('playerModal').classList.add('active');
}

function closePlayer() {
  var video = document.getElementById('modalVideo');
  video.pause();
  video.src = '';
  if (hls) { hls.destroy(); hls = null; }
  document.getElementById('playerModal').classList.remove('active');
}

function copyUrl(url) {
  navigator.clipboard.writeText(url).then(function() {
    alert('Copied!');
  });
}

// Close on overlay click
document.getElementById('playerModal').addEventListener('click', function(e) {
  if (e.target === this) closePlayer();
});
</script>
</body></html>
"""


def fmt_date(d: str) -> str:
    try:
        return datetime.strptime(d, "%Y-%m-%d").strftime("%d %b %Y")
    except:
        return d


# ── Build per-day pages ────────────────────────────────────────────────────────
json_files = sorted(glob.glob(os.path.join(DATA_DIR, "serials_*.json")), reverse=True)
all_dates  = []   # [{date, label, found, total}]

for jf in json_files:
    with open(jf, encoding="utf-8") as f:
        data = json.load(f)

    d      = data["date"]
    serials = data["serials"]
    found  = data.get("found", sum(1 for s in serials if s.get("video_url")))
    total  = data.get("total", len(serials))

    all_dates.append({"date": d, "label": fmt_date(d), "found": found, "total": total})

    # ── Per-day HTML ──────────────────────────────────────────────────────
    rows = ""
    for s in sorted(serials, key=lambda x: x["name"]):
        name = s["name"]
        url  = s.get("video_url")
        if url:
            rows += f"""
        <div class="serial-card">
          <span class="serial-name">{name}</span>
          <div>
            <button class="btn btn-play" onclick="playSerial({json.dumps(name)}, {json.dumps(url)})">▶ Play</button>
            <button class="btn btn-copy" onclick="copyUrl({json.dumps(url)})">Copy URL</button>
          </div>
        </div>"""
        else:
            err = s.get("error", "no link")
            rows += f"""
        <div class="serial-card">
          <span class="serial-name no-link">{name}</span>
          <span class="no-link-tag">❌ {err}</span>
        </div>"""

    day_html = HEAD.format(title=f"Serials — {fmt_date(d)}") + f"""
<header>
  <a href="index.html">⬅</a>
  <h1>📺 Serials — {fmt_date(d)}</h1>
</header>
<div class="container">
  <p class="summary">{found} of {total} links found</p>
  <div class="serial-list">{rows}
  </div>
</div>
""" + FOOT

    out_path = os.path.join(OUT_DIR, f"{d}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(day_html)
    print(f"  ✓ {out_path}")


# ── Build index page ───────────────────────────────────────────────────────────
from datetime import date as dt_date
today_str = dt_date.today().isoformat()

cards = ""
for entry in all_dates:
    cls   = "date-card today" if entry["date"] == today_str else "date-card"
    badge = " 🔴 Today" if entry["date"] == today_str else ""
    cards += f"""
    <a href="{entry['date']}.html" class="{cls}">
      <div class="date-label">{entry['label']}{badge}</div>
      <div class="date-meta">{entry['found']}/{entry['total']} links</div>
    </a>"""

index_html = HEAD.format(title="Serials Archive") + f"""
<header>
  <h1>📺 ShaSeria Archive</h1>
</header>
<div class="container">
  <p class="summary">{len(all_dates)} days archived</p>
  <div class="date-grid">{cards}
  </div>
</div>
""" + FOOT

with open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8") as f:
    f.write(index_html)

print(f"\n✓ index.html + {len(all_dates)} day pages built in docs/")