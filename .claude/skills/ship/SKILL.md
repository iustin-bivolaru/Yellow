---
name: ship
description: Finish the current Yellow task - run tests and lint, one independent code review, fix findings, update docs/PLAN.md, commit on a task branch (Conventional Commits, no attribution), push it and open a pull request for the user to merge. Use when a build step's code is written, or when the user says ship / commit / push / move on.
---

# Ship a task

Keep this cheap: one reviewer run per step, no extra agents, few turns.

**Never commit or push to `main`** (a PreToolUse hook blocks it). One branch per task, named
`<type>/<short-name>`, e.g. `feat/tech-registry`, `fix/hf-date-window`, `chore/ci-workflow`.
Create it **before** the first edit of a task: `git switch main && git pull && git switch -c <branch>`.

1. **Checks (deterministic, free):**
   `.venv/bin/ruff format . && .venv/bin/ruff check . && .venv/bin/pytest -q`
   Fix any failure before going on. Don't call the reviewer on red tests.
2. **Review once:** spawn the `code-reviewer` agent with the prompt
   "Review the uncommitted changes in this repository." Wait for its result.
   - Fix every blocker/major finding, or explain to the user why it's wrong.
   - Fix minor findings when the fix is small; otherwise add them to the
     "Carried over from code review" list in `docs/PLAN.md`.
   - Re-run the reviewer only if a blocker fix was substantial (at most once).
3. Re-run the checks from step 1.
4. **Update `docs/PLAN.md`:** tick the finished step in "Status", set "Next" to the following step.
5. **Commit** on the task branch: `git add -A`, then a Conventional Commits message:
   ```
   <type>(<scope>): <summary, imperative, lowercase, no period, <= 72 chars>

   <optional body: what changed and why, wrapped at ~72 chars>
   ```
   - type: `feat` (new behavior), `fix`, `refactor`, `perf`, `test`, `docs`, `chore`
     (tooling/config), `ci`, `build` (deps/packaging).
   - scope: the area, e.g. `sources`, `collect`, `analyze`, `registry`, `render`, `ui`, `cli`,
     `claude` (Claude Code setup). Optional when the change is repo-wide.
   - Breaking change: `feat(analyze)!: ...` plus a `BREAKING CHANGE:` line in the body.
   - Example: `feat(sources): add Reddit, arXiv, Hugging Face and GitHub adapters`
   - **No** `Co-Authored-By` or "Generated with Claude Code" lines.
6. **Push and open a PR:** `git push -u origin <branch>`, then
   `gh pr create --base main --title "<the commit summary line>" --body "<what/why, test count, review outcome>"`.
   Don't merge it: the **user merges** on GitHub. After they say it's merged:
   `git switch main && git pull && git branch -d <branch>`.
7. Report in a few lines: what shipped, test count, review outcome, PR link, next step.
