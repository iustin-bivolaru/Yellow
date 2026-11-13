"""arXiv via its public export API: the newest submissions in the configured categories.

Heavily capped (sources.arxiv.max_items). The same paper often also appears in Hugging Face daily
papers; the collector merges them by title and keeps the copy with upvotes.
"""

from __future__ import annotations

import re
from datetime import datetime

import feedparser

from yellow.models import Item, item_id
from yellow.sources.abstract_source import Source
from yellow.sources.rss import entry_time
from yellow.text import canonical_url, html_to_text, is_http_url

API_URL = "https://export.arxiv.org/api/query"
_VERSION_RE = re.compile(r"v\d+$")


class ArxivSource(Source):
    """Newest arXiv papers in sources.arxiv.categories."""

    name = "arxiv"

    def _fetch(self, since: datetime) -> list[Item]:
        """Run one query OR-ing all categories, newest first, and parse it."""
        scfg = self.cfg.sources.arxiv
        if not scfg.categories:
            return []
        resp = self.client.get(
            API_URL,
            params={
                "search_query": " OR ".join(f"cat:{c}" for c in scfg.categories),
                "sortBy": "submittedDate",
                "sortOrder": "descending",
                "max_results": scfg.max_items,
            },
        )
        resp.raise_for_status()
        return parse(resp.content, since)[: scfg.max_items]


def parse(content: bytes | str, since: datetime) -> list[Item]:
    """Turn an arXiv API Atom response into Items published at or after `since`."""
    parsed = feedparser.parse(content)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"unparseable arXiv response: {parsed.get('bozo_exception')}")
    items: list[Item] = []
    for entry in parsed.entries:
        title = html_to_text(entry.get("title"), limit=300)
        # Drop the version suffix so v1 and v2 of a paper are the same story.
        url = _VERSION_RE.sub("", (entry.get("link") or "").strip())
        published = entry_time(entry)
        if not title or not is_http_url(url) or published is None or published < since:
            continue
        items.append(
            Item(
                id=item_id(canonical_url(url)),
                title=title,
                url=url,
                source="arxiv",
                source_name="arXiv",
                published=published,
                snippet=html_to_text(entry.get("summary"), limit=500),
            )
        )
    return items
