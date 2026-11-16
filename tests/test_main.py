import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.test_analyze import FakeClient, _response
from yellow import main as main_mod
from yellow.analyze import LLMOutput
from yellow.config import Config
from yellow.main import main, run
from yellow.models import Item, Technology, item_id
from yellow.tech_registry import save_registry

NOW = datetime(2026, 11, 13, 7, tzinfo=UTC)  # 09:00 in Europe/Bucharest (UTC+2)


class FakeSource:
    name = "fake"

    def __init__(self, items: list[Item]) -> None:
        self.items = items

    def fetch(self, since: datetime) -> list[Item]:
        return self.items


def _items(n: int = 3) -> list[Item]:
    out = []
    for i in range(n):
        url = f"https://example.com/story/{i}"
        out.append(
            Item(
                id=item_id(url),
                title=f"OpenAI releases GPT model {i}",
                url=url,
                source="hackernews",
                source_name="Hacker News",
                published=NOW - timedelta(minutes=i + 1),
                score=100 + i,
            )
        )
    return out


def _llm_out(items: list[Item], cfg: Config) -> LLMOutput:
    return LLMOutput(
        nutshell="Three sentences.",
        top5=[items[0].id],
        items=[
            {
                "id": i.id,
                "category": cfg.categories[0],
                "summary": "A summary.",
                "importance": 3,
                "technologies": ["GPT"],
            }
            for i in items
        ],
    )


def _run(tmp_path: Path, cfg: Config, items: list[Item] | None = None, **kw: Any) -> int:
    kw.setdefault("use_llm", False)
    kw.setdefault("now", NOW)
    if "client" in kw:  # fake Anthropic client: use the SDK backend
        cfg = cfg.model_copy(deep=True)
        cfg.llm.backend = "api"
    return run(
        data_dir=tmp_path / "data",
        site_dir=tmp_path / "site",
        cfg=cfg,
        sources=[FakeSource(_items() if items is None else items)],
        **kw,
    )


def test_full_run_writes_everything(tmp_path: Path, cfg: Config) -> None:
    assert _run(tmp_path, cfg) == 0
    data = tmp_path / "data"
    assert (data / "digests" / "2026-11-13.json").is_file()
    assert (data / "tech_registry.json").is_file()
    assert (data / "seen.json").is_file()
    assert (tmp_path / "site" / "index.html").is_file()


def test_dry_run_writes_site_only(tmp_path: Path, cfg: Config) -> None:
    assert _run(tmp_path, cfg, dry_run=True) == 0
    assert not (tmp_path / "data").exists()
    assert (tmp_path / "site" / "index.html").is_file()


def test_same_day_rerun_is_stable(tmp_path: Path, cfg: Config) -> None:
    _run(tmp_path, cfg)
    data = tmp_path / "data"
    first = json.loads((data / "digests" / "2026-11-13.json").read_text())
    reg = (data / "tech_registry.json").read_text()
    assert _run(tmp_path, cfg, now=NOW + timedelta(minutes=30)) == 0
    second = json.loads((data / "digests" / "2026-11-13.json").read_text())
    assert [i["id"] for i in second["items"]] == [i["id"] for i in first["items"]]
    assert len(second["items"]) == 3
    assert second["analyzer"] == first["analyzer"]
    assert (data / "tech_registry.json").read_text() == reg


def test_empty_collection_keeps_existing_digest(tmp_path: Path, cfg: Config) -> None:
    _run(tmp_path, cfg)
    path = tmp_path / "data" / "digests" / "2026-11-13.json"
    before = path.read_text()
    (tmp_path / "site" / "index.html").unlink()
    assert _run(tmp_path, cfg, items=[]) == 0
    assert path.read_text() == before
    assert (tmp_path / "site" / "index.html").is_file()


def test_empty_collection_without_digest_saves_nothing(tmp_path: Path, cfg: Config) -> None:
    assert _run(tmp_path, cfg, items=[]) == 0
    assert not (tmp_path / "data").exists()
    assert (tmp_path / "site" / "index.html").is_file()  # empty page


def test_corrupt_today_digest_is_treated_as_missing(tmp_path: Path, cfg: Config) -> None:
    path = tmp_path / "data" / "digests" / "2026-11-13.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    assert _run(tmp_path, cfg) == 0
    assert json.loads(path.read_text())["items"]


def test_keyword_fallback_does_not_replace_llm_digest(tmp_path: Path, cfg: Config) -> None:
    items = _items(2)
    client = FakeClient(_response(_llm_out(items, cfg)))
    _run(tmp_path, cfg, items=items, use_llm=True, client=client)
    path = tmp_path / "data" / "digests" / "2026-11-13.json"
    before = path.read_text()
    registry = (tmp_path / "data" / "tech_registry.json").read_text()
    failing = FakeClient(error=RuntimeError("api down"))
    assert _run(tmp_path, cfg, items=_items(3), use_llm=True, client=failing) == 0
    assert path.read_text() == before
    assert (tmp_path / "data" / "tech_registry.json").read_text() == registry


@pytest.mark.parametrize(
    ("now", "runs"),
    [
        (datetime(2026, 7, 10, 6, tzinfo=UTC), True),  # summer UTC+3: 09:00
        (datetime(2026, 7, 10, 5, tzinfo=UTC), False),  # 08:00
        (datetime(2026, 11, 13, 7, tzinfo=UTC), True),  # winter UTC+2: 09:00
        (datetime(2026, 11, 13, 6, tzinfo=UTC), False),  # 08:00
        (datetime(2026, 11, 13, 8, 30, tzinfo=UTC), True),  # 10:30 local, late cron retry
    ],
)
def test_scheduled_gate_dst(tmp_path: Path, cfg: Config, now: datetime, runs: bool) -> None:
    assert _run(tmp_path, cfg, scheduled=True, now=now) == 0
    assert (tmp_path / "data").exists() is runs


def test_local_date_differs_from_utc_date(tmp_path: Path, cfg: Config) -> None:
    now = datetime(2026, 7, 10, 22, 30, tzinfo=UTC)  # 01:30 on the 11th in Bucharest
    assert _run(tmp_path, cfg, now=now) == 0
    assert (tmp_path / "data" / "digests" / "2026-07-11.json").is_file()


def test_http_client_is_closed(tmp_path: Path, cfg: Config, monkeypatch) -> None:
    closed: list[bool] = []

    class Http:
        def __enter__(self) -> "Http":
            return self

        def __exit__(self, *exc: object) -> None:
            closed.append(True)

    monkeypatch.setattr(main_mod, "make_client", lambda _cfg: Http())
    monkeypatch.setattr(main_mod, "enabled_sources", lambda *a, **k: [FakeSource(_items())])
    code = run(data_dir=tmp_path / "d", site_dir=tmp_path / "s", cfg=cfg, now=NOW, use_llm=False)
    assert code == 0
    assert closed == [True]


def test_known_tech_reaches_the_prompt(tmp_path: Path, cfg: Config) -> None:
    save_registry(
        tmp_path / "data" / "tech_registry.json",
        {
            "zetatech": Technology(
                name="ZetaTech", slug="zetatech", first_seen=date(2026, 11, 1),
                last_seen=date(2026, 11, 1), counts={"2026-11-01": 1}, items={"2026-11-01": []},
            )
        },
    )  # fmt: skip
    items = _items(1)
    client = FakeClient(_response(_llm_out(items, cfg)))
    _run(tmp_path, cfg, items=items, use_llm=True, client=client)
    call = (client.calls + client.beta_calls)[0]
    assert "ZetaTech" in str(call["system"]) + str(call["messages"])


def test_scheduled_gate(tmp_path: Path, cfg: Config) -> None:
    early = NOW - timedelta(hours=3)
    assert _run(tmp_path, cfg, scheduled=True, now=early) == 0
    assert not (tmp_path / "data").exists()  # skipped outside run_hour
    assert _run(tmp_path, cfg, scheduled=True) == 0
    path = tmp_path / "data" / "digests" / "2026-11-13.json"
    assert path.is_file()  # ran at run_hour
    before = path.read_text()
    assert _run(tmp_path, cfg, scheduled=True, items=_items(1)) == 0
    assert path.read_text() == before  # skipped: digest exists


def test_llm_path(tmp_path: Path, cfg: Config) -> None:
    items = _items(2)
    client = FakeClient(_response(_llm_out(items, cfg)))
    assert _run(tmp_path, cfg, items=items, use_llm=True, client=client) == 0
    assert len(client.calls) + len(client.beta_calls) == 1
    digest = (tmp_path / "data" / "digests" / "2026-11-13.json").read_text()
    assert cfg.llm.model in digest and "A summary." in digest


def test_render_failure_writes_no_state(
    tmp_path: Path, cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*a: Any, **k: Any) -> None:
        raise RuntimeError("render broke")

    monkeypatch.setattr(main_mod, "render_site", boom)
    monkeypatch.setattr(main_mod, "load_config", lambda *a, **k: cfg)
    monkeypatch.setattr(main_mod, "enabled_sources", lambda *a, **k: [FakeSource(_items())])
    code = main(
        ["run", "--no-llm", "--data-dir", str(tmp_path / "d"), "--site-dir", str(tmp_path / "s")]
    )
    assert code == 1
    assert not (tmp_path / "d").exists()


@pytest.mark.parametrize("argv", [[], ["bogus"], ["run", "--nope"]])
def test_usage_errors_exit_2(argv: list[str]) -> None:
    assert main(argv) == 2
