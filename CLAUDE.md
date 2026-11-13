# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Start here

**Status:** build steps 1–9 are done (code and daily workflow); deployment setup with the user is next. The full agreed spec, the decisions already made with the user, the open questions and the build order are in **`docs/PLAN.md`**. Read it before doing anything, and continue from its "Status" section.

## What this is

**Yellow** is a daily AI/IT news digest: a 9 AM GitHub Actions job collects free sources, dedupes, makes one Claude call, updates a tech registry and deploys a yellow phone PWA to GitHub Pages (pipeline and architecture: `docs/PLAN.md`).

The focus is **AI**. X/Twitter is deliberately **disabled** (its API is paid). `sources/x.py` is a stub that stays off until there's a token.

## Commands

Call the venv binaries directly (`.venv/bin/pytest`, `.venv/bin/ruff`, `.venv/bin/python`); the
planned file layout is in `docs/PLAN.md`.

```bash
python -m yellow run --dry-run --no-llm     # full pipeline, no API cost, writes site/
python -m yellow run                        # real run (needs ANTHROPIC_API_KEY); `--scheduled` adds the 9 AM gate
scripts/new-task.sh <type>/<name>          # after `git fetch origin`: branch from origin/main (--no-track), tidy merged branches
scripts/ship.sh "type(scope): summary" [body]  # checks, commit, prints the push + `gh pr create` commands to run
git fetch origin data && git worktree add data data   # optional (move an existing ./data aside first): the daily state (seen, registry, digests) lives on the `data` branch
python -m http.server -d site 8000          # preview: the sandbox blocks local ports, so the user runs this with `!`
```

## Rules

- **LLM cost matters.** Use exactly one Claude call per run, through `analyze.py`. The model comes from `config.yaml` (`llm.model`); the default is `claude-haiku-5-5`, and the alternative is `claude-sonnet-5-5`. Don't hardcode a model, add per-item calls, or add agent loops without asking.
- Use the official `anthropic` Python SDK with a Pydantic `output_format`, streamed (`client.messages.stream(...)` + `get_final_message()`, which returns the parsed message) because `llm.max_tokens` is 32k and the SDK refuses long non-streaming calls. Always check `stop_reason` before using the output, and fall back to the keyword-only digest on refusal or error so the site still builds.
- **Git workflow (user's request):** one branch per task (`<type>/<short-name>`), never commit or push to `main` (blocked by the PreToolUse hook `.claude/hooks/no-commit-on-main.py`). Commit messages follow Conventional Commits (`feat(scope): summary`; details in the `ship` skill). Push the branch, open a PR with `gh pr create`; **the user merges**.
- **No Claude attribution** in git: no `Co-Authored-By: Claude` trailers or "Generated with Claude Code" lines in commits or PRs (the user's request; also set via `attribution` in `.claude/settings.json`).
- The daily Action never commits to `main`: all state (`seen.json`, `tech_registry.json`, `digests/`) goes to the orphan `data` branch, checked out at `./data` (gitignored on `main`).
- **Never** commit secrets. `ANTHROPIC_API_KEY` lives in the environment or GitHub Secrets only.
- Sources must not throw and break the run. A failing source logs a warning and returns `[]`.
- Only use public, unauthenticated or free APIs/feeds, and set a descriptive generic User-Agent. No scraping that breaks a site's Terms of Service.
- Tests never touch the network. Save real responses into `tests/fixtures/` and parse those.
- Times are stored in UTC. They are converted to `config.yaml` `timezone` only for display and for the 9 AM gate.
- The UI is static HTML + vanilla JS with no framework or build step. Follow the `yellow-ui` skill.
- Python 3.12+, type hints everywhere, `ruff` clean.
- **Every module, class and function in `src/` has a docstring**, private and nested ones included (user's request). Enforced by ruff `D` rules (Google convention, via the edit hook) and `tests/test_docstrings.py`. Tests are exempt; their names describe them.
- Pydantic model fields (in `models.py` and `config.py`) are written as `name: Annotated[type, Field(..., description="...")] = default`, with constraints and `default_factory` inside `Field`.

## Project skills and agents

**How a task flows (branch → implementer → checks → review → commit → PR → user merges) is in
`.claude/WORKFLOW.md`. Follow it.**

- Skills and agents are listed in every session; their roles in the flow are in `WORKFLOW.md`. The `code-reviewer` runs **once per task**, not after every turn (usage limits matter).
- PostToolUse hook `.claude/hooks/ruff-on-edit.sh`: `ruff check --fix` then `ruff format` on every edited `.py` file; unfixable lint errors come back to Claude.
- PreToolUse hook `.claude/hooks/no-commit-on-main.py`: blocks `git commit`/`git push` on `main`.

## Working economically
The user is on a Claude subscription with a 5-hour usage window. Batch work into few turns, prefer deterministic scripts/hooks over agent runs, don't spawn agents for things a command can check, and don't re-run the reviewer unless a blocker fix was substantial.
