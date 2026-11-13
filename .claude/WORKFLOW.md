# How we work on Yellow

This is the working agreement between the user and Claude Code for this repo. `CLAUDE.md` holds
the project rules; this file describes the process. The `ship` skill is the executable version.

The main session only talks, plans, briefs and decides. Agents write code and fix findings. The
mechanical git/check steps are two scripts, so nothing is improvised.

## Roles

| Who | Model | Does | Never does |
|---|---|---|---|
| **User** | - | Decides scope and open questions, merges every PR on GitHub, owns sandbox/permission settings; runs `/sandbox exclude "gh pr *"` once so `gh pr create` works from the session | - |
| **Main session** | Opus | Talks with the user, plans, writes briefs, decides what to do with review findings, runs `scripts/new-task.sh`, `scripts/ship.sh` and the network commands they print, reports briefly | Edits code, fixes findings itself, merges PRs, loosens the sandbox |
| **`implementer` agent** | Sonnet | Code, tests, fixtures, the `docs/PLAN.md` status line (from the brief) and review fixes (sent back to the same agent); runs ruff + pytest; reports | Commits, pushes, switches branches, widens scope |
| **`ui-builder` agent** | Sonnet | Same as the implementer, for the phone UI (templates, CSS, JS, PWA), following the `yellow-ui` skill | Commits |
| **`code-reviewer` agent** | Opus | Reviews the uncommitted diff, once per task, with no context of why it was written; reports findings | Edits files |
| **CI** | GitHub Actions | Independent ruff + pytest on every PR (replaces re-running checks in the main session) | - |

## The flow for one task

1. **Agree on the task.** The main session reads `docs/PLAN.md` ("Status" says what's next) and
   settles open questions with the user first. Subagents can't ask the user anything.
2. **Branch.** `git fetch origin` (its own command), then `scripts/new-task.sh <type>/<short-name>`
   (e.g. `feat/tech-registry`). It validates the name, creates the branch from `origin/main` with
   `--no-track`, fast-forwards local `main` and deletes merged local branches. If it exits 3,
   the user runs the printed `git switch --no-track -c ...` line with `!`, then the session runs
   `scripts/new-task.sh --tidy` (housekeeping only). Never work on `main`.
3. **Implement.** The main session writes a brief (goal, PLAN section, files, data contracts,
   edge cases, tests, the `docs/PLAN.md` status line to set, out of scope) and spawns
   `implementer` (or `ui-builder`).
4. **Review once.** `code-reviewer` reviews the uncommitted changes. The main session decides per
   finding: blocker/major are fixed; minor are fixed if small, else added to "Carried over from
   code review" in `docs/PLAN.md`. Fixes go back to the same implementer, not the main session.
   A second review only if a blocker fix was substantial.
5. **Ship.** `scripts/ship.sh "<type>(<scope>): <summary>" ["<body>"]` runs ruff + pytest, stages
   everything, refuses secret files, commits, and prints the next commands.
6. **Push + PR.** Run the printed `git push origin <branch>` and `gh pr create ...`, each as its
   own command.
7. **CI checks the PR; the user merges** on GitHub. Then the session runs `git fetch origin` and
   `scripts/new-task.sh --tidy`, or goes straight to the next task's `new-task.sh`. Delete the remote branch with
   `git push origin --delete <branch>` if GitHub didn't.
8. **Report** in a few lines: what shipped, test count, review outcome, PR link, next step.

## Commit messages (Conventional Commits)

```
<type>(<scope>): <imperative summary, lowercase, no period, <= 72 chars>

<optional body: what and why>
```
Types: `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `chore`, `ci`, `build`.
Scopes: `sources`, `collect`, `analyze`, `registry`, `render`, `ui`, `cli`, `ci`, `claude`.
`ship.sh` enforces the format and rejects attribution text.

## Guardrails that run automatically

| What | Where | Effect |
|---|---|---|
| Task scripts | `scripts/new-task.sh`, `scripts/ship.sh` | Validate names/messages, refuse a dirty tree, `main`, secret files and failing checks; local steps only, they print the network commands |
| Ruff on every edit | PostToolUse hook `.claude/hooks/ruff-on-edit.sh` | Autofixes + formats each edited `.py` file; unfixable lint errors go back to the agent |
| No commits to main | PreToolUse hook `.claude/hooks/no-commit-on-main.py` | Blocks `git commit`/`git push` on `main` and pushes to `main`. It matches command text, so it stops mistakes, not deliberate workarounds. There is no GitHub branch protection (the user's choice) |
| CI | `.github/workflows/ci.yml` | ruff format/check + pytest on every PR; the user merges only on a green check |
| Docstrings | ruff `D` rules + `tests/test_docstrings.py` | Every module/class/function in `src/` needs one |
| Secret files | deny rules + Bash sandbox in `.claude/settings.json` | Secret files can't be read by any tool or shell command (the tracked example file is the only exception, so git works); `ship.sh` also refuses to stage them |
| Sandbox | `.claude/settings.json` `sandbox` | Every shell command runs in a macOS sandbox, network limited to the project's sources, PyPI, GitHub and the Anthropic API. `git push/fetch` and `gh pr` run outside it (they need the keychain) and still ask permission |
| Review of Claude config | `code-reviewer` agent | Reviews `.claude/hooks/*.sh` and `.claude/settings.json` like code; skips prose (skills, agent text, this file) |

## Cost rules (5-hour usage window)

- One implementer run and one review per task; follow-ups go to the same agent, not a new one.
- Deterministic scripts, hooks and CI instead of agent runs wherever possible.
- The app itself makes exactly one Claude API call per daily run (see `CLAUDE.md`).

## Exceptions

- **The daily bot pushes only to the `data` branch.** From build step 9 the GitHub Action stores
  state (seen items, tech registry, digests) on the orphan `data` branch. Nothing commits to `main`
  outside PRs.

## Quirks to know

- Network git (`fetch`, `push`) and `gh` only work as their own top-level command (they're excluded
  from the sandbox by command pattern). Chained, or inside a script, they run sandboxed and fail.
  That is why the scripts do local steps only and print the network commands.
- Always `git switch --no-track -c <branch> origin/main`. Tracking writes `.git/config`, which the
  sandbox blocks: git then dies after swapping files but before moving HEAD, and the next commit
  lands on the old branch. For the same reason `git push -u` is not used; push with
  `git push origin <branch>` and pass `--head <branch>` to `gh`.
- The sandbox write-protects `.claude/settings*.json`, `.claude/hooks`, `.claude/skills`,
  `.claude/agents`, the example env file and `.git/config`. A switch/checkout/pull whose diff
  touches them half-fails (files partly swapped, HEAD unchanged). `new-task.sh` detects this and
  prints the one-liner for the user to run with `!` (then `--tidy`). Edits to those paths also need the user.
- Commands that mention the secret-file name are blocked by a deny rule, so commit messages and
  commands avoid that text.
- Start Claude Code from the repo root: the deny rules' paths are relative to it.
- `SHIP_CHECK_CMD` overrides the check command in `ship.sh` only when `SHIP_TEST_MODE=1` is also set; only the tests use it.
