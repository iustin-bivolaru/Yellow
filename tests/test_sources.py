import json
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest

from tests.conftest import FIXTURES
from yellow.config import Config, RssFeed
from yellow.models import Item
from yellow.sources import enabled_sources, hackernews, rss
from yellow.sources.abstract_source import Source

SINCE = datetime(2026, 11, 10, tzinfo=UTC)


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# --- Hacker News ---------------------------------------------------------------------------


def test_hackernews_parses_fixture() -> None:
    data = json.loads((FIXTURES / "hackernews.json").read_text())
    items = hackernews.parse(data, SINCE)
    assert len(items) == len(data["hits"])
    first = items[0]
    assert first.source == "hackernews"
    assert first.score and first.score >= 50
    assert first.discussion_url and first.discussion_url.startswith(
        "https://news.ycombinator.com/item?id="
    )
    assert first.published.tzinfo is not None
    assert len({i.id for i in items}) == len(items)


def test_hackernews_post_without_url_links_to_discussion() -> None:
    data = json.loads((FIXTURES / "hackernews.json").read_text())
    pairs = zip(hackernews.parse(data, SINCE), data["hits"], strict=True)
    no_url = [i for i, h in pairs if not h.get("url")]
    assert no_url, "fixture should contain an Ask/Show HN post"
    assert all(i.url == i.discussion_url for i in no_url)


def test_hackernews_filters_old_items() -> None:
    data = json.loads((FIXTURES / "hackernews.json").read_text())
    assert hackernews.parse(data, datetime(2100, 1, 1, tzinfo=UTC)) == []


def test_hackernews_fetch_sends_filters(cfg: Config) -> None:
    seen: dict[str, str] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(req.url.params)
        return httpx.Response(200, content=(FIXTURES / "hackernews.json").read_bytes())

    items = hackernews.HackerNewsSource(cfg, _client(handler)).fetch(SINCE)
    assert items
    assert seen["tags"] == "story"
    assert f"created_at_i>{int(SINCE.timestamp())}" in seen["numericFilters"]
    assert f"points>={cfg.sources.hackernews.min_points}" in seen["numericFilters"]


# --- RSS / Atom ----------------------------------------------------------------------------


@pytest.mark.parametrize("fixture", ["rss_techcrunch.xml", "atom_verge.xml"])
def test_rss_parses_rss_and_atom(fixture: str) -> None:
    items = rss.parse((FIXTURES / fixture).read_bytes(), "Feed", SINCE)
    assert items
    for it in items:
        assert it.source == "rss" and it.source_name == "Feed"
        assert it.url.startswith("http")
        assert "<" not in it.title
        assert it.snippet is None or "<" not in it.snippet
        assert it.published >= SINCE


def test_rss_one_bad_feed_does_not_drop_others(cfg: Config) -> None:
    good = (FIXTURES / "rss_techcrunch.xml").read_bytes()

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500) if "bad" in req.url.host else httpx.Response(200, content=good)

    cfg = cfg.model_copy(deep=True)
    cfg.sources.rss.feeds = [
        RssFeed(name="Bad", url="https://bad.example/feed"),
        RssFeed(name="Good", url="https://good.example/feed"),
    ]
    items = rss.RssSource(cfg, _client(handler)).fetch(SINCE)
    assert items and {i.source_name for i in items} == {"Good"}


def test_rss_caps_items_per_feed(cfg: Config) -> None:
    good = (FIXTURES / "rss_techcrunch.xml").read_bytes()
    cfg = cfg.model_copy(deep=True)
    cfg.caps.max_items_per_source = 3
    cfg.sources.rss.feeds = [RssFeed(name="Good", url="https://good.example/feed")]
    items = rss.RssSource(cfg, _client(lambda r: httpx.Response(200, content=good))).fetch(SINCE)
    assert len(items) == 3


UNSAFE_RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>
<item><title>Evil</title><link>javascript:alert(1)</link>
<pubDate>Thu, 12 Nov 2026 10:00:00 +0000</pubDate></item>
<item><title>Data</title><link>data:text/html,hi</link>
<pubDate>Thu, 12 Nov 2026 10:00:00 +0000</pubDate></item>
<item><title>Fine</title><link>https://example.com/fine</link>
<pubDate>Thu, 12 Nov 2026 10:00:00 +0000</pubDate></item>
<item><title>Old</title><link>https://example.com/old</link>
<pubDate>Mon, 01 Jan 2024 10:00:00 +0000</pubDate></item>
<item><title>Newest</title><link>https://example.com/newest</link>
<pubDate>Thu, 12 Nov 2026 12:00:00 +0000</pubDate></item>
</channel></rss>"""


def test_rss_drops_unsafe_links() -> None:
    titles = [i.title for i in rss.parse(UNSAFE_RSS, "X", SINCE)]
    assert "Evil" not in titles and "Data" not in titles
    assert "Fine" in titles


def test_rss_cap_keeps_newest(cfg: Config) -> None:
    cfg = cfg.model_copy(deep=True)
    cfg.caps.max_items_per_source = 1
    cfg.sources.rss.feeds = [RssFeed(name="X", url="https://x.example/feed")]
    client = _client(lambda r: httpx.Response(200, content=UNSAFE_RSS))
    assert [i.title for i in rss.RssSource(cfg, client).fetch(SINCE)] == ["Newest"]


def test_hackernews_unsafe_url_falls_back_to_discussion() -> None:
    hit = {
        "objectID": "1",
        "title": "Evil",
        "url": "javascript:alert(1)",
        "created_at_i": int(SINCE.timestamp()) + 60,
        "points": 100,
    }
    [item] = hackernews.parse({"hits": [hit]}, SINCE)
    assert item.url == "https://news.ycombinator.com/item?id=1"


def test_rss_garbage_is_not_a_crash() -> None:
    with pytest.raises(ValueError):
        rss.parse(b"<html>not a feed", "X", SINCE)


# --- base / registry -----------------------------------------------------------------------


class _Boom(Source):
    name = "boom"

    def _fetch(self, since: datetime) -> list[Item]:
        raise RuntimeError("network down")


def test_failing_source_returns_empty_list(cfg: Config) -> None:
    assert _Boom(cfg, _client(lambda r: httpx.Response(200))).fetch(SINCE) == []


def test_enabled_sources_only_returns_implemented_enabled(cfg: Config) -> None:
    names = {s.name for s in enabled_sources(cfg, _client(lambda r: httpx.Response(200)))}
    assert names == {"hackernews", "rss"}
    cfg = cfg.model_copy(deep=True)
    cfg.sources.hackernews.enabled = False
    names = {s.name for s in enabled_sources(cfg, _client(lambda r: httpx.Response(200)))}
    assert names == {"rss"}
