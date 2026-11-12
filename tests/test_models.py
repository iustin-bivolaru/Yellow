from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from yellow.models import Digest, DigestItem, Item, ItemAnalysis, Technology, TechRef, item_id


def _item(published: datetime) -> Item:
    return Item(
        id="x",
        title="t",
        url="https://example.com",
        source="test",
        source_name="Test",
        published=published,
    )


def test_naive_datetime_is_treated_as_utc() -> None:
    it = _item(datetime(2026, 11, 12, 9, 0))
    assert it.published == datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
    assert it.published.utcoffset() == timedelta(0)


def test_aware_datetime_is_converted_to_utc() -> None:
    bucharest_winter = timezone(timedelta(hours=2))
    it = _item(datetime(2026, 11, 12, 11, 0, tzinfo=bucharest_winter))
    assert it.published == datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
    assert it.published.utcoffset() == timedelta(0)


def test_item_id_is_stable_and_distinct() -> None:
    a = item_id("https://example.com/a")
    assert a == item_id("https://example.com/a")
    assert a != item_id("https://example.com/b")
    assert len(a) == 12


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(0, 1), (-3, 1), (3, 3), (9, 5), (3.0, 3), (7.5, 5), ("4", 4), ("9", 5), (0.0, 1)],
)
def test_importance_is_clamped(raw: object, expected: int) -> None:
    a = ItemAnalysis(id="x", category="AI Research", summary="s", importance=raw)
    assert a.importance == expected


def test_digest_generated_at_is_utc() -> None:
    d = Digest(
        date=date(2026, 11, 12),
        generated_at=datetime(2026, 11, 12, 9, 0, tzinfo=timezone(timedelta(hours=2))),
        analyzer="keyword-fallback",
        nutshell="n",
    )
    assert d.generated_at == datetime(2026, 11, 12, 7, 0, tzinfo=UTC)


def test_digest_json_round_trip() -> None:
    item = DigestItem(
        id="abc",
        title="Llama 4 released",
        url="https://example.com/llama",
        source="hackernews",
        source_name="Hacker News",
        published=datetime(2026, 11, 12, 6, 30),
        score=420,
        category="AI Models & Releases",
        summary="Meta released Llama 4.",
        importance=5,
        technologies=["Llama 4"],
    )
    d = Digest(
        date=date(2026, 11, 12),
        generated_at=datetime(2026, 11, 12, 7, 0, tzinfo=UTC),
        analyzer="claude-haiku-5-5",
        nutshell="Three sentences.",
        top5=["abc"],
        items=[item],
        new_tech=[TechRef(name="Llama 4", slug="llama-4", count_today=1)],
    )
    back = Digest.model_validate_json(d.model_dump_json())
    assert back == d
    assert back.date == date(2026, 11, 12)


def test_technology_json_round_trip() -> None:
    t = Technology(
        name="Llama 4",
        slug="llama-4",
        first_seen=date(2026, 11, 10),
        last_seen=date(2026, 11, 12),
        counts={"2026-11-10": 1, "2026-11-12": 3},
        items=["abc"],
    )
    assert Technology.model_validate_json(t.model_dump_json()) == t
