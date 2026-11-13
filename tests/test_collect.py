from datetime import UTC, date, datetime, timedelta

from yellow.collect import (
    Seen,
    collect,
    dedupe,
    filter_seen,
    load_seen,
    mark_seen,
    prune_seen,
    save_seen,
    title_key,
)
from yellow.models import Item, item_id
from yellow.sources.base import Source
from yellow.text import canonical_url

NOW = datetime(2026, 11, 13, 7, tzinfo=UTC)
TODAY = date(2026, 11, 13)


def _item(
    url: str,
    title: str = "A reasonably long headline about models",
    *,
    source: str = "rss",
    score: int | None = None,
    snippet: str | None = None,
    discussion_url: str | None = None,
    hours_ago: int = 1,
) -> Item:
    return Item(
        id=item_id(canonical_url(url)),
        title=title,
        url=url,
        source=source,
        source_name=source,
        published=NOW - timedelta(hours=hours_ago),
        score=score,
        snippet=snippet,
        discussion_url=discussion_url,
    )


class _Fake(Source):
    def __init__(self, name: str, items: list[Item] | None = None, fail: bool = False) -> None:
        self.name = name
        self._items = items or []
        self._fail = fail

    def _fetch(self, since: datetime) -> list[Item]:
        if self._fail:
            raise RuntimeError("boom")
        return self._items


def test_title_key_normalizes_case_punctuation_and_hn_prefix() -> None:
    assert title_key("Show HN: Llama 4 runs on a phone!") == title_key("llama 4 runs on a PHONE")
    assert title_key("Update") is None


def test_dedupe_same_canonical_url_keeps_best_and_fills_gaps() -> None:
    a = _item("https://www.example.com/post/?utm_source=x", snippet="from rss")
    b = _item(
        "http://example.com/post",
        source="hackernews",
        score=300,
        discussion_url="https://news.ycombinator.com/item?id=1",
    )
    out = dedupe([a, b])
    assert len(out) == 1
    assert out[0].source == "hackernews"
    assert out[0].snippet == "from rss"


def test_dedupe_by_title_across_different_urls() -> None:
    a = _item("https://blog.example.com/x", "OpenAI releases a new reasoning model")
    b = _item("https://news.example.org/y", "OpenAI Releases a New Reasoning Model!", score=10)
    c = _item("https://other.example.org/z", "Something completely different today")
    out = dedupe([a, b, c])
    assert [i.url for i in out] == ["https://news.example.org/y", "https://other.example.org/z"]


def test_short_titles_are_not_merged() -> None:
    out = dedupe(
        [_item("https://a.example.com/1", "Update"), _item("https://b.example.com/2", "Update")]
    )
    assert len(out) == 2


def test_seen_filter_mark_prune_roundtrip(tmp_path) -> None:
    old = _item("https://example.com/old", "Yesterday's big model release story")
    retitled = _item("https://mirror.example.com/old", "Yesterday's BIG model release story")
    new = _item("https://example.com/new", "Brand new agent framework launched")

    seen = mark_seen(Seen(), [old], TODAY - timedelta(days=1))
    assert filter_seen([old, retitled, new], seen, TODAY) == [new]
    # Same-day rerun: items marked today are still shown.
    assert filter_seen([old, new], mark_seen(Seen(), [old, new], TODAY), TODAY) == [old, new]

    path = tmp_path / "data" / "seen.json"
    save_seen(path, seen)
    assert load_seen(path) == seen

    # Earlier date is kept when an item is marked again.
    assert mark_seen(seen, [old], TODAY).ids[old.id] == TODAY - timedelta(days=1)

    pruned = prune_seen(seen, TODAY + timedelta(days=40), retention_days=30)
    assert pruned.ids == {} and pruned.titles == {}
    assert prune_seen(seen, TODAY, retention_days=30) == seen


def test_load_seen_missing_or_corrupt_is_empty(tmp_path) -> None:
    assert load_seen(tmp_path / "nope.json") == Seen()
    bad = tmp_path / "seen.json"
    bad.write_text("{not json")
    assert load_seen(bad) == Seen()


def test_collect_survives_failing_source_dedupes_and_sorts() -> None:
    older = _item("https://example.com/a", "First story about inference chips", hours_ago=5)
    newer = _item("https://example.com/b", "Second story about vector databases", hours_ago=1)
    dup = _item(
        "https://www.example.com/a/", "First story about inference chips", score=99, hours_ago=5
    )
    seen_item = _item("https://example.com/c", "Third story that was shown yesterday")
    seen = mark_seen(Seen(), [seen_item], TODAY - timedelta(days=1))

    sources = [
        _Fake("one", [older, seen_item]),
        _Fake("broken", fail=True),
        _Fake("two", [newer, dup]),
    ]
    out = collect(sources, NOW - timedelta(hours=26), seen, TODAY)
    assert [i.url for i in out] == ["https://example.com/b", "https://www.example.com/a/"]
    assert out[1].score == 99


def test_collect_with_no_sources() -> None:
    assert collect([], NOW, Seen(), TODAY) == []


def test_dedupe_is_transitive() -> None:
    a = _item("https://a.example.com/1", "Story alpha about GPU shortages")
    b = _item("https://b.example.com/2", "Story beta about compiler bugs")
    c = _item("https://a.example.com/1/", "Story beta about compiler bugs")  # URL of a, title of b
    assert len(dedupe([a, b, c])) == 1
