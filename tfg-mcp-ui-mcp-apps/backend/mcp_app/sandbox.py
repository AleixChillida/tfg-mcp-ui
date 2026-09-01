from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse

SANDBOX_PATH = Path(__file__).with_name("sandbox.html")
_DOMAIN_BAD_CHARS = re.compile(r"[;\r\n'\" ]")


def _domains(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item or _DOMAIN_BAD_CHARS.search(item):
            continue
        result.append(item)
    return result


def build_csp_header(csp: dict[str, Any] | None) -> str:
    """Build the HTTP CSP for the outer MCP Apps sandbox proxy.

    The proxy is served from a different origin than the React host. Its CSP is
    derived only from the resource-declared MCP Apps policy and sanitized before
    being interpolated into an HTTP header.
    """

    csp = csp if isinstance(csp, dict) else {}
    resource = " ".join(_domains(csp.get("resourceDomains")))
    connect = " ".join(_domains(csp.get("connectDomains")))
    frames = " ".join(_domains(csp.get("frameDomains")))
    base = " ".join(_domains(csp.get("baseUriDomains")))

    def with_extra(prefix: str, extra: str) -> str:
        return f"{prefix} {extra}".strip()

    directives = [
        "default-src 'self' 'unsafe-inline'",
        with_extra("script-src 'self' 'unsafe-inline' blob: data:", resource),
        with_extra("style-src 'self' 'unsafe-inline' blob: data:", resource),
        with_extra("img-src 'self' data: blob:", resource),
        with_extra("font-src 'self' data: blob:", resource),
        with_extra("media-src 'self' data: blob:", resource),
        with_extra("connect-src 'self'", connect),
        with_extra("worker-src 'self' blob:", resource),
        # The proxy itself must host the inner about:blank/same-origin iframe.
        with_extra("frame-src 'self' blob: data:", frames),
        "object-src 'none'",
        f"base-uri {base}" if base else "base-uri 'none'",
        "frame-ancestors http://localhost:5173 http://127.0.0.1:5173",
    ]
    return "; ".join(directives)


def sandbox_response(request: Request) -> HTMLResponse:
    raw = request.query_params.get("csp")
    parsed: dict[str, Any] | None = None
    if raw and len(raw) <= 8192:
        try:
            value = json.loads(raw)
            if isinstance(value, dict):
                parsed = value
        except json.JSONDecodeError:
            parsed = None

    return HTMLResponse(
        SANDBOX_PATH.read_text(encoding="utf-8"),
        headers={
            "Content-Security-Policy": build_csp_header(parsed),
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Content-Type-Options": "nosniff",
        },
    )
