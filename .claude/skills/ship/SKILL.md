---
name: ship
description: Finish the current Yellow task - one independent code review, fixes by the implementer, then scripts/ship.sh (checks, commit on the task branch with a Conventional Commits message, no attribution) and the printed push + PR commands. Use when a build step's code is written, or when the user says ship / commit / push / move on.
---

# Ship a task

The whole flow, roles and quirks are in `.claude/WORKFLOW.md`. The main session does not edit code:
agents do. Keep it cheap: one implementer run, one reviewer run per task, few turns.

**Never commit or push to `main`** (a PreToolUse hook blocks it). One branch per task, named
`<type>/<short-name>`, created **before** the first edit:

1. `git fetch origin` (as its own command), then `scripts/new-task.sh <type>/<short-name>`.
   Exit 3 means the switch touches sandbox-protected paths: give the user the printed
   `git switch --no-track -c ...` line to run with `!`.
2. **Implement:** spawn `implementer` (or `ui-builder`) with a brief: goal, the `docs/PLAN.md`
   section, files, data contracts, edge cases, test expectations, the `docs/PLAN.md` status line to
   set (tick the step, set "Next"), and what's out of scope. Resolve open questions with the user
   **before** briefing. Send follow-ups to the same agent (SendMessage), not a new one.
3. **Review once:** spawn `code-reviewer` with "Review the uncommitted changes in this repository."
   - Decide per finding. Blocker/major: fix (or explain to the user why it's wrong). Minor: fix if
     small, else add to "Carried over from code review" in `docs/PLAN.md`.
   - Fixes go to the same implementer, not the main session. Re-review only if a blocker fix was
     substantial (at most once).
4. **Ship:** `scripts/ship.sh "<type>(<scope>): <summary>" ["<body>"]`. It runs
   `ruff format --check`, `ruff check` and `pytest`, stages everything, refuses secret files,
   validates the message (lowercase, no period, <= 72 chars, no attribution) and commits. If the
   checks fail, send the failure to the implementer and re-run.
   - type: `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `chore`, `ci`, `build`.
   - scope: `sources`, `collect`, `analyze`, `registry`, `render`, `ui`, `cli`, `ci`, `claude`.
     Optional when repo-wide.
   - Breaking change: `feat(analyze)!: ...` plus a `BREAKING CHANGE:` line in the body.
5. **Push and open the PR:** run the two commands the script printed, **each as its own Bash call**
   (`git push origin <branch>`, then `gh pr create --base main --head <branch> ...`). No `-u`:
   the sandbox protects `.git/config`. CI runs ruff + pytest on the PR. The **user merges**.
6. Report in a few lines: what shipped, test count, review outcome, PR link, next step.
