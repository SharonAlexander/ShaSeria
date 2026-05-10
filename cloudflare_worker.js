/**
 * Cloudflare Worker — HLS proxy for coke.infamous.network
 *
 * Deploy:
 *   1. Go to https://workers.cloudflare.com  (free account)
 *   2. Create a new Worker
 *   3. Paste this entire file
 *   4. Deploy → you get a URL like https://hls-proxy.YOUR-NAME.workers.dev
 *   5. In generate_html.py set:  PROXY_BASE = "https://hls-proxy.YOUR-NAME.workers.dev"
 *
 * How it works:
 *   Your page calls:  https://hls-proxy.../proxy?url=<encoded m3u8 url>
 *   Worker fetches the URL server-side (no CORS), rewrites all segment/playlist
 *   URIs inside m3u8 files to also go through the proxy, returns with
 *   Access-Control-Allow-Origin: * so hls.js can read it freely.
 *
 * Only allows requests to coke.infamous.network and groovy.monster for safety.
 */

const ALLOWED_HOSTS = [
  "coke.infamous.network",
  "groovy.monster",
];

// Headers sent to the CDN to mimic the Firefox extension behaviour.
// Key insight from network capture:
//   Sec-Fetch-Site: same-origin  ← extension achieves this by acting as browser nav
//   No Origin or Referer         ← extension strips them
// We can't set Sec-Fetch-* from a Worker (browser-controlled), but we can
// omit Origin/Referer and set a clean User-Agent which achieves the same effect
// since the CDN sees a plain GET with no cross-origin signals.
const CDN_HEADERS = {
  "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:150.0) Gecko/20100101 Firefox/150.0",
  "Accept":          "*/*",
  "Accept-Language": "en-US,en;q=0.9",
  "Accept-Encoding": "gzip, deflate, br",
  "Connection":      "keep-alive",
};

const CORS_HEADERS = {
  "Access-Control-Allow-Origin":  "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "*",
};

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // ── CORS preflight ────────────────────────────────────────────────────────
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS_HEADERS });
    }

    // ── Only handle /proxy?url=... ────────────────────────────────────────────
    if (url.pathname !== "/proxy") {
      return new Response("Not found", { status: 404 });
    }

    const targetUrl = url.searchParams.get("url");
    if (!targetUrl) {
      return new Response("Missing ?url= parameter", { status: 400 });
    }

    // ── Safety: only proxy allowed CDN hosts ──────────────────────────────────
    let targetParsed;
    try {
      targetParsed = new URL(targetUrl);
    } catch {
      return new Response("Invalid URL", { status: 400 });
    }

    const allowed = ALLOWED_HOSTS.some(h => targetParsed.hostname === h || targetParsed.hostname.endsWith("." + h));
    if (!allowed) {
      return new Response(`Host not allowed: ${targetParsed.hostname}`, { status: 403 });
    }

    // ── Fetch from CDN ────────────────────────────────────────────────────────
    let cdnResponse;
    try {
      cdnResponse = await fetch(targetUrl, {
        method:  "GET",
        headers: CDN_HEADERS,
        // Don't follow redirects blindly — surface them
        redirect: "follow",
      });
    } catch (err) {
      return new Response(`Upstream fetch failed: ${err.message}`, { status: 502 });
    }

    const contentType = cdnResponse.headers.get("content-type") || "";
    const isM3u8 = (
      contentType.includes("mpegurl") ||
      targetUrl.endsWith(".m3u8") ||
      targetUrl.includes("/stream/variant/")
    );

    // ── M3U8: rewrite URIs to go through this proxy ───────────────────────────
    if (isM3u8) {
      const text     = await cdnResponse.text();
      const rewritten = rewriteM3u8(text, targetUrl, request.url);
      return new Response(rewritten, {
        status: cdnResponse.status,
        headers: {
          ...CORS_HEADERS,
          "Content-Type":  "application/vnd.apple.mpegurl",
          "Cache-Control": "no-cache",
        },
      });
    }

    // ── Binary segments: stream through as-is ────────────────────────────────
    const responseHeaders = new Headers(CORS_HEADERS);
    responseHeaders.set("Content-Type", contentType || "video/MP2T");

    // Pass through content-length if present
    const cl = cdnResponse.headers.get("content-length");
    if (cl) responseHeaders.set("Content-Length", cl);

    return new Response(cdnResponse.body, {
      status:  cdnResponse.status,
      headers: responseHeaders,
    });
  },
};

/**
 * Rewrite all URIs inside an m3u8 playlist so every segment and sub-playlist
 * request routes through this proxy.
 * Handles absolute URLs, relative paths, and URI="..." attributes.
 */
function rewriteM3u8(content, originalUrl, workerUrl) {
  const base      = originalUrl.substring(0, originalUrl.lastIndexOf("/") + 1);
  const proxyBase = new URL(workerUrl).origin + "/proxy";

  const lines = content.split("\n").map(line => {
    const trimmed = line.trim();
    if (!trimmed) return line;

    // Rewrite URI="..." inside tags (EXT-X-KEY, EXT-X-MAP, etc.)
    line = line.replace(/URI="([^"]+)"/g, (_, inner) => {
      const abs = inner.startsWith("http") ? inner : base + inner;
      return `URI="${proxyBase}?url=${encodeURIComponent(abs)}"`;
    });

    // Rewrite bare segment/playlist lines (no leading #)
    if (!trimmed.startsWith("#")) {
      const abs = trimmed.startsWith("http") ? trimmed : base + trimmed;
      return `${proxyBase}?url=${encodeURIComponent(abs)}`;
    }

    return line;
  });

  return lines.join("\n");
}