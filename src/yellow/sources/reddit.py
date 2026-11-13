"""Reddit via the public "top of the day" Atom feed of all subreddits combined (no API key).

One combined request (r/A+B+C) because Reddit rate-limits back-to-back anonymous requests.

Link posts point at the external article, with the Reddit thread as the discussion link.
Image, video and text posts point at the Reddit thread itself.
"""

from __future__ import annotations

import html
import logging
import re
import time
from datetime import datetime
from urllib.parse import urlsplit

import feedparser

from yellow.models import Item, item_id
from yellow.sources.abstract_source import Source
from yellow.sources.rss import entry_time
from yellow.text import canonical_url, html_to_text, is_http_url

log = logging.getLogger(__name__)

FEED_URL = "https://www.reddit.com/r/{subs}/top/.rss?t=day&limit={limit}"
RETRY_AFTER_429_SECONDS = 5
_LINK_RE = re.compile(r'<a href="([^"]+)">\s*\[link\]\s*</a>')
_SUBMITTED_RE = re.compile(r"\s*submitted by\s+/u/.*$", re.DOTALL)
# Hosts that serve the post's own media; such posts are better read on the thread page.
_REDDIT_HOSTS = ("reddit.com", "redd.it")


class RedditSource(Source):
    """Top posts of the day from each subreddit in sources.reddit.subreddits."""

    name = "reddit"

    def _fetch(self, since: datetime) -> list[Item]:
        """Fetch the combined feed once, retrying a single time if rate-limited (429)."""
        subs = self.cfg.sources.reddit.subreddits
        if not subs:
            return []
        limit = self.cfg.caps.max_items_per_source
        url = FEED_URL.format(subs="+".join(subs), limit=limit)
        resp = self.client.get(url)
        if resp.status_code == 429:
            log.info("reddit rate-limited; retrying once in %ss", RETRY_AFTER_429_SECONDS)
            time.sleep(RETRY_AFTER_429_SECONDS)
            resp = self.client.get(url)
        resp.raise_for_status()
        return parse(resp.content, since)[:limit]


def _is_reddit_host(url: str) -> bool:
    """Return whether `url` is on reddit.com or one of its media hosts (i.redd.it, ...)."""
    host = urlsplit(url).netloc.lower()
    return any(host == h or host.endswith("." + h) for h in _REDDIT_HOSTS)


def _subreddit(entry: feedparser.FeedParserDict) -> str:
    """Return the entry's subreddit from its Atom category, e.g. "LocalLLaMA"; "" if absent."""
    tags = entry.get("tags") or []
    return (tags[0].get("term") or "") if tags else ""


def parse(content: bytes | str, since: datetime) -> list[Item]:
    """Turn a (combined) subreddit Atom feed into Items published at or after `since`."""
    parsed = feedparser.parse(content)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"unparseable feed: {parsed.get('bozo_exception')}")
    items: list[Item] = []
    for entry in parsed.entries:
        title = html_to_text(entry.get("title"), limit=300)
        thread = (entry.get("link") or "").strip()
        published = entry_time(entry)
        if not title or not is_http_url(thread) or published is None or published < since:
            continue
        body = entry.get("summary") or ""
        m = _LINK_RE.search(body)
        link = html.unescape(m.group(1)) if m else thread
        url = link if is_http_url(link) and not _is_reddit_host(link) else thread
        snippet = _SUBMITTED_RE.sub("", html_to_text(body) or "").strip() or None
        items.append(
            Item(
                id=item_id(canonical_url(url)),
                title=title,
                url=url,
                source="reddit",
                source_name=f"r/{sub}" if (sub := _subreddit(entry)) else "Reddit",
                published=published,
                snippet=snippet,
                discussion_url=thread,
            )
        )
    return items
