"""Generic RSS/Atom adapter. The feed list lives in config.yaml under sources.rss.feeds."""

from __future__ import annotations

import calendar
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import feedparser

from yellow.config import RssFeed
from yellow.models import Item, item_id
from yellow.sources.base import Source
from yellow.text import canonical_url, html_to_text, is_http_url

log = logging.getLogger(__name__)


class RssSource(Source):
    name = "rss"

    def _fetch(self, since: datetime) -> list[Item]:
        feeds = self.cfg.sources.rss.feeds
        if not feeds:
            return []
        with ThreadPoolExecutor(max_workers=min(8, len(feeds))) as pool:
            results = pool.map(lambda f: self._fetch_feed(f, since), feeds)
        return [item for batch in results for item in batch]

    def _fetch_feed(self, feed: RssFeed, since: datetime) -> list[Item]:
        """One feed failing must not drop the others, so errors are isolated per feed."""
        try:
            resp = self.client.get(feed.url)
            resp.raise_for_status()
            items = parse(resp.content, feed.name, since)
        except Exception as e:
            log.warning("rss feed %s failed: %s: %s", feed.name, type(e).__name__, e)
            return []
        items.sort(key=lambda i: i.published, reverse=True)  # some feeds list oldest-first
        return items[: self.cfg.caps.max_items_per_source]


def _entry_time(entry: feedparser.FeedParserDict) -> datetime | None:
    # feedparser normalizes *_parsed to a UTC struct_time
    for key in ("published_parsed", "updated_parsed"):
        st = entry.get(key)
        if st:
            return datetime.fromtimestamp(calendar.timegm(st), tz=UTC)
    return None


def parse(content: bytes | str, feed_name: str, since: datetime) -> list[Item]:
    parsed = feedparser.parse(content)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"unparseable feed: {parsed.get('bozo_exception')}")
    items: list[Item] = []
    for entry in parsed.entries:
        title = html_to_text(entry.get("title"), limit=300)
        link = (entry.get("link") or "").strip()
        published = _entry_time(entry)
        if not title or not is_http_url(link) or published is None or published < since:
            continue  # unsafe/missing links and undated entries are skipped
        items.append(
            Item(
                id=item_id(canonical_url(link)),
                title=title,
                url=link,
                source="rss",
                source_name=feed_name,
                published=published,
                snippet=html_to_text(entry.get("summary")),
            )
        )
    return items
