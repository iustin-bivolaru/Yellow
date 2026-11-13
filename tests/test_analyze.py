from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from yellow.analyze import (
    KEYWORD_ANALYZER,
    LLMOutput,
    analyze,
    keyword_category,
    keyword_technologies,
    select_items,
)
from yellow.config import FALLBACK_CATEGORY, Config
from yellow.models import Item, ItemAnalysis, item_id

NOW = datetime(2026, 11, 13, 7, tzinfo=UTC)
DAY = date(2026, 11, 13)


def _item(
    n: int, source: str = "hackernews", score: int | None = None, title: str = "", **kw: Any
) -> Item:
    url = f"https://example.com/{source}/{n}"
    return Item(
        id=item_id(url),
        title=title or f"Story {n} from {source}",
        url=url,
        source=source,
        source_name=kw.pop("source_name", source),
        published=NOW - timedelta(minutes=n),
        score=score,
        **kw,
    )


class FakeClient:
    """Stands in for anthropic.Anthropic: records calls, returns a canned response."""

    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.beta_calls: list[dict[str, Any]] = []
        self._response, self._error = response, error
        self.messages = SimpleNamespace(stream=self._stream(self.calls))
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream(self.beta_calls)))

    def _stream(self, log: list[dict[str, Any]]):
        def stream(**kwargs: Any) -> Any:
            log.append(kwargs)
            if self._error:
                raise self._error
            return _FakeStream(self._response)

        return stream


class _FakeStream:
    """Context manager like anthropic's MessageStreamManager."""

    def __init__(self, response: Any) -> None:
        self._response = response

    def __enter__(self) -> "_FakeStream":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def get_final_message(self) -> Any:
        return self._response


def _response(parsed: LLMOutput | None, stop: str = "end_turn") -> SimpleNamespace:
    usage = SimpleNamespace(input_tokens=25_000, output_tokens=8_000)
    return SimpleNamespace(
        stop_reason=stop, parsed_output=parsed, usage=usage, model="claude-haiku-5-5",
        stop_details=SimpleNamespace(category="cyber") if stop == "refusal" else None,
    )  # fmt: skip


def _llm_output(items: list[Item], **over: Any) -> LLMOutput:
    analyses = [
        ItemAnalysis(
            id=it.id,
            category="AI Research",
            summary=f"Summary of {it.title}.",
            importance=3,
            technologies=["llama 4", " PyTorch ", "pytorch"],
        )
        for it in items
    ]
    data: dict[str, Any] = {
        "nutshell": "One. Two. Three.",
        "top5": [items[0].id],
        "items": analyses,
    }
    return LLMOutput(**(data | over))


# --- selection -----------------------------------------------------------------------------


def test_select_items_round_robin_and_best_first() -> None:
    hn = [_item(i, "hackernews", score=i) for i in range(10)]
    rss = [_item(i, "rss") for i in range(2)]
    picked = select_items(hn + rss, limit=6)
    assert len(picked) == 6
    assert sum(1 for p in picked if p.source == "rss") == 2  # small source not crowded out
    hn_scores = [p.score for p in picked if p.source == "hackernews"]
    assert hn_scores == [9, 8, 7, 6]


def test_select_items_under_limit_keeps_all() -> None:
    items = [_item(i) for i in range(3)]
    assert {i.id for i in select_items(items, 150)} == {i.id for i in items}


# --- keyword fallback ----------------------------------------------------------------------


def test_keyword_category_rules(cfg: Config) -> None:
    cats = cfg.categories
    assert (
        keyword_category(_item(1, title="Critical CVE-2026-1234 exploit in OpenSSH"), cats)
        == "Security"
    )
    assert (
        keyword_category(_item(2, title="Startup raises $50M Series B"), cats)
        == "Industry & Funding"
    )
    assert keyword_category(_item(3, source_name="arXiv"), cats) == "AI Research"
    assert keyword_category(_item(4, title="Nothing to see"), cats) == FALLBACK_CATEGORY


def test_keyword_technologies_whole_words() -> None:
    it = _item(1, title="Running Llama on llama.cpp with CUDA", snippet="not pythonic")
    found = keyword_technologies(it, ["Llama", "llama.cpp", "CUDA", "Python"])
    assert found == ["Llama", "llama.cpp", "CUDA"]


def test_no_llm_digest(cfg: Config) -> None:
    items = [_item(i, score=100 - i, title=f"New Claude model release {i}") for i in range(8)]
    client = FakeClient()
    d = analyze(items, cfg, day=DAY, now=NOW, use_llm=False, client=client)
    assert client.calls == [] and client.beta_calls == []
    assert d.analyzer == KEYWORD_ANALYZER
    assert len(d.items) == 8 and len(d.top5) == 5
    assert all(i.category in cfg.categories for i in d.items)
    assert "Claude" in d.items[0].technologies
    assert d.items[0].importance >= d.items[-1].importance


# --- Claude path ---------------------------------------------------------------------------


def test_claude_success_merges_and_normalizes(cfg: Config) -> None:
    items = [_item(i, score=i) for i in range(7)]
    client = FakeClient(_response(_llm_output(items)))
    d = analyze(items, cfg, day=DAY, now=NOW, known_tech=["Llama 4"], client=client)
    [call] = client.calls
    assert call["model"] == "claude-haiku-5-5" and call["output_format"] is LLMOutput
    assert call["output_config"] == {"effort": "low"} and call["max_tokens"] == 32000
    assert "Llama 4" in call["messages"][0]["content"]
    assert d.analyzer == "claude-haiku-5-5"
    assert d.nutshell == "One. Two. Three."
    assert d.top5[0] == items[0].id and len(d.top5) == 5  # filled up from importance
    assert d.items[0].technologies == ["Llama 4", "PyTorch"]  # registry spelling, deduped
    assert d.items[0].summary and d.items[0].summary.startswith("Summary of")


def test_unknown_category_becomes_fallback_and_missing_items_use_keywords(cfg: Config) -> None:
    items = [_item(1, title="Ransomware hits hospital"), _item(2)]
    out = _llm_output(items[1:])
    out.items[0].category = "Made Up Category"
    out.top5 = ["not-an-id", items[1].id, items[1].id]
    d = analyze(items, cfg, day=DAY, now=NOW, client=FakeClient(_response(out)))
    by_id = {i.id: i for i in d.items}
    assert by_id[items[1].id].category == FALLBACK_CATEGORY
    assert by_id[items[0].id].category == "Security"  # Claude skipped it: keyword fallback
    assert d.top5 == [items[1].id, items[0].id]


@pytest.mark.parametrize("stop", ["refusal", "max_tokens"])
def test_bad_stop_reason_falls_back(cfg: Config, stop: str) -> None:
    items = [_item(i) for i in range(3)]
    d = analyze(
        items, cfg, day=DAY, now=NOW, client=FakeClient(_response(_llm_output(items), stop))
    )
    assert d.analyzer == KEYWORD_ANALYZER and len(d.items) == 3


def test_api_error_falls_back(cfg: Config) -> None:
    items = [_item(i) for i in range(3)]
    d = analyze(items, cfg, day=DAY, now=NOW, client=FakeClient(error=RuntimeError("boom")))
    assert d.analyzer == KEYWORD_ANALYZER


def test_sonnet_uses_server_side_fallback(cfg: Config) -> None:
    cfg = cfg.model_copy(deep=True)
    cfg.llm.model = "claude-sonnet-5-5"
    items = [_item(1)]
    client = FakeClient(_response(_llm_output(items)))
    analyze(items, cfg, day=DAY, now=NOW, client=client)
    assert client.calls == []
    [call] = client.beta_calls
    assert call["fallbacks"] == "default" and call["betas"] == ["server-side-fallback-2026-07-01"]


def test_empty_input_makes_no_call(cfg: Config) -> None:
    client = FakeClient()
    d = analyze([], cfg, day=DAY, now=NOW, client=client)
    assert client.calls == [] and d.items == [] and d.top5 == []


def test_one_call_logs_cost(cfg: Config, caplog: pytest.LogCaptureFixture) -> None:
    items = [_item(1)]
    caplog.set_level("INFO")
    analyze(items, cfg, day=DAY, now=NOW, client=FakeClient(_response(_llm_output(items))))
    assert "est. cost $0.0065" in caplog.text


def test_other_models_do_not_get_fallback_beta(cfg: Config) -> None:
    cfg = cfg.model_copy(deep=True)
    cfg.llm.model = "claude-sonnet-5-5-preview"  # not an exact match: plain endpoint
    items = [_item(1)]
    client = FakeClient(_response(_llm_output(items)))
    analyze(items, cfg, day=DAY, now=NOW, client=client)
    assert client.beta_calls == [] and len(client.calls) == 1
