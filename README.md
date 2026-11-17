# Yellow

## What it is

Yellow is a daily AI/IT news digest with a strong focus on AI. Every day at 9 AM (`Europe/Bucharest`, from `timezone` in `config.yaml`) a GitHub Actions job collects free sources, dedupes them, makes exactly one Claude call, updates a registry of technologies and deploys a yellow phone PWA (installable web app) to GitHub Pages.

X/Twitter is deliberately disabled because its read API is paid. `src/yellow/sources/x.py` is a stub that stays off until there is a token.

## How it works

Pipeline, once per run:

1. Collect all enabled sources in parallel (a failing source logs a warning and returns nothing; it never breaks the run).
2. Dedupe by canonical URL and normalized title, and drop items already in `data/seen.json`.
3. Pick up to `llm.max_items` items (fairly per source) and make **one** Claude call: category, 1-2 sentence summary, importance, technologies per item, plus the top 5 and a short "AI in a nutshell".
4. Update the tech registry (`data/tech_registry.json`): which technologies are new on the radar and which are trending.
5. Render the static site into `site/` (index, per-day archive, one page per technology, PWA files).
6. Save the state (registry, seen items, the day's digest) and deploy `site/` to GitHub Pages.

Sources (all free, configurable in `config.yaml`):

- Hacker News (Algolia API)
- Reddit: r/MachineLearning, r/LocalLLaMA, r/artificial, r/programming
- arXiv: cs.AI, cs.CL, cs.LG (capped)
- Hugging Face: daily papers and new trending models
- GitHub: new, fast-rising AI repos (`GITHUB_TOKEN` is optional)
- RSS blogs: OpenAI, Google DeepMind, Hugging Face, Mistral AI, Microsoft Research, TechCrunch AI, The Verge AI, Ars Technica, InfoQ AI
- X/Twitter: disabled

LLM backend (`llm.backend` in `config.yaml`):

- `claude-code` (default): runs the Claude Code CLI headless on your Claude subscription, authenticated with `CLAUDE_CODE_OAUTH_TOKEN`. No separate API billing. Every tool and MCP server is disabled (feed text is untrusted) and it is limited to `--max-turns 3`.
- `api`: the Anthropic SDK, which needs `ANTHROPIC_API_KEY` (you must also add it to the workflow).
- The model comes from `llm.model` (default `claude-haiku-5-5`, alternative `claude-sonnet-5-5`); it is never hardcoded.
- On refusal, error or `--no-llm`, a keyword-only digest is built so the site still builds.

## Who can use it

- **The site.** GitHub Pages on a free account needs a public repo, and the site has no login. Anyone with the URL (likely `https://iustin-bivolaru.github.io/Yellow/`) can read it and add it to their home screen, and search engines may index it. The content is public news, so that is accepted.
- **The daily run.** Readers only see the static HTML that is already built. They cannot trigger runs or use the owner's subscription. The token lives in GitHub Secrets, and only people with write access to the repo can dispatch the workflow. There is one Claude call a day, however many people read the site.
- **Forks.** Anyone can fork the repo and run their own copy with their own token (see "Deploy your own copy"). Forks never get the original repo's secrets.
- **Making it private.** Use GitHub Enterprise Cloud private Pages, or another host with a login in front (for example Cloudflare Pages with Cloudflare Access). An unlisted URL only hides the site; it does not protect it.

## Install on your phone

Open the Pages URL in your phone's browser, then choose **Add to Home Screen**. The app works offline from its cache.

## Run locally

Python 3.12+ is required.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

.venv/bin/python -m yellow run --dry-run --no-llm   # full pipeline, no Claude call, writes site/ only
.venv/bin/python -m yellow run                      # real run (see below)
.venv/bin/python -m yellow run --scheduled          # adds the 9 AM gate (what CI uses)
python3 -m http.server -d site 8000                 # preview at http://localhost:8000
```

- `--dry-run` writes only `site/`, never `data/`. `--no-llm` builds the keyword-only digest. `--scheduled` exits early before `run_hour` (local time) or when today's digest already exists. `--data-dir` and `--site-dir` override the default `./data` and `./site`.
- A real run needs the Claude Code CLI installed and authenticated: locally its own login, in CI `CLAUDE_CODE_OAUTH_TOKEN`.
- Optional: the daily state lives on the `data` branch. To get it locally (move an existing `./data` aside first): `git fetch origin data && git worktree add data data`. `data/` is gitignored on `main`.

## Deploy your own copy

1. In your own terminal run `claude setup-token` and copy the token it prints. No API billing is needed; the daily call counts toward your subscription's limits.
2. Create a GitHub repo and push the project. Pages on a free account needs a **public** repo (the content is public news; the token stays in Secrets).
3. Repo Settings, Pages, Source: **GitHub Actions**.
4. Set the secret: `gh secret set CLAUDE_CODE_OAUTH_TOKEN -R <owner>/<repo>` and paste the token when prompted.
5. Run the workflow manually (Actions, Daily digest, Run workflow, tick `force`). The first run creates the `data` branch. Then open the Pages URL on your phone and choose Add to Home Screen.
6. Recommended: add a `main` ruleset that requires a PR and the `CI` check and blocks force push and deletion. The bot only pushes to `data`, so no bypass is needed.
7. Recommended: trigger the run on time from outside GitHub. GitHub delays scheduled runs, sometimes by hours, so a free external scheduler such as [cron-job.org](https://cron-job.org) calls the workflow at 9 AM:
   - Token: a fine-grained GitHub token for `Yellow` only, with **Actions: Read and write** and nothing else; set an expiry (1 year) and a reminder to renew it.
   - Job: `POST https://api.github.com/repos/<owner>/Yellow/actions/workflows/daily.yml/dispatches`, daily at 09:05 and 09:35 `Europe/Bucharest` (the service handles daylight saving), with headers `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`, body `{"ref":"main","inputs":{"force":"false"}}`, and failure notifications on.
   - Test: a test run returns **204** and a `workflow_dispatch` run appears under Actions (401/403: token or permission wrong; 404: the token can't see the repo). With `force` false the 9 AM gate still applies, so extra calls are no-ops once today's digest exists.
   - If the token leaks, it can only start, re-run or cancel runs (a `force` run costs one Claude call); revoke it on GitHub. When it expires the calls fail and the GitHub crons remain the fallback.

## Schedule and state

A GitHub Actions workflow (`.github/workflows/daily.yml`) runs daily at 9 AM Europe/Bucharest. GitHub crons run in UTC with no daylight-saving support, so there are crons at 06:17, 07:17, 08:17 and 09:17 UTC (off the hour, because GitHub delays on-the-hour schedules most): 06:17 is 9:17 AM in summer and 07:17 in winter; the later ones are retries and do nothing if today's digest exists (the `--scheduled` gate; the digest file is saved last, as the "done" marker). GitHub still runs these late at times (hours, on busy days), so an external scheduler can start the workflow on time (step 7 of "Deploy your own copy"); the crons stay as the fallback.

Its state (seen items, tech registry, digests) is stored on the orphan `data` branch, never on `main`, so `main` stays code-only and can be protected by a ruleset. The branch is created on the first run. To get it locally, see "Run locally".

Trigger a manual run from the Actions tab: `force` skips the 9 AM gate, `no_llm` skips the Claude call.

The workflow has three jobs so the write token never reaches code that parses feeds:

- `build`: read-only. Reads the `data` branch, runs the CLI without `GITHUB_TOKEN`, and uploads the new state and the Pages artifact.
- `persist`: the only job with `contents: write`. Runs no project code; it copies the state onto the `data` branch and pushes.
- `deploy`: publishes the Pages artifact (only if `site/index.html` was rendered).

## Configuration

Everything is in `config.yaml` (no secrets). Main keys:

- `timezone`, `run_hour`: display timezone and the local hour from which the scheduled run may publish. Stored times are UTC.
- `site`: `title`, `base_url` (set to `/<repo-name>/` for a Pages project site if needed), `archive_days`.
- `http`: `user_agent`, `timeout_seconds`.
- `llm`: `backend`, `model`, `effort`, `max_tokens`, `max_items`, `snippet_chars`.
- `caps`: `lookback_hours`, `max_items_per_source`, `seen_retention_days`.
- `registry`: thresholds for trending and the size of the "new" and "trending" lists.
- `categories`: the category list Claude assigns from.
- `sources`: per-source `enabled` and options, including the RSS feed list.

Secrets come from the environment only: `CLAUDE_CODE_OAUTH_TOKEN` (or `ANTHROPIC_API_KEY` for the `api` backend), optional `GITHUB_TOKEN`.

## Development

```bash
.venv/bin/ruff format . && .venv/bin/ruff check . && .venv/bin/pytest -q
```

- Tests never touch the network: they parse saved real responses from `tests/fixtures/`.
- Every module, class and function in `src/` needs a docstring (enforced by ruff `D` rules, Google convention, and `tests/test_docstrings.py`). Pydantic fields use `Annotated[type, Field(..., description=...)]`.
- Workflow: one branch per task (`<type>/<short-name>`), Conventional Commits, a PR for each, and the owner merges. Never commit to `main`. Helpers: `scripts/new-task.sh <type>/<name>` to start a branch and `scripts/ship.sh "type(scope): summary"` to run checks and commit. Details in [`.claude/WORKFLOW.md`](.claude/WORKFLOW.md); the full spec and decisions are in [`docs/PLAN.md`](docs/PLAN.md).
- Never commit secrets.

## Project layout

```
config.yaml            settings, sources, categories
pyproject.toml         package and tool config
src/yellow/
  main.py              CLI (python -m yellow run)
  config.py, models.py typed config and data models
  collect.py           parallel fetch, dedupe, seen filter
  analyze.py           the one Claude call, keyword fallback
  tech_registry.py     new and trending technologies
  render.py            builds site/ from templates/
  sources/             one module per source
templates/             Jinja2 pages, CSS, JS, PWA files
tests/                 pytest, fixtures in tests/fixtures/
scripts/               new-task.sh, ship.sh
docs/PLAN.md           spec, decisions, status
.github/workflows/     daily.yml (digest), ci.yml (ruff + pytest on PRs)
data/                  the `data` branch worktree (gitignored on main)
site/                  rendered output (generated)
```
