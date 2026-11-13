# Yellow: build plan and decisions

This is the agreed spec for Yellow. Decisions marked **(decided)** were made with the user, so don't reopen them unless the user asks. Read this file together with `CLAUDE.md`.

## Status (2026-11-13)

- [x] Plan agreed with the user
- [x] Claude Code setup: `CLAUDE.md`, skills (`run-digest`, `add-source`, `yellow-ui`, `ship`), agents (`implementer` Sonnet, `code-reviewer` Opus, `ui-builder` Sonnet), ruff and no-commit-on-main hooks, Bash sandbox with secret files blocked. `.gitignore` added. (The early auto-review Stop hook was removed to save usage.)
- [x] Workflow (2026-11-13, PRs #1, #2, #4): one branch per task, Conventional Commits, PRs merged by the user; implementer → checks → one Opus review per task. See `.claude/WORKFLOW.md`.
- [x] Build step 1: package skeleton, `config.py` (strict), `models.py`, tests (pushed as 91a01fc)
- [x] Build step 2: `sources/abstract_source.py`, Hacker News, RSS (9 verified feeds), `text.py` (canonical URLs), fixtures + tests
- [x] Build step 3: `collect.py` (parallel fetch, transitive dedupe by canonical URL + normalized title, `data/seen.json` filter/mark/prune), tests
- [x] Build step 4: Reddit (one combined request + 429 retry), arXiv, Hugging Face (papers + new trending models), GitHub (new repos by stars), X stub; real fixtures + tests. Live run: ~170 items/day after dedupe.
- [x] Build step 5: `analyze.py`: fair per-source selection (≤ `llm.max_items`), keyword fallback (`--no-llm`), one streamed Claude call with structured output, stop_reason checks, cost log. Tested with a fake client; **not yet run against the real API** (no key locally).
- [x] Build step 6: `tech_registry.py` (slug-keyed registry; `C++`/`C#`/`.NET` keep distinct slugs; per-day `counts` and `items` overwritten so same-day reruns are idempotent; New on radar + trending from `config.yaml` `registry`), tests
- [x] CI (2026-11-13): `.github/workflows/ci.yml` runs ruff format/check + pytest on every PR and on pushes to `main`. Later: a GitHub ruleset on `main` that requires a PR and this check (see the step 9 note below).
- [x] Build step 7: `render.py` (save/load digests, `render_site`: index, `day/`, `tech/<slug>`, PWA files, stdlib PNG icons) + `templates/` (yellow-ui), tests. Relative links (Pages subpath); SW cache id = digest time + templates hash; offline navigation to an uncached page redirects home. **Not checked by eye yet at 390×844 / dark mode**: the user previews `site/` (`python3 -m http.server -d site 8000`).
- [x] Build step 8: `main.py` CLI (`run --dry-run --no-llm --scheduled --data-dir --site-dir`); state (digest, registry, seen) saved only after render and never on `--dry-run`; empty collection keeps an existing digest; 9 AM gate. Live dry run: 197 collected, 192 new, 150 analyzed, no source warnings.
- [ ] **Next: build step 9** (GitHub workflow; decide data-branch vs commit-to-main with the user first).
- [ ] One-time setup by the user, after the code works (see "Deployment setup")

### Answered questions
1. **Timezone for "9 AM"**: `Europe/Bucharest` (decided 2026-11-12).
2. `CLAUDE.md` and `.claude/` are version-controlled: the user said yes, so they were removed from `.git/info/exclude` and committed (2026-11-12).

### How to build
- Every step follows `.claude/WORKFLOW.md`: task branch → `implementer` agent (Sonnet) from a brief → checks → one `code-reviewer` pass (Opus) → commit → PR → the user merges.
- Build the **interface** (templates/, style.css, app.js, PWA files; build step 7) with the `ui-builder` agent instead of `implementer` (user's request), briefed with the `yellow-ui` skill and the `render.py` data contract.
- Step 9's daily GitHub Action commits `data/` to `main` as the github-actions bot. That's the one allowed exception to "no direct commits to main" (state, not code). If GitHub branch protection is ever added, the Action needs a bypass or its own branch.
- **Proposed for step 9 (not decided yet):** the daily Action writes `data/` to a separate `data` branch instead, so a ruleset can protect `main` (PR + passing `CI`) with no bypass. Keep the local no-commit-on-main hook too: it catches mistakes before a commit, the ruleset is the server-side lock.

### Carried over from code review (do in the named step)
- ~~Per-source config models with `extra="forbid"`~~: done in `config.py` (`SourcesConfig`). A new source must add its model there.
- First real Claude run (with a key): check that 150 items fit in `max_tokens` 32k with room to spare (log shows output tokens), and that summaries/categories look right.
- `collect._rank` compares scores across scales (stars vs points) when merging duplicates; only affects which copy is shown. Revisit if it looks wrong in the UI.

## What the user wants

An app that delivers **IT news every morning at 9 AM**, with a strong focus on **AI**. It should:
- track what's new, and the technologies being used, especially **new technologies as they appear**,
- group everything into categories,
- show it in a **nice phone interface with a yellow theme**.

## Decisions

| Topic | Decision |
|---|---|
| X / Twitter | **Skip for now** (decided). Its read API is paid. Keep `sources/x.py` as a disabled stub, to be enabled later with an `X_BEARER_TOKEN`. The user has an X account (made with a dedicated Google account) for later. |
| Delivery | **Static installable web app (PWA) on GitHub Pages** (decided). The user opens it on their phone from the home screen. |
| Scheduler | **GitHub Actions** cron, so it runs even when the Mac is off (decided). |
| Summarizing | **Claude API, one call per run** (decided). Not the Claude Agent SDK, whose agent loop would use 10–50× more tokens. |
| Model | **`claude-haiku-5-5` by default**, switchable to `claude-sonnet-5-5` via `config.yaml` `llm.model` (decided, to keep costs low). Don't use Opus. |
| Language | Python 3.12+ (the project has a `.venv` and is opened in PyCharm) |

## Architecture

```
GitHub Actions (cron ~9 AM local)
  → collect all sources in parallel → dedupe → drop items already in data/seen.json
  → ONE Claude call (summaries, categories, importance, technologies, top 5, intro)
  → update data/tech_registry.json (new on radar / trending)
  → render site/ (Jinja2) → commit data/ → deploy site/ to GitHub Pages
```

## Files to create

```
pyproject.toml          # deps: anthropic, httpx, feedparser, jinja2, pydantic, pyyaml; dev: pytest, ruff
config.yaml             # timezone, sources + feed URLs, categories, llm.model/effort, caps
src/yellow/
  __main__.py, main.py  # CLI: python -m yellow run [--dry-run] [--no-llm]
  models.py             # Item, ItemAnalysis, Technology, Digest (pydantic)
  sources/abstract_source.py # Source protocol: name, fetch(since) -> list[Item]
  sources/__init__.py   # registry of enabled sources
  sources/hackernews.py # Algolia HN API: stories from the last 24h above a points threshold
  sources/rss.py        # generic RSS/Atom; feed list in config.yaml
  sources/reddit.py     # .rss of r/MachineLearning, r/LocalLLaMA, r/artificial, r/programming
  sources/arxiv.py      # cs.AI / cs.CL / cs.LG new submissions (capped; rank by HF daily-paper upvotes when available)
  sources/huggingface.py# HF daily papers + trending models API
  sources/github_trending.py # GitHub search API: recently created AI repos with fast star growth
  sources/x.py          # disabled stub
  collect.py            # run sources concurrently, canonicalize URLs, dedupe by URL + normalized title, seen filter
  analyze.py            # Claude call → Digest; keyword fallback
  tech_registry.py      # first_seen / last_seen / daily counts; new + trending
  render.py             # Jinja2 → site/ (index, per-day archive, tech pages, PWA files)
templates/ index.html.j2, day.html.j2, tech.html.j2, style.css, app.js, manifest.json, sw.js, icon.svg (+ 192/512 PNG)
data/                   # committed by CI: seen.json, tech_registry.json, digests/YYYY-MM-DD.json
tests/                  # pytest, fixtures in tests/fixtures/, no network
.github/workflows/daily.yml
```

Then update `CLAUDE.md` if anything differs from what's written there.

## Sources (initial set, all free; configurable)

- **Hacker News** (Algolia API)
- **Reddit** RSS: r/MachineLearning, r/LocalLLaMA, r/artificial, r/programming
- **arXiv**: cs.AI, cs.CL, cs.LG (heavily capped)
- **Hugging Face**: daily papers, trending models
- **GitHub**: new, fast-rising AI repos (search API; use `GITHUB_TOKEN` in Actions for rate limits)
- **RSS blogs**: OpenAI, Google DeepMind, Hugging Face, Mistral, Microsoft Research, TechCrunch AI, The Verge AI, Ars Technica, InfoQ (all verified 2026-11-12). Anthropic and Meta AI have no RSS feed, so they were dropped.

Rules: a failing source logs a warning and returns `[]`. Use a generic User-Agent (no personal info). No ToS-violating scraping.

## Claude analysis (`analyze.py`)

- `anthropic` SDK, `client.messages.stream(model=cfg.llm.model, max_tokens=32000, output_config={"effort": "low"}, output_format=LLMOutput, ...)` + `get_final_message()` (streamed: 150 items need ~15-20k output tokens, too long for a non-streaming call).
- With `claude-sonnet-5-5`, also send `betas=["server-side-fallback-2026-07-01"]` and `fallbacks="default"`. Haiku 5.5 has no server-side fallback.
- Check `stop_reason` (`refusal`, `max_tokens`) before using `parsed_output`. On any failure, build the keyword-only digest so the site still builds.
- Input: up to about 150 items, each with id, title, source, snippet (truncated) and score. Pass the existing tech-registry names so Claude normalizes them (for example "Llama-4" → "Llama 4").
- Output: per item: `category`, a 1–2 sentence `summary`, `importance` 1–5, `technologies[]`. Plus `top5` (item ids) and `nutshell` (3 sentences on AI today).
- **Categories:** AI Models & Releases · AI Agents & Tools · AI Research · Dev Tools & Frameworks · Open Source · Cloud & Infra · Security · Industry & Funding · Other Tech.
- Log token usage and estimated cost each run. Expected: about 25k input + 8k output tokens/day, roughly $0.007/day on Haiku 5.5 (~$4/month on Sonnet 5.5).

## Technology tracking (`tech_registry.py`)

- Per technology: `first_seen`, `last_seen`, `counts: {date: n}`, and `items: {date: [ids]}`.
- **New on radar** = first seen today. **Trending** = today's mentions ≥ 2× the 7-day average (with a small minimum count).
- Every technology gets a page listing all stories that mentioned it.

## Phone UI (full rules in the `yellow-ui` skill)

- Static HTML, vanilla JS, no framework or build step. An installable PWA (manifest, icons, service worker, works offline).
- Yellow `#FFD400` header and accents, off-white background, near-black text. Dark mode is yellow on `#121212`.
- Order: header (date) → "AI in a nutshell" → **Top 5** → **New on radar** chips → sticky category filter chips → feed cards (title link, summary, source badge, importance dots, tech tags) → archive (last 30 days).
- Autoescape everything that comes from feeds.

## Scheduling (`.github/workflows/daily.yml`)

- GitHub cron runs in UTC with no daylight-saving support. Schedule **two** crons, one hour apart, covering 9 AM local in both summer and winter time. The job exits early unless the current local hour in `config.yaml` `timezone` is **at least** `run_hour` (9) **and** today's digest doesn't exist yet (GitHub crons run late, and the second cron is the retry; the digest file is saved last, as the "done" marker). Add `workflow_dispatch` for manual runs.
- Steps: checkout → setup Python 3.12 → `pip install .` → `python -m yellow run` → commit `data/` (as the github-actions bot) → `actions/upload-pages-artifact` with `site/` → `actions/deploy-pages`.
- Permissions: `contents: write`, `pages: write`, `id-token: write`. Secret: `ANTHROPIC_API_KEY`.

## Deployment setup (the user does this once; walk them through it)

1. Create an API key at console.anthropic.com, add credit, and set a monthly spend limit.
2. Create a GitHub repo and push this project. Pages on a free account needs a **public** repo; the content is public news anyway, and the key stays in Secrets.
3. Repo Settings → Pages → Source: **GitHub Actions**.
4. Repo Settings → Secrets → Actions: add `ANTHROPIC_API_KEY`.
5. Run the workflow manually, open the Pages URL on the phone, then choose **Add to Home Screen**.

## Build order

1. `pyproject.toml`, package skeleton, `models.py`, `config.yaml`
2. `sources/abstract_source.py` + Hacker News + RSS, with fixtures and tests
3. `collect.py` (dedupe, seen filter), with tests
4. Remaining sources, with fixtures and tests
5. `analyze.py`: keyword fallback first (`--no-llm`), then the Claude call
6. `tech_registry.py`, with tests (new, trending)
7. `render.py` + templates (follow the `yellow-ui` skill), checked at 390×844 in light and dark
8. `main.py` CLI wiring, then `/run-digest`
9. GitHub workflow, then update `CLAUDE.md`, then guide the user through deployment setup

## Verification

- `pytest` and `ruff check .` pass.
- `python -m yellow run --dry-run --no-llm` builds `site/` with real sources; preview at phone width.
- `python -m yellow run --dry-run` with a key: the categories, summaries and New on radar look sensible, and the cost is logged.
- After deployment: a manual workflow run succeeds, the page opens on the phone, and the next 9 AM run updates it.
