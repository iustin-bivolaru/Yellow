"""The no-commit-on-main hook: run the real script against real (temporary) git repos."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import REPO

HOOK = REPO / ".claude" / "hooks" / "no-commit-on-main.py"


def _repo(path: Path, branch: str) -> Path:
    subprocess.run(["git", "init", "-q", "-b", branch, str(path)], check=True)
    return path


def _run(project: Path, command: str) -> int:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    env = {"CLAUDE_PROJECT_DIR": str(project), "PATH": "/usr/bin:/bin:/opt/homebrew/bin"}
    return subprocess.run(
        [sys.executable, str(HOOK)], input=payload, text=True, capture_output=True, env=env
    ).returncode


@pytest.fixture
def feature(tmp_path: Path) -> Path:
    return _repo(tmp_path / "feat", "feat/x")


@pytest.fixture
def on_main(tmp_path: Path) -> Path:
    return _repo(tmp_path / "main", "main")


@pytest.mark.parametrize(
    "command",
    [
        "git commit -m x",
        "git push origin feat/x",
        "git -c user.name=a commit -m x",
        "git --no-pager push",
    ],
)
def test_blocks_commit_and_push_on_main(on_main: Path, command: str) -> None:
    assert _run(on_main, command) == 2


@pytest.mark.parametrize(
    "command",
    [
        "git switch main && git commit -m a",
        "git checkout main; git push",
        "git push origin main",
        "git push origin +main",
        "git push origin HEAD:main",
        "git push origin refs/heads/main",
        "git push origin 'main'",
        "git push origin HEAD:refs/heads/main",
        "git push --all origin",
        "git push --mirror origin",
        "git -C . -c x=y push origin main",
    ],
)
def test_blocks_reaching_main_from_a_feature_branch(feature: Path, command: str) -> None:
    assert _run(feature, command) == 2


@pytest.mark.parametrize(
    "command",
    [
        "git commit -m 'feat: x'",
        "git push origin feat/x",
        "git push origin feat/x && git log main",
        "git switch -c feat/y && git commit -m y",
        "git log --oneline main",
        "pytest -q",
        "git diff origin/main",
    ],
)
def test_allows_normal_work_on_a_feature_branch(feature: Path, command: str) -> None:
    assert _run(feature, command) == 0


def test_git_dash_c_uses_that_repos_branch(tmp_path: Path) -> None:
    project = _repo(tmp_path / "proj", "feat/x")
    _repo(project / "sub", "main")
    assert _run(project, "git -C sub commit -m x") == 2


def test_bad_input_fails_closed(feature: Path) -> None:
    res = subprocess.run(
        [sys.executable, str(HOOK)], input="not json", text=True, capture_output=True
    )
    assert res.returncode == 2
