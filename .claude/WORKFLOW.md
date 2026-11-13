# How we work on Yellow

This is the working agreement between the user and Claude Code for this repo. `CLAUDE.md` holds
the project rules; this file describes the process. The `ship` skill is the executable version.

## Roles

| Who | Model | Does | Never does |
|---|---|---|---|
| **User** | - | Decides scope and open questions, merges every PR on GitHub, owns sandbox/permission settings | - |
| **Main session** | Opus | Plans, asks the user, creates the branch, briefs the implementer, runs the checks, fixes small review findings, commits, pushes, opens the PR | Merges PRs, loosens the sandbox |
| **`implementer` agent** | Sonnet | Writes the code, tests and fixtures for one task from the brief; runs ruff + pytest; reports | Commits, pushes, switches branches, widens scope |
| **`code-reviewer` agent** | Opus | Reviews the uncommitted diff with no context of why it was written; reports findings | Edits files |
| **`ui-builder` agent** | Sonnet | Same role as the implementer, for the phone UI (templates, CSS, JS, PWA), following the `yellow-ui` skill | Commits |

## The flow for one task

1. **Agree on the task.** The main session reads `docs/PLAN.md` ("Status" says what's next) and
   settles open questions with the user first. Subagents can't ask the user anything.
2. **Branch.** `git switch main && git pull --ff-only && git switch -c <type>/<short-name>`,
   e.g. `feat/tech-registry`. Never work on `main`.
3. **Implement.** The main session writes a brief (goal, PLAN section, files, data contracts,
   edge cases, tests, out of scope) and spawns `implementer` (or `ui-builder` for UI work).
4. **Check.** The main session runs, itself:
   `.venv/bin/ruff format . && .venv/bin/ruff check . && .venv/bin/pytest -q`.
   A subagent saying "tests pass" is not enough.
5. **Review once.** `code-reviewer` (Opus) reviews the uncommitted changes.
   - blocker/major: fixed (small fixes by the main session, larger ones sent back to the
     same implementer).
   - minor: fixed if small, otherwise added to "Carried over from code review" in `docs/PLAN.md`.
   - A second review only if a blocker fix was substantial.
6. **Re-check**, then update `docs/PLAN.md` (tick the step, set "Next").
7. **Commit** on the branch with a Conventional Commits message, no Claude attribution:
   `feat(registry): track first-seen and trending technologies`
8. **Push + PR.** `git push origin <branch>`, then `gh pr create --base main --head <branch> ...`
   (as its own command).
9. **User merges** on GitHub. Then: `git switch main && git pull --ff-only`, delete the branch
   locally and on GitHub.

## Commit messages (Conventional Commits)

```
<type>(<scope>): <imperative summary, lowercase, no period, <= 72 chars>

<optional body: what and why>
```
Types: `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `chore`, `ci`, `build`.
Scopes: `sources`, `collect`, `analyze`, `registry`, `render`, `ui`, `cli`, `ci`, `claude`.

## Guardrails that run automatically

| What | Where | Effect |
|---|---|---|
| Ruff on every edit | PostToolUse hook `.claude/hooks/ruff-on-edit.sh` | Autofixes + formats each edited `.py` file; unfixable lint errors go back to the agent |
| No commits to main | PreToolUse hook `.claude/hooks/no-commit-on-main.sh` | Blocks `git commit`/`git push` on `main` and pushes to `main`. It matches command text, so it stops mistakes, not deliberate workarounds (`git -c ... commit`, aliases). There is no GitHub branch protection (the user's choice) |
| Docstrings | ruff `D` rules + `tests/test_docstrings.py` | Every module/class/function in `src/` needs one |
| Secret files | deny rules + Bash sandbox in `.claude/settings.json` | `.env` files can't be read by any tool or shell command (the tracked `.env.example` is the only exception for the sandbox, so git works) |
| Sandbox | `.claude/settings.json` `sandbox` | Every shell command runs in a macOS sandbox, network limited to the project's sources, PyPI, GitHub and the Anthropic API. `git push/fetch/pull` run outside it (they need the keychain) and still ask permission; so does `gh pr` after the one-time local setup below |
| Review of Claude config | `code-reviewer` agent | Reviews `.claude/hooks/*.sh` and `.claude/settings.json` like code; skips prose (skills, agent text, this file) |

## Cost rules (5-hour usage window)

- One implementer run and one review per task; follow-ups go to the same agent, not a new one.
- Deterministic checks (ruff, pytest, hooks) instead of agent runs wherever possible.
- The app itself makes exactly one Claude API call per daily run (see `CLAUDE.md`).

## Exceptions

- **The daily CI bot commits to `main`.** From build step 9, the GitHub Action commits `data/`
  (seen items, tech registry, digests) to `main` every morning. That's state, not code, and the
  only allowed direct commit. The hook doesn't apply to it (it only guards Claude Code).

## One-time local setup (not in git)

- `gh` needs the macOS keychain, which the sandbox blocks. Each machine runs once:
  `/sandbox exclude "gh pr *"` (saved in the gitignored `.claude/settings.local.json`).
  Without it, the main session prints the `gh pr create` command for the user to run with `!`.

## Quirks to know

- Run a `gh` command on its own; chained with anything else it runs sandboxed and fails on TLS.
- `git push -u` can't save the upstream (`.git/config` is sandbox-protected); push with
  `git push origin <branch>` and pass `--head <branch>` to `gh`.
- Commands that mention `.env` are blocked by a deny rule, so commit messages and commands avoid
  that text.
- Start Claude Code from the repo root: the deny rules' paths are relative to it.
