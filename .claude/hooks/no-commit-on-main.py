"""PreToolUse hook (Bash): no commits or pushes to main.

Work happens on a task branch, goes up as a pull request, and the user merges it. The command is
split into shell segments and each `git` invocation is parsed (global options such as `-C dir`,
`-c k=v`, `--git-dir=...` are skipped), so it catches:
  - `git commit` / `git push` while the repo's branch is main,
  - `git switch main && git commit ...` (a switch to main earlier in the same command),
  - pushes that target main from any branch: `main`, `+main`, `HEAD:main`, `refs/heads/main`,
    `--all`, `--mirror`.
Exit 2 blocks the call and shows Claude the reason. It parses text, so it stops mistakes, not
deliberate workarounds (aliases, scripts, `cd` into another repo); see .claude/WORKFLOW.md.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys

PROTECTED = "main"
SEPARATORS = {";", "&&", "||", "|", "&", "\n", "(", ")"}
# Global git options that take a separate value (`-C dir`, `-c key=value`, `--git-dir dir`).
OPTS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}


def segments(command: str) -> list[list[str]]:
    """Split a shell command into simple-command token lists at ; && || | & and newlines."""
    lexer = shlex.shlex(command.replace("\n", " ; "), posix=True, punctuation_chars=";&|()")
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:  # unbalanced quotes: fall back to a plain split
        tokens = command.split()
    out: list[list[str]] = [[]]
    for tok in tokens:
        if tok in SEPARATORS or set(tok) <= set(";&|()"):
            out.append([])
        else:
            out[-1].append(tok)
    return [s for s in out if s]


def parse_git(tokens: list[str]) -> tuple[str | None, str | None, list[str]]:
    """Return (repo dir from -C, subcommand, args) for a `git ...` segment.

    Segments without `git` give (None, None, []).
    """
    try:
        i = next(n for n, t in enumerate(tokens) if os.path.basename(t) == "git")
    except StopIteration:
        return None, None, []
    repo: str | None = None
    i += 1
    while i < len(tokens) and tokens[i].startswith("-"):
        opt = tokens[i]
        if opt in OPTS_WITH_VALUE and i + 1 < len(tokens):
            if opt == "-C":
                repo = os.path.join(repo or "", tokens[i + 1])
            i += 2
        else:
            i += 1
    if i >= len(tokens):
        return repo, None, []
    return repo, tokens[i], tokens[i + 1 :]


def current_branch(project: str, repo: str | None) -> str:
    """Branch checked out in `repo` (relative to the project dir); "" if unknown or detached."""
    path = os.path.join(project, repo) if repo else project
    try:
        res = subprocess.run(
            ["git", "-C", path, "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return res.stdout.strip()


def targets_main(args: list[str]) -> bool:
    """True if `git push` args update main: a refspec ending in main, or --all / --mirror."""
    for arg in args:
        if arg in ("--all", "--mirror"):
            return True
        if arg.startswith("-"):
            continue
        dest = arg.lstrip("+").rsplit(":", 1)[-1]
        if dest in (PROTECTED, f"refs/heads/{PROTECTED}"):
            return True
    return False


def switches_to_main(sub: str | None, args: list[str]) -> bool:
    """True for `git switch main`, `git checkout main` and `-B/-C main` variants."""
    return sub in ("switch", "checkout") and PROTECTED in args


def reason(command: str, project: str) -> str | None:
    """Why the command must be blocked, or None to let it through."""
    on_main_after_switch = False
    for seg in segments(command):
        repo, sub, args = parse_git(seg)
        if sub is None:
            continue
        if switches_to_main(sub, args):
            on_main_after_switch = True
            continue
        if sub not in ("commit", "push"):
            continue
        branch = PROTECTED if on_main_after_switch else current_branch(project, repo)
        if branch == PROTECTED:
            return (
                f"you are on {PROTECTED}. Create a task branch first "
                "(git switch -c <type>/<short-name>), commit there, push it and open a PR"
            )
        if sub == "push" and targets_main(args):
            return f"this push updates {PROTECTED}. Push the task branch and open a PR instead"
    return None


def main() -> int:
    """Read the hook payload from stdin; exit 2 (block) with a reason, else 0."""
    try:
        payload = json.load(sys.stdin)
        command = payload.get("tool_input", {}).get("command") or ""
    except (ValueError, AttributeError):
        print("Blocked: no-commit-on-main hook could not read its input.", file=sys.stderr)
        return 2
    why = reason(command, os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    if why:
        print(f"Blocked: {why}; the user merges it.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
