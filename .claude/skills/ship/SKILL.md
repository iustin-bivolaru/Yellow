---
name: ship
description: Finish the current Yellow task - run tests and lint, one independent code review, fix findings, update docs/PLAN.md, commit on a task branch (Conventional Commits, no attribution), push it and open a pull request for the user to merge. Use when a build step's code is written, or when the user says ship / commit / push / move on.
---

# Ship a task

Keep this cheap: one implementer run, one reviewer run per task, few turns. The whole flow is
described in `.claude/WORKFLOW.md`.

**Never commit or push to `main`** (a PreToolUse hook blocks it). One branch per task, named
`<type>/<short-name>`, e.g. `feat/tech-registry`, `fix/hf-date-window`, `chore/ci-workflow`.
Create it **before** the first edit of a task: `git switch main && git pull && git switch -c <branch>`.

0. **Implement (if not done yet):** spawn the `implementer` agent (Sonnet) with a brief: the goal,
   the `docs/PLAN.md` section, the files to create/change, the data contracts (models, function
   signatures), edge cases and test expectations, and what's out of scope. Resolve open questions
   with the user **before** briefing. Read its report; send follow-ups to the same agent
   (SendMessage) rather than starting a new one.

1. **Checks (deterministic, free):**
   `.venv/bin/ruff format . && .venv/bin/ruff check . && .venv/bin/pytest -q`
   Fix any failure before going on. Don't call the reviewer on red tests.
2. **Review once:** spawn the `code-reviewer` agent (Opus) with the prompt
   "Review the uncommitted changes in this repository." Wait for its result.
   - Fix every blocker/major finding, or explain to the user why it's wrong. Small fixes: do them
     directly. Larger ones: send them to the implementer agent that wrote the code.
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
6. **Push and open a PR:** `git push origin <branch>` (not `-u`: the sandbox protects
   `.git/config`, so the upstream can't be saved), then, **as its own Bash call** (a `gh` command
   only runs outside the sandbox when nothing is chained to it):
   `gh pr create --base main --head <branch> --title "<the commit summary line>" --body "<what/why, test count, review outcome>"`.
   Don't merge it: the **user merges** on GitHub. After they say it's merged:
   `git switch main && git pull --ff-only && git branch -D <branch>` and
   `git push origin --delete <branch>`.
7. Report in a few lines: what shipped, test count, review outcome, PR link, next step.
