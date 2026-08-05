"""Same-origin TiTiler proxy for local development.

In production Traefik routes ``/tiles`` to ``tiler-cache``. Locally the
dashboard owns ``:80`` / ``localhost``, so browser tile URLs use
``TILER_URL=http://localhost/tiles`` and this Flask route forwards to
``tiler-cache`` on the Docker network — avoiding cross-origin loads from
``127.0.0.1:8002`` that Chrome ORB-blocks when TiTiler returns JSON errors.
"""

from __future__ import annotations

import logging
import os

import requests
from flask import Request, Response, request

logger = logging.getLogger(__name__)

# Hop-by-hop headers must not be forwarded (RFC 7230).
_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


def _proxy_target() -> str:
    return (
        os.environ.get("TILER_PROXY_URL")
        or os.environ.get("TILER_CACHE_URL")
        or "http://tiler-cache"
    ).rstrip("/")


def register_tiler_proxy(server) -> None:
    """Attach ``/tiles/<path>`` reverse-proxy routes to the Dash Flask server."""

    @server.route("/tiles/<path:path>", methods=["GET", "HEAD", "OPTIONS"])
    def proxy_tiles(path: str):
        if request.method == "OPTIONS":
            return Response(
                status=204,
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
                    "Access-Control-Allow-Headers": "Origin, Content-Type, Accept",
                },
            )

        upstream = f"{_proxy_target()}/{path.lstrip('/')}"
        if request.query_string:
            upstream = f"{upstream}?{request.query_string.decode('latin-1')}"

        try:
            upstream_resp = requests.request(
                method=request.method,
                url=upstream,
                headers=_forward_headers(request),
                stream=True,
                timeout=120,
            )
        except requests.RequestException as exc:
            logger.warning("Tiler proxy upstream error for %s: %s", path, exc)
            return Response("Bad Gateway", status=502, mimetype="text/plain")

        excluded = _HOP_BY_HOP | {"content-encoding", "content-length"}
        headers = [
            (key, value)
            for key, value in upstream_resp.headers.items()
            if key.lower() not in excluded
        ]
        return Response(
            upstream_resp.iter_content(chunk_size=16 * 1024),
            status=upstream_resp.status_code,
            headers=headers,
        )


def _forward_headers(req: Request) -> dict[str, str]:
    headers = {}
    for key, value in req.headers:
        if key.lower() in _HOP_BY_HOP or key.lower() == "host":
            continue
        headers[key] = value
    return headers
