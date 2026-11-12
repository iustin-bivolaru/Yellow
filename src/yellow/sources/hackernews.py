"""Hacker News via the free Algolia search API: stories since `since` above a points threshold."""

from __future__ import annotations

from datetime import UTC, datetime

from yellow.models import Item, item_id
from yellow.sources.base import Source
from yellow.text import canonical_url, html_to_text, is_http_url

API_URL = "https://hn.algolia.com/api/v1/search"
ITEM_URL = "https://news.ycombinator.com/item?id={}"


class HackerNewsSource(Source):
    name = "hackernews"

    def _fetch(self, since: datetime) -> list[Item]:
        scfg = self.cfg.sources.hackernews
        resp = self.client.get(
            API_URL,
            params={
                "tags": "story",
                "numericFilters": f"created_at_i>{int(since.timestamp())},"
                f"points>={scfg.min_points}",
                "hitsPerPage": self.cfg.caps.max_items_per_source,
            },
        )
        resp.raise_for_status()
        return parse(resp.json(), since)


def parse(data: dict, since: datetime) -> list[Item]:
    items: list[Item] = []
    for hit in data.get("hits", []):
        title = (hit.get("title") or "").strip()
        object_id = hit.get("objectID")
        created = hit.get("created_at_i")
        if not title or not object_id or created is None:
            continue
        published = datetime.fromtimestamp(int(created), tz=UTC)
        if published < since:
            continue
        discussion = ITEM_URL.format(object_id)
        url = hit.get("url")
        if not is_http_url(url):  # Ask/Show HN posts have no URL; unsafe schemes are dropped
            url = discussion
        items.append(
            Item(
                id=item_id(canonical_url(url)),
                title=title,
                url=url,
                source="hackernews",
                source_name="Hacker News",
                published=published,
                snippet=html_to_text(hit.get("story_text")),
                score=hit.get("points"),
                discussion_url=discussion,
            )
        )
    return items
