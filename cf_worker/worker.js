/**
 * PyPI proxy - routes `pip install` traffic through Cloudflare's edge
 * instead of a direct connection to pypi.org/files.pythonhosted.org, for
 * cases where an ISP throttles that direct connection specifically
 * (observed: a PySide6 wheel crawling at ~200 kB/s on an otherwise fast
 * link, 16+ minutes for a single file).
 *
 * Deploy with cf_worker/deploy.sh, then set OCUT_PYPI_PROXY to the
 * printed worker URL before running run.sh/run.ps1 - see README.md.
 *
 * Routing:
 *   /simple/...  and everything else -> https://pypi.org/...
 *   /files/...                       -> https://files.pythonhosted.org/...
 *
 * pip's index pages (PEP 503 /simple/<pkg>/ HTML, and PEP 658 .metadata
 * links) point straight at files.pythonhosted.org - those links get
 * rewritten to route back through this worker's own /files/ path so the
 * actual (large) wheel/sdist download also goes through Cloudflare's
 * edge instead of pip following the link straight to the real host.
 */
const UPSTREAM_INDEX = "https://pypi.org";
const UPSTREAM_FILES = "https://files.pythonhosted.org";

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const isFile = url.pathname.startsWith("/files/");
    const upstreamBase = isFile ? UPSTREAM_FILES : UPSTREAM_INDEX;
    const upstreamPath = isFile ? url.pathname.slice("/files".length) : url.pathname;
    const upstreamUrl = upstreamBase + upstreamPath + url.search;

    const upstreamRequest = new Request(upstreamUrl, {
      method: request.method,
      headers: request.headers,
    });
    upstreamRequest.headers.delete("host");

    const response = await fetch(upstreamRequest, {
      cf: {
        // Wheels/sdists are immutable once published on PyPI - safe to
        // cache aggressively at Cloudflare's edge so a repeat install
        // (or a second machine using the same worker) doesn't need a
        // round trip to the real origin at all.
        cacheEverything: true,
        cacheTtl: 2592000, // 30 days
      },
    });

    const contentType = response.headers.get("content-type") || "";
    if (!contentType.includes("text/html")) {
      return response;
    }

    let html = await response.text();
    html = html.split(UPSTREAM_FILES).join(url.origin + "/files");

    // Rewriting the body changed its byte length - drop the original
    // content-length so the platform recomputes it, instead of shipping
    // a header that no longer matches the actual response body.
    const headers = new Headers(response.headers);
    headers.delete("content-length");
    return new Response(html, { status: response.status, statusText: response.statusText, headers });
  },
};
