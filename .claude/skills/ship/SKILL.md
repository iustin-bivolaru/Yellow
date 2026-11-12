---
name: ship
description: Finish the current Yellow build step - run tests and lint, one independent code review, fix findings, update docs/PLAN.md, commit without attribution, push. Use when a build step's code is written, or when the user says ship / commit / push / move on.
---

# Ship a build step

Keep this cheap: one reviewer run per step, no extra agents, few turns.

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
5. **Commit and push:** `git add -A`, then a concise commit message describing the step.
   **No** `Co-Authored-By` or "Generated with Claude Code" lines. Then `git push origin main`.
6. Report in a few lines: what shipped, test count, review outcome, commit hash, next step.
