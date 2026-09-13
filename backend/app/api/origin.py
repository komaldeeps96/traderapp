"""Which pages may drive this API.

CORS only stops a foreign page *reading* a response; the request itself still
runs, and browsers exempt WebSockets from CORS altogether. So the socket and
every REST route check where a request came from before acting on it.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

from ..core.settings import Settings
from ..services.container import get_container


def origin_allowed(origin: str | None, host: str | None, settings: Settings) -> bool:
    """Whether a page at ``origin`` may talk to this server.

    No Origin means no browser, and anything that is not one can claim whatever
    origin it likes; the loopback rule on orders covers it.
    """
    if origin is None:
        return True
    if origin in settings.cors_origins:
        return True
    if settings.cors_origin_regex and re.fullmatch(settings.cors_origin_regex, origin):
        return True
    # Same origin: the API serving the built UI itself.
    return urlsplit(origin).netloc == host


def refuse_cross_site(request: Request) -> None:
    """403 for a request another site's page made.

    ``Sec-Fetch-Site`` rides every request a current browser makes, including the
    ones CORS never preflights — an image tag, a plain form post. A phone on the
    WiFi reaching :8000 from a page on :3000 is same-site: ports do not count.
    """
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(status_code=403, detail="cross-site request refused")
    origin = request.headers.get("origin")
    if not origin_allowed(origin, request.headers.get("host"), get_container().settings):
        raise HTTPException(status_code=403, detail="origin not allowed")
