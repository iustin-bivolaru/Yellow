"""scripts/new-task.sh and scripts/ship.sh against temporary repos with a local bare origin."""

import os
import subprocess
from pathlib import Path

import pytest

from tests.conftest import REPO

NEW_TASK = REPO / "scripts" / "new-task.sh"
SHIP = REPO / "scripts" / "ship.sh"

ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "SHIP_TEST_MODE": "1",
    "SHIP_CHECK_CMD": "true",
}


def git(cwd: Path, *args: str) -> str:
    """Run git in cwd and return stripped stdout."""
    out = subprocess.run(
        ["git", *args], cwd=cwd, env=ENV, check=True, capture_output=True, text=True
    )
    return out.stdout.strip()


def run(script: Path, cwd: Path, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    """Run a script in cwd with the test git environment."""
    return subprocess.run(
        [str(script), *args], cwd=cwd, env={**ENV, **env}, capture_output=True, text=True
    )


def commit_file(repo: Path, name: str, content: str = "x") -> None:
    """Create a file and commit it."""
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", f"chore: add {name}")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A work clone on main whose origin is a local bare repo."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True, env=ENV)
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True, env=ENV)
    git(work, "remote", "add", "origin", str(origin))
    commit_file(work, "README.md")
    git(work, "push", "-q", "origin", "main")
    git(work, "fetch", "-q", "origin")
    return work


@pytest.mark.parametrize("name", ["foo", "feat/", "feat/Upper", "wip/x", "feat/a_b", "feat/-x"])
def test_new_task_rejects_bad_names(repo: Path, name: str) -> None:
    result = run(NEW_TASK, repo, name)
    assert result.returncode != 0
    assert git(repo, "branch", "--show-current") == "main"


def test_new_task_rejects_existing_branch(repo: Path) -> None:
    git(repo, "branch", "feat/x")
    assert run(NEW_TASK, repo, "feat/x").returncode == 1


def test_new_task_refuses_dirty_tree(repo: Path) -> None:
    (repo / "dirty.txt").write_text("x")
    result = run(NEW_TASK, repo, "feat/x")
    assert result.returncode == 1
    assert "dirty" in result.stderr


def test_new_task_protected_path_prints_command(repo: Path, tmp_path: Path) -> None:
    other = tmp_path / "other"
    subprocess.run(
        ["git", "clone", "-q", str(tmp_path / "origin.git"), str(other)], check=True, env=ENV
    )
    commit_file(other, ".claude/hooks/new.sh")
    git(other, "push", "-q", "origin", "main")
    git(repo, "fetch", "-q", "origin")
    result = run(NEW_TASK, repo, "feat/x")
    assert result.returncode == 3
    assert "git switch --no-track -c feat/x origin/main" in result.stdout
    assert git(repo, "branch", "--show-current") == "main"


def test_new_task_happy_path_and_housekeeping(repo: Path, tmp_path: Path) -> None:
    # merged branch (at main) and an unmerged one with its own commit
    git(repo, "branch", "feat/merged")
    git(repo, "switch", "-q", "-c", "feat/unmerged")
    commit_file(repo, "wip.txt")
    git(repo, "switch", "-q", "main")
    # origin/main moves ahead; local main is behind
    other = tmp_path / "other"
    subprocess.run(
        ["git", "clone", "-q", str(tmp_path / "origin.git"), str(other)], check=True, env=ENV
    )
    commit_file(other, "more.txt")
    git(other, "push", "-q", "origin", "main")
    git(repo, "fetch", "-q", "origin")

    result = run(NEW_TASK, repo, "feat/new")
    assert result.returncode == 0, result.stderr
    assert git(repo, "branch", "--show-current") == "feat/new"
    assert git(repo, "rev-parse", "HEAD") == git(repo, "rev-parse", "origin/main")
    assert git(repo, "rev-parse", "main") == git(repo, "rev-parse", "origin/main")
    assert (
        subprocess.run(
            ["git", "config", "--get", "branch.feat/new.remote"], cwd=repo, env=ENV
        ).returncode
        != 0
    )
    branches = git(repo, "branch", "--format=%(refname:short)").split()
    assert "feat/merged" not in branches
    assert "feat/unmerged" in branches
    assert "feat/new" in branches
    assert "deleted merged branch: feat/merged" in result.stdout


@pytest.fixture
def task(repo: Path) -> Path:
    """The work clone switched to a task branch."""
    assert run(NEW_TASK, repo, "feat/x").returncode == 0
    return repo


def test_ship_refuses_on_main(repo: Path) -> None:
    (repo / "a.txt").write_text("x")
    result = run(SHIP, repo, "feat: add a")
    assert result.returncode == 1
    assert "main" in result.stderr


@pytest.mark.parametrize(
    "subject",
    [
        "add stuff",
        "feature: add a",
        "feat: Add a",
        "feat: add a.",
        "feat(Scope): add a",
        "feat: " + "x" * 70,
    ],
)
def test_ship_rejects_bad_subjects(task: Path, subject: str) -> None:
    (task / "a.txt").write_text("x")
    result = run(SHIP, task, subject)
    assert result.returncode == 2
    assert git(task, "rev-list", "--count", "origin/main..HEAD") == "0"


@pytest.mark.parametrize(
    ("subject", "body"),
    [
        ("feat: add a", "Generated with Claude Code"),
        ("feat: add a", "Co-Authored-By: Claude <noreply@anthropic.com>"),
        ("feat: add a", "Co-Authored-By: someone"),
        ("feat: add a", "Generated with a tool"),
    ],
)
def test_ship_rejects_attribution(task: Path, subject: str, body: str) -> None:
    (task / "a.txt").write_text("x")
    result = run(SHIP, task, subject, body)
    assert result.returncode == 2
    assert git(task, "rev-list", "--count", "origin/main..HEAD") == "0"


def test_ship_refuses_staged_secret_file(task: Path) -> None:
    (task / ".env").write_text("KEY=1")
    result = run(SHIP, task, "feat: add a")
    assert result.returncode == 1
    assert "secret" in result.stderr
    assert git(task, "rev-list", "--count", "origin/main..HEAD") == "0"
    assert git(task, "diff", "--cached", "--name-only") == ""


def test_ship_allows_example_env_file(task: Path) -> None:
    (task / ".env.example").write_text("KEY=")
    assert run(SHIP, task, "chore: add example").returncode == 0


def test_ship_failing_checks_stop_before_commit(task: Path) -> None:
    (task / "a.txt").write_text("x")
    result = run(SHIP, task, "feat: add a", SHIP_CHECK_CMD="false")
    assert result.returncode == 1
    assert git(task, "rev-list", "--count", "origin/main..HEAD") == "0"


def test_ship_nothing_to_ship(task: Path) -> None:
    result = run(SHIP, task, "feat: add a")
    assert result.returncode == 1
    assert "nothing to ship" in result.stderr


def test_ship_happy_path_commits_and_prints_commands(task: Path) -> None:
    (task / "a.txt").write_text("x")
    result = run(SHIP, task, "feat(core): add a", "Why it matters.")
    assert result.returncode == 0, result.stderr
    assert git(task, "log", "-1", "--format=%s") == "feat(core): add a"
    assert git(task, "log", "-1", "--format=%b") == "Why it matters."
    assert "git push origin feat/x" in result.stdout
    assert "gh pr create --base main --head feat/x --title" in result.stdout
    assert "'Why it matters.'" in result.stdout or "Why\\ it\\ matters." in result.stdout


def test_ship_pr_body_defaults_to_subject(task: Path) -> None:
    (task / "a.txt").write_text("x")
    result = run(SHIP, task, "fix: tweak a")
    assert result.returncode == 0, result.stderr
    assert "--body fix:\\ tweak\\ a" in result.stdout


@pytest.mark.parametrize(
    "subject", ["docs(claude): update workflow", "feat(sources): add claude blog feed"]
)
def test_ship_allows_claude_word(task: Path, subject: str) -> None:
    (task / "a.txt").write_text("x")
    assert run(SHIP, task, subject).returncode == 0
    assert git(task, "log", "-1", "--format=%s") == subject


def test_ship_ignores_check_cmd_without_test_mode(task: Path) -> None:
    (task / "a.txt").write_text("x")
    result = run(SHIP, task, "feat: add a", SHIP_TEST_MODE="0", SHIP_CHECK_CMD="true")
    assert "ignored" in result.stderr
    assert "running checks: .venv/bin/ruff" in result.stdout


def test_ship_secret_unstages_only_offender(task: Path) -> None:
    (task / "a.txt").write_text("x")
    (task / ".env").write_text("KEY=1")
    assert run(SHIP, task, "feat: add a").returncode == 1
    assert git(task, "diff", "--cached", "--name-only") == "a.txt"


def test_new_task_keeps_local_only_main_commit(repo: Path) -> None:
    commit_file(repo, "local.txt")
    sha = git(repo, "rev-parse", "main")
    assert run(NEW_TASK, repo, "feat/x").returncode == 0
    assert git(repo, "rev-parse", "main") == sha
    assert run(NEW_TASK, repo, "--tidy").returncode == 0
    assert git(repo, "rev-parse", "main") == sha


def test_tidy_happy_path_with_dirty_tree(repo: Path, tmp_path: Path) -> None:
    git(repo, "branch", "feat/merged")
    git(repo, "switch", "-q", "-c", "feat/cur")
    other = tmp_path / "other"
    subprocess.run(
        ["git", "clone", "-q", str(tmp_path / "origin.git"), str(other)], check=True, env=ENV
    )
    commit_file(other, "more.txt")
    git(other, "push", "-q", "origin", "main")
    git(repo, "fetch", "-q", "origin")
    (repo / "dirty.txt").write_text("x")
    result = run(NEW_TASK, repo, "--tidy")
    assert result.returncode == 0, result.stderr
    assert git(repo, "rev-parse", "main") == git(repo, "rev-parse", "origin/main")
    branches = git(repo, "branch", "--format=%(refname:short)").split()
    assert "feat/merged" not in branches
    assert "feat/cur" in branches


def test_tidy_survives_undeletable_branch(repo: Path, tmp_path: Path) -> None:
    git(repo, "branch", "feat/merged")
    git(repo, "worktree", "add", "-q", str(tmp_path / "wt"), "feat/merged")
    result = run(NEW_TASK, repo, "--tidy")
    assert result.returncode == 0, result.stderr
    assert "could not delete feat/merged" in result.stderr
