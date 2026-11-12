"""Small text/URL helpers shared by source adapters and the collector."""

from __future__ import annotations

import html
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


_TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref_src"}


def html_to_text(raw: str | None, limit: int = 1000) -> str | None:
    """Strip tags and entities, collapse whitespace, truncate. Returns None for empty input."""
    if not raw:
        return None
    text = _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", raw))).strip()
    if not text:
        return None
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def is_http_url(url: str | None) -> bool:
    """True only for absolute http(s) URLs. Blocks javascript:, data: and friends from feeds."""
    if not url:
        return False
    parts = urlsplit(url.strip())
    return parts.scheme.lower() in {"http", "https"} and bool(parts.netloc)


def canonical_url(url: str) -> str:
    """Normalize a URL so the same story from different sources gets the same id.

    Uses https for http and https alike, lowercases the host, drops "www.", the fragment,
    tracking params (utm_* etc.) and a trailing slash. Remaining query params are sorted.
    """
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    query = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_PARAMS
    )
    path = parts.path.rstrip("/") or ""
    return urlunsplit(("https", host, path, urlencode(query), ""))
