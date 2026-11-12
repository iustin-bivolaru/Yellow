---
name: add-source
description: Add a new news source (API, RSS feed, or site) to Yellow end to end — adapter, config, fixture, test. Use when the user wants news from a new place.
---

# Add a news source

## 0. Check it's allowed and free
- Prefer, in order: an official public API → an official RSS/Atom feed → nothing. Don't scrape HTML that the site's Terms of Service forbid, and don't add paid APIs without asking. X/Twitter stays disabled.
- If the source is just an RSS feed, **don't write code**. Add it to `config.yaml` under `sources.rss.feeds` with `name`, `url` and `weight`, and skip to step 4.

## 1. Adapter: `src/yellow/sources/<name>.py`
- Implement the `Source` protocol from `sources/base.py`: `name: str` and `fetch(since: datetime) -> list[Item]`.
- Use the shared `httpx` client with a timeout of 15s or less and the project User-Agent.
- Map into `Item` with: `title`, `url` (canonical, no tracking params), `source`, `published_at` (an **aware UTC** datetime), `snippet` (≤ 500 chars, stripped of HTML), and `score` (popularity signal, if the source has one).
- Return only items newer than `since`, and cap them at `config.max_items`.
- Wrap the whole fetch: on any exception, log a warning and `return []`. A source must never crash the run.

## 2. Register it
- Add it to the registry in `sources/__init__.py` and to `config.yaml` (`enabled: true` plus any options).

## 3. Fixture + test
- Save one real response to `tests/fixtures/<name>.json` (or `.xml`), trimmed to about 5 items.
- Add `tests/sources/test_<name>.py`. Parse the fixture through the adapter by mocking the HTTP layer, then assert the field mapping, the UTC conversion, the `since` filter, and that a failing HTTP call returns `[]`.

## 4. Verify
- Run `pytest tests/sources -q` and `ruff check .`
- Run `python -m yellow run --dry-run --no-llm` and confirm the new source shows a non-zero count in the summary.
