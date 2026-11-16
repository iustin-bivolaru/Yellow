import json
import subprocess
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
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


@pytest.fixture
def cfg(cfg: Config) -> Config:
    """Config using the SDK ("api") backend, which the FakeClient tests below exercise."""
    cfg = cfg.model_copy(deep=True)
    cfg.llm.backend = "api"
    return cfg


@pytest.fixture
def cli_cfg(cfg: Config) -> Config:
    """Config using the default Claude Code CLI backend."""
    cfg = cfg.model_copy(deep=True)
    cfg.llm.backend = "claude-code"
    return cfg


class FakeRunner:
    """Stands in for subprocess.run: records calls, returns a canned process or raises."""

    def __init__(
        self,
        stdout: str = "",
        returncode: int = 0,
        error: Exception | None = None,
    ) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []
        self._out, self._rc, self._error = stdout, returncode, error

    def __call__(self, cmd: list[str], **kwargs: Any) -> Any:
        self.calls.append((cmd, kwargs))
        if self._error:
            raise self._error
        return SimpleNamespace(stdout=self._out, stderr="", returncode=self._rc)


def _envelope(out: LLMOutput | str | None, **over: Any) -> str:
    """A Claude Code JSON envelope; `out` goes into `result` as JSON text (str is used as is)."""
    result = out if isinstance(out, str) else (out.model_dump_json() if out else "")
    env: dict[str, Any] = {
        "type": "result", "subtype": "success", "is_error": False, "result": result,
        "total_cost_usd": 0.0123, "usage": {"input_tokens": 25000, "output_tokens": 8000},
    }  # fmt: skip
    return json.dumps(env | over)


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


# --- Claude Code CLI backend ---------------------------------------------------------------


def test_cli_success(cli_cfg: Config, repo_root: Path) -> None:
    items = [_item(i, score=i) for i in range(4)]
    runner = FakeRunner(_envelope(_llm_output(items)))
    d = analyze(items, cli_cfg, day=DAY, now=NOW, known_tech=["Llama 4"], runner=runner)
    [(cmd, kw)] = runner.calls  # exactly one subprocess call
    assert cmd[0] == "claude" and "--print" in cmd
    assert cmd[cmd.index("--model") + 1] == "claude-haiku-5-5"
    assert cmd[cmd.index("--tools") + 1] == ""  # no built-in tools
    assert "--strict-mcp-config" in cmd and "--mcp-config" not in cmd
    assert cmd[cmd.index("--output-format") + 1] == "json"
    assert json.loads(cmd[cmd.index("--json-schema") + 1])["properties"]["nutshell"]
    assert "Llama 4" in kw["input"] and kw["input"] not in cmd  # prompt on stdin, not argv
    assert "Story 0" not in " ".join(cmd)
    assert kw["timeout"] == 600
    assert Path(kw["cwd"]).resolve() != repo_root
    assert repo_root not in Path(kw["cwd"]).resolve().parents
    assert d.analyzer == "claude-haiku-5-5" and d.nutshell == "One. Two. Three."
    assert d.items[0].technologies == ["Llama 4", "PyTorch"]


def test_cli_structured_output_field_and_fenced_text(cli_cfg: Config) -> None:
    items = [_item(1)]
    out = _llm_output(items)
    structured = _envelope("", structured_output=out.model_dump(mode="json"))
    d = analyze(items, cli_cfg, day=DAY, now=NOW, runner=FakeRunner(structured))
    assert d.analyzer == "claude-haiku-5-5"
    fenced = _envelope(f"```json\n{out.model_dump_json()}\n```")
    d = analyze(items, cli_cfg, day=DAY, now=NOW, runner=FakeRunner(fenced))
    assert d.analyzer == "claude-haiku-5-5"


def test_cli_logs_usage(cli_cfg: Config, caplog: pytest.LogCaptureFixture) -> None:
    items = [_item(1)]
    caplog.set_level("INFO")
    analyze(items, cli_cfg, day=DAY, now=NOW, runner=FakeRunner(_envelope(_llm_output(items))))
    assert "25000 input + 8000 output" in caplog.text and "0.0123" in caplog.text


@pytest.mark.parametrize(
    "runner",
    [
        FakeRunner(_envelope("Not logged in", is_error=True, subtype="error")),
        FakeRunner(_envelope("Not logged in"), returncode=1),
        FakeRunner(error=subprocess.TimeoutExpired("claude", 600)),
        FakeRunner(error=FileNotFoundError("claude")),
        FakeRunner("not json at all"),
        FakeRunner(_envelope("this is not json")),
        FakeRunner(_envelope('{"nutshell": "x"}')),  # schema-invalid
        FakeRunner(""),
    ],
    ids=[
        "is_error",
        "exit1",
        "timeout",
        "no-binary",
        "bad-envelope",
        "bad-result",
        "schema",
        "empty",
    ],
)
def test_cli_failures_fall_back(cli_cfg: Config, runner: FakeRunner) -> None:
    items = [_item(i) for i in range(3)]
    d = analyze(items, cli_cfg, day=DAY, now=NOW, runner=runner)
    assert d.analyzer == KEYWORD_ANALYZER and len(d.items) == 3
    assert len(runner.calls) == 1


def test_cli_not_called_without_llm_or_items(cli_cfg: Config) -> None:
    runner = FakeRunner(_envelope(None))
    analyze([_item(1)], cli_cfg, day=DAY, now=NOW, use_llm=False, runner=runner)
    analyze([], cli_cfg, day=DAY, now=NOW, runner=runner)
    assert runner.calls == []


def test_cli_backend_ignores_sdk_client(cli_cfg: Config) -> None:
    items = [_item(1)]
    client = FakeClient(_response(_llm_output(items)))
    runner = FakeRunner(_envelope(_llm_output(items)))
    analyze(items, cli_cfg, day=DAY, now=NOW, client=client, runner=runner)
    assert client.calls == [] and client.beta_calls == [] and len(runner.calls) == 1


def test_cli_env_drops_api_credentials_and_has_max_turns(
    cli_cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth")
    items = [_item(1)]
    runner = FakeRunner(_envelope(_llm_output(items)))
    analyze(items, cli_cfg, day=DAY, now=NOW, runner=runner)
    [(cmd, kw)] = runner.calls
    assert "ANTHROPIC_API_KEY" not in kw["env"] and "ANTHROPIC_AUTH_TOKEN" not in kw["env"]
    assert kw["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "oauth"
    assert cmd[cmd.index("--max-turns") + 1] == "3"


def test_cli_failure_logs_stderr_tail_and_ci_annotation(
    cli_cfg: Config,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Runner(FakeRunner):
        def __call__(self, cmd: list[str], **kwargs: Any) -> Any:
            proc = super().__call__(cmd, **kwargs)
            proc.stderr = "x" * 600 + "AUTH-FAILED"
            return proc

    items = [_item(1)]
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    for out in ("garbage", _envelope("nope", is_error=True)):
        caplog.clear()
        d = analyze(items, cli_cfg, day=DAY, now=NOW, runner=Runner(out))
        assert d.analyzer == KEYWORD_ANALYZER
        assert "AUTH-FAILED" in caplog.text and "x" * 600 not in caplog.text
    assert "::warning::Claude call failed" in capsys.readouterr().out
    monkeypatch.delenv("GITHUB_ACTIONS")
    analyze(items, cli_cfg, day=DAY, now=NOW, runner=Runner("garbage"))
    assert "::warning::" not in capsys.readouterr().out
