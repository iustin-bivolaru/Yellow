from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from yellow.config import Config, load_config


def _base(repo_root: Path) -> dict:
    return yaml.safe_load((repo_root / "config.yaml").read_text())


def test_loads_real_config(repo_root: Path) -> None:
    cfg = load_config(repo_root / "config.yaml")
    assert cfg.timezone == "Europe/Bucharest"
    assert cfg.llm.model == "claude-haiku-5-5"
    assert "AI Research" in cfg.categories
    assert cfg.source_enabled("hackernews")
    assert not cfg.source_enabled("x")


def test_default_path_uses_yellow_root(
    repo_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("YELLOW_ROOT", str(repo_root))
    monkeypatch.chdir(tmp_path)  # no config.yaml here, so only YELLOW_ROOT can find it
    assert load_config().timezone == "Europe/Bucharest"


@pytest.mark.parametrize("model", ["claude-opus-5-5", "Claude-OPUS-4"])
def test_opus_rejected(repo_root: Path, model: str) -> None:
    data = _base(repo_root)
    data["llm"]["model"] = model
    with pytest.raises(ValidationError):
        Config.model_validate(data)


def test_unknown_timezone_is_validation_error(repo_root: Path) -> None:
    data = _base(repo_root)
    data["timezone"] = "Europe/Bucharset"
    with pytest.raises(ValidationError):
        Config.model_validate(data)


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        (None, "run_hour", 25),
        ("llm", "max_items", 0),
        ("llm", "max_tokens", -1),
        ("llm", "effort", "lwo"),
        ("caps", "lookback_hours", 0),
    ],
)
def test_bounds(repo_root: Path, section: str | None, key: str, value: object) -> None:
    data = _base(repo_root)
    (data[section] if section else data)[key] = value
    with pytest.raises(ValidationError):
        Config.model_validate(data)


@pytest.mark.parametrize(
    "path",
    [
        ("run_hours",),
        ("llm", "max_item"),
        ("caps", "lookback_hour"),
        ("site", "titel"),
        ("sources", "hackernews", "enabeld"),
        ("sources", "hackernwes"),
    ],
)
def test_unknown_keys_rejected(repo_root: Path, path: tuple[str, ...]) -> None:
    data = _base(repo_root)
    node = data
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = {"enabled": True} if path[-1] == "hackernwes" else 1
    with pytest.raises(ValidationError):
        Config.model_validate(data)


def test_enabled_must_be_a_real_bool(repo_root: Path) -> None:
    data = _base(repo_root)
    data["sources"]["reddit"]["enabled"] = "false"
    with pytest.raises(ValidationError):
        Config.model_validate(data)


def test_x_requires_token(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = _base(repo_root)
    data["sources"]["x"]["enabled"] = True
    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)
    with pytest.raises(ValidationError):
        Config.model_validate(data)
    monkeypatch.setenv("X_BEARER_TOKEN", "test-token")
    assert Config.model_validate(data).source_enabled("x")


@pytest.mark.parametrize(
    "categories", [[], ["AI Research"], ["Other Tech", "AI Research", "Other Tech"]]
)
def test_categories_validated(repo_root: Path, categories: list[str]) -> None:
    data = _base(repo_root)
    data["categories"] = categories
    with pytest.raises(ValidationError):
        Config.model_validate(data)
