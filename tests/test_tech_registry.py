import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from yellow.config import RegistryConfig
from yellow.models import Digest, DigestItem, Technology
from yellow.tech_registry import (
    annotate_digest,
    known_names,
    load_registry,
    save_registry,
    slugify,
    update_registry,
)

DAY = date(2026, 11, 13)
CFG = RegistryConfig()


def _digest(day: date, items: dict[str, list[str]]) -> Digest:
    return Digest(
        date=day,
        generated_at=datetime(2026, 11, 13, 7, tzinfo=UTC),
        analyzer="test",
        nutshell="",
        items=[
            DigestItem(
                id=i,
                title=i,
                url=f"https://example.com/{i}",
                source="s",
                source_name="S",
                published=datetime(2026, 11, 13, tzinfo=UTC),
                technologies=techs,
            )
            for i, techs in items.items()
        ],
    )


def _tech(name: str, counts: dict[date, int]) -> Technology:
    days = sorted(counts)
    return Technology(
        name=name,
        slug=slugify(name),
        first_seen=days[0],
        last_seen=days[-1],
        counts={d.isoformat(): n for d, n in counts.items()},
    )


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("Llama 4", "llama-4"),
        ("GPT-5", "gpt-5"),
        ("gpt 5", "gpt-5"),
        ("  C++ / Rust!! ", "c-plus-plus-rust"),
        ("C", "c"),
        ("C++", "c-plus-plus"),
        ("C#", "c-sharp"),
        (".NET", "dot-net"),
        ("Net", "net"),
        ("Node.js", "node-js"),
        ("Café Ünï", "cafe-uni"),
    ],
)
def test_slugify(name: str, slug: str) -> None:
    assert slugify(name) == slug


def test_slugify_fallback_for_non_ascii() -> None:
    s = slugify("大規模言語モデル")
    assert s.startswith("t-") and len(s) == 10
    assert s == slugify("大規模言語モデル")
    assert s != slugify("別の名前")


def test_new_tech_on_first_day() -> None:
    reg = update_registry({}, _digest(DAY, {"a": ["Llama 4"], "b": ["Llama 4", "GPT-5"]}))
    assert reg["llama-4"].counts == {"2026-11-13": 2}
    assert reg["llama-4"].items == {"2026-11-13": ["a", "b"]}
    assert reg["gpt-5"].first_seen == reg["gpt-5"].last_seen == DAY
    out = annotate_digest(_digest(DAY, {}), reg, CFG)
    assert [t.slug for t in out.new_tech] == ["llama-4", "gpt-5"]
    assert out.trending_tech == []


def test_counts_once_per_item_and_first_spelling_wins() -> None:
    reg = update_registry({}, _digest(DAY, {"a": ["GPT-5", "gpt 5", "GPT 5"]}))
    assert list(reg) == ["gpt-5"]
    assert reg["gpt-5"].counts == {"2026-11-13": 1}
    assert reg["gpt-5"].name == "GPT-5"
    reg2 = update_registry(reg, _digest(DAY + timedelta(days=1), {"b": ["gpt 5"]}))
    assert reg2["gpt-5"].name == "GPT-5"


def test_same_day_rerun_is_idempotent() -> None:
    first = _digest(DAY, {"a": ["Alpha", "Beta"], "b": ["Alpha"]})
    second = _digest(DAY, {"a": ["Alpha"], "c": ["Alpha", "Gamma"]})
    once = update_registry({}, second)
    twice = update_registry(update_registry({}, first), second)
    assert twice.keys() == once.keys() == {"alpha", "gamma"}  # "beta" only in the first run
    assert twice == once
    assert twice["alpha"].items == {"2026-11-13": ["a", "c"]}  # "b" was dropped in the rerun


def test_rerun_keeps_other_days_and_recomputes_dates() -> None:
    yesterday = DAY - timedelta(days=1)
    reg = {"alpha": _tech("Alpha", {yesterday: 1, DAY: 3})}
    out = update_registry(reg, _digest(DAY, {}))
    assert out["alpha"].counts == {yesterday.isoformat(): 1}
    assert out["alpha"].last_seen == yesterday


def test_first_seen_recomputed_when_first_day_rerun_drops_tech() -> None:
    reg = {"alpha": _tech("Alpha", {DAY: 1, DAY + timedelta(days=1): 1})}
    out = update_registry(reg, _digest(DAY, {}))
    assert out["alpha"].first_seen == DAY + timedelta(days=1)


def test_input_registry_not_mutated() -> None:
    reg = {"alpha": _tech("Alpha", {DAY - timedelta(days=1): 1})}
    before = {k: v.model_copy(deep=True) for k, v in reg.items()}
    update_registry(reg, _digest(DAY, {"a": ["Alpha", "Beta"]}))
    assert reg == before


def _trend_registry(today: int, past: dict[int, int]) -> dict[str, Technology]:
    counts = {DAY - timedelta(days=n): c for n, c in past.items()}
    counts[DAY] = today
    return {"alpha": _tech("Alpha", counts)}


@pytest.mark.parametrize(
    ("today", "past", "trending"),
    [
        (4, {1: 7, 2: 7}, True),  # avg 2.0 -> needs >= 4
        (3, {1: 7, 2: 7}, False),
        (2, {1: 1}, True),  # avg 1/7
        (1, {8: 1}, False),  # below the minimum count
        (2, {1: 7, 2: 7}, False),
        (4, {8: 100}, True),  # outside the 7-day window
    ],
)
def test_trending_threshold(today: int, past: dict[int, int], trending: bool) -> None:
    out = annotate_digest(_digest(DAY, {}), _trend_registry(today, past), CFG)
    assert bool(out.trending_tech) is trending
    assert out.new_tech == []


def test_new_tech_is_not_trending() -> None:
    out = annotate_digest(_digest(DAY, {}), {"alpha": _tech("Alpha", {DAY: 9})}, CFG)
    assert [t.slug for t in out.new_tech] == ["alpha"]
    assert out.trending_tech == []


def test_annotate_sort_and_caps_and_no_mutation() -> None:
    reg = {slugify(n): _tech(n, {DAY: c}) for n, c in [("b", 1), ("a", 1), ("c", 3), ("d", 2)]}
    digest = _digest(DAY, {})
    out = annotate_digest(digest, reg, RegistryConfig(max_new=3))
    assert [(t.name, t.count_today) for t in out.new_tech] == [("c", 3), ("d", 2), ("a", 1)]
    assert digest.new_tech == []

    old = DAY - timedelta(days=30)
    reg = {f"t{i}": _tech(f"t{i}", {old: 1, DAY: 5 + i}) for i in range(4)}
    out = annotate_digest(digest, reg, RegistryConfig(max_trending=2))
    assert [t.name for t in out.trending_tech] == ["t3", "t2"]


def test_known_names_order() -> None:
    reg = {
        "b": _tech("B", {DAY: 2}),
        "a": _tech("A", {DAY: 1, DAY - timedelta(days=1): 1}),
        "c": _tech("C", {DAY: 5}),
    }
    assert known_names(reg) == ["C", "A", "B"]
    assert known_names({}) == []


def test_load_missing_and_corrupt(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    assert load_registry(tmp_path / "none.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_registry(bad) == {}
    bad.write_text(json.dumps({"x": {"name": "X"}}), encoding="utf-8")
    assert load_registry(bad) == {}
    bad.write_text("[]", encoding="utf-8")
    assert load_registry(bad) == {}
    assert "empty registry" in caplog.text


def test_save_load_round_trip_sorted(tmp_path: Path) -> None:
    reg = {
        "zeta": _tech("Zeta", {DAY: 1}),
        "alpha": _tech("Alpha", {DAY: 2, DAY - timedelta(days=3): 1}),
    }
    path = tmp_path / "sub" / "tech_registry.json"
    save_registry(path, reg)
    assert load_registry(path) == reg
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert list(raw) == ["alpha", "zeta"]
    assert list(raw["alpha"]["counts"]) == ["2026-11-10", "2026-11-13"]


def test_rerun_drops_todays_items_but_keeps_other_days() -> None:
    reg = update_registry({}, _digest(DAY - timedelta(days=1), {"x": ["Alpha"]}))
    reg = update_registry(reg, _digest(DAY, {"y": ["Alpha"]}))
    reg = update_registry(reg, _digest(DAY, {"z": ["Beta"]}))
    assert reg["alpha"].items == {"2026-11-12": ["x"]}
    assert reg["alpha"].counts == {"2026-11-12": 1}


def test_load_registry_unreadable_path_is_empty(tmp_path: Path) -> None:
    assert load_registry(tmp_path) == {}  # a directory: OSError is logged, not raised
