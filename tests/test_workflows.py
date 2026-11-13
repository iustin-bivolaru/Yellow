"""Static checks of .github/workflows/daily.yml (no network)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def wf() -> dict[str, Any]:
    """Parsed daily.yml."""
    return yaml.safe_load((ROOT / ".github/workflows/daily.yml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def conf() -> dict[str, Any]:
    """Parsed config.yaml."""
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def _triggers(wf: dict[str, Any]) -> dict[str, Any]:
    """Return the trigger map; PyYAML parses the key `on` as boolean True."""
    return wf.get("on", wf.get(True))


def _cron_hours(wf: dict[str, Any]) -> list[int]:
    """UTC hours of every cron entry (all are daily: `M H * * *`)."""
    hours = []
    for entry in _triggers(wf)["schedule"]:
        minute, hour, *rest = entry["cron"].split()
        assert minute == "0"
        assert rest == ["*", "*", "*"]
        hours.append(int(hour))
    return hours


def _local_hour(utc_hour: int, day: str, tz: str) -> int:
    """Local hour in `tz` for `utc_hour` UTC on the ISO date `day`."""
    y, m, d = map(int, day.split("-"))
    return datetime(y, m, d, utc_hour, tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo(tz)).hour


@pytest.mark.parametrize("day", ["2026-07-01", "2026-01-15"])
def test_a_cron_hits_run_hour_and_all_are_close(
    wf: dict[str, Any], conf: dict[str, Any], day: str
) -> None:
    run_hour, tz = conf["run_hour"], conf["timezone"]
    local = [_local_hour(h, day, tz) for h in _cron_hours(wf)]
    assert run_hour in local
    assert all(run_hour - 1 <= h <= run_hour + 3 for h in local)


def test_dispatch_inputs(wf: dict[str, Any]) -> None:
    inputs = _triggers(wf)["workflow_dispatch"]["inputs"]
    assert {"force", "no_llm"} <= set(inputs)


def test_top_level_permissions_read_only(wf: dict[str, Any]) -> None:
    assert wf["permissions"] == {"contents": "read"}


def test_deploy_gated_on_build_output(wf: dict[str, Any]) -> None:
    deploy = wf["jobs"]["deploy"]
    assert set(deploy["needs"]) == {"build", "persist"}
    assert "needs.build.outputs.deploy" in deploy["if"]
    assert deploy["permissions"] == {"pages": "write", "id-token": "write"}


def test_secrets_only_in_env(wf: dict[str, Any]) -> None:
    for job in wf["jobs"].values():
        for step in job["steps"]:
            assert "secrets." not in step.get("run", "")


def test_nothing_pushes_to_main() -> None:
    text = (ROOT / ".github/workflows/daily.yml").read_text(encoding="utf-8")
    for line in text.splitlines():
        if "git" in line and "push" in line and not line.lstrip().startswith("#"):
            assert "data" in line
            assert "main" not in line


def _steps_text(job: dict[str, Any]) -> str:
    """All step run/env/with content of a job, as one string."""
    return yaml.safe_dump(job["steps"])


def test_build_job_is_read_only_and_keeps_no_credentials(wf: dict[str, Any]) -> None:
    build = wf["jobs"]["build"]
    assert build["permissions"] == {"contents": "read"}
    checkout = build["steps"][0]
    assert checkout["uses"].startswith("actions/checkout@")
    assert checkout["with"]["persist-credentials"] is False
    text = _steps_text(build)
    assert "GITHUB_TOKEN" not in text
    assert text.count("secrets.") == 1
    assert "secrets.ANTHROPIC_API_KEY" in text


def test_only_persist_can_write_and_runs_no_project_code(wf: dict[str, Any]) -> None:
    writers = [
        n for n, j in wf["jobs"].items() if j.get("permissions", {}).get("contents") == "write"
    ]
    assert writers == ["persist"]
    persist = wf["jobs"]["persist"]
    text = _steps_text(persist)
    assert "pip" not in text
    assert "python" not in text
    assert "yellow" not in text.replace("data-state", "")


def test_persist_pushes_only_data_to_origin(wf: dict[str, Any]) -> None:
    pushes = [
        line.strip()
        for step in wf["jobs"]["persist"]["steps"]
        for line in step.get("run", "").splitlines()
        if "push" in line
    ]
    assert pushes == ["git -C data push origin data"]


def test_no_configure_pages(wf: dict[str, Any]) -> None:
    for job in wf["jobs"].values():
        for step in job["steps"]:
            assert "configure-pages" not in step.get("uses", "")


def test_ls_remote_distinguishes_missing_branch() -> None:
    text = (ROOT / ".github/workflows/daily.yml").read_text(encoding="utf-8")
    assert text.count("git ls-remote --exit-code") == text.count('"$rc" -eq 2') == 2
