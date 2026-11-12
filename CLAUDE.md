# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Start here

**Status:** planning and Claude Code setup are done; **no app code exists yet**. The full agreed spec, the decisions already made with the user, the open questions and the build order are in **`docs/PLAN.md`**. Read it before doing anything, and continue from its "Status" section.

## What this is

**Yellow** is a daily AI/IT news digest. Every morning at 9 AM (local time), a GitHub Actions job:
1. collects news from free sources (Hacker News, Reddit, arXiv, Hugging Face, GitHub, AI lab and tech-press RSS),
2. drops duplicates and anything already shown on a previous day,
3. sends one batch to the Claude API to summarize, categorize and extract technologies,
4. updates a technology registry (first-seen and trending tech),
5. renders a yellow-themed, mobile-first static PWA and deploys it to GitHub Pages.

The focus is **AI**. X/Twitter is deliberately **disabled** (its API is paid). `sources/x.py` is a stub that stays off until there's a token.

## Layout

```
config.yaml                  # timezone, sources, categories, llm.model, caps (no secrets)
src/yellow/
  models.py                  # pydantic: Item, Digest, Technology
  sources/                   # one module per source; each implements Source.fetch(since) -> list[Item]
  collect.py                 # parallel fetch, dedupe, data/seen.json filter
  analyze.py                 # the single Claude API call -> Digest
  tech_registry.py           # data/tech_registry.json: first_seen, daily counts, trending
  render.py                  # Jinja2 -> site/
  main.py                    # CLI entry: python -m yellow run
templates/                   # HTML/CSS/JS/PWA assets (yellow theme)
data/                        # state committed by CI: seen.json, tech_registry.json, digests/
site/                        # build output (gitignored, deployed by CI)
tests/                       # pytest, fixture-based, no network
.github/workflows/daily.yml
```

## Commands

```bash
source .venv/bin/activate
pip install -e ".[dev]"                     # install with dev deps
pytest                                      # all tests (offline, fixtures only)
pytest tests/test_registry.py -k trending   # single test
ruff check . && ruff format .               # lint + format
python -m yellow run --dry-run --no-llm     # full pipeline, no API cost, writes site/
python -m yellow run                        # real run (needs ANTHROPIC_API_KEY)
python -m http.server -d site 8000          # preview at http://localhost:8000
```

## Rules

- **LLM cost matters.** Use exactly one Claude call per run, through `analyze.py`. The model comes from `config.yaml` (`llm.model`); the default is `claude-haiku-5-5`, and the alternative is `claude-sonnet-5-5`. Don't hardcode a model, add per-item calls, or add agent loops without asking.
- Use the official `anthropic` Python SDK with `client.messages.parse(...)` and a Pydantic `output_format`. Always check `stop_reason` before using the output, and fall back to the keyword-only digest on refusal or error so the site still builds.
- **No Claude attribution** in git: no `Co-Authored-By: Claude` trailers or "Generated with Claude Code" lines in commits or PRs (the user's request; also set via `attribution` in `.claude/settings.json`).
- **Never** commit secrets. `ANTHROPIC_API_KEY` lives in the environment or GitHub Secrets only.
- Sources must not throw and break the run. A failing source logs a warning and returns `[]`.
- Only use public, unauthenticated or free APIs/feeds, and set a descriptive generic User-Agent. No scraping that breaks a site's Terms of Service.
- Tests never touch the network. Save real responses into `tests/fixtures/` and parse those.
- Times are stored in UTC. They are converted to `config.yaml` `timezone` only for display and for the 9 AM gate.
- The UI is static HTML + vanilla JS with no framework or build step. Follow the `yellow-ui` skill.
- Python 3.12+, type hints everywhere, `ruff` clean.

## Project skills and agents

- `/run-digest`: run and preview the pipeline locally.
- `/add-source`: add a new news source adapter end to end.
- `/yellow-ui`: design tokens and component rules for the phone UI.
- `/ship`: finish a build step: tests + lint, **one** `code-reviewer` pass, fix, update `docs/PLAN.md`, commit (no attribution), push.
- `code-reviewer` agent (Sonnet): independent reviewer with **no conversation context**; reviews only what's on disk. Runs once per build step via `/ship`, not after every turn (usage limits matter).
- `ui-builder` agent (Sonnet): builds the phone UI (templates/, CSS, JS, PWA) at build step 7, following `yellow-ui`.
- PostToolUse hook `.claude/hooks/ruff-on-edit.sh`: `ruff format` + `ruff check --fix` on every edited `.py` file; unfixable lint errors come back to Claude.

## Working economically
The user is on a Claude subscription with a 5-hour usage window. Batch work into few turns, prefer deterministic scripts/hooks over agent runs, don't spawn agents for things a command can check, and don't re-run the reviewer unless a blocker fix was substantial.
