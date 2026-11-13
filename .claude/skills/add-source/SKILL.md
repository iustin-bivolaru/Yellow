---
name: add-source
description: Add a new news source (API, RSS feed, or site) to Yellow end to end — adapter, config, fixture, test. Use when the user wants news from a new place.
---

# Add a news source

## 0. Check it's allowed and free
- Prefer, in order: an official public API → an official RSS/Atom feed → nothing. Don't scrape HTML that the site's Terms of Service forbid, and don't add paid APIs without asking. X/Twitter stays disabled.
- If the source is just an RSS feed, **don't write code**. Add it to `config.yaml` under `sources.rss.feeds` with `name` and `url`, and skip to step 4.

## 1. Adapter: `src/yellow/sources/<name>.py`
- Subclass `Source` from `sources/abstract_source.py`: set `name` (same as the config key) and implement `_fetch(since)`. The base `fetch()` already catches every exception, logs a warning and returns `[]`.
- Put parsing in a module-level `parse(...)` function so tests can call it on a fixture directly. Every function needs a docstring.
- Use `self.client` (the shared `httpx` client: project User-Agent and timeout already set).
- Map into `Item`: `id=item_id(canonical_url(url))`, `title`, `url` (check `is_http_url`), `source`, `source_name`, `published` (aware UTC; `parse_iso_utc` / `rss.entry_time` help), `snippet` via `html_to_text` (≤ 500 chars), `score` and `discussion_url` when the source has them.
- Return only items newer than `since` (or a source-specific age window, as for GitHub/HF models), capped at `caps.max_items_per_source` or a per-source `max_items`.

## 2. Register it
- Add it to `REGISTRY` in `sources/__init__.py`, give it a config model in `config.py` `SourcesConfig` (`Annotated` fields, `extra="forbid"` via `SourceConfig`), and add it to `config.yaml`.

## 3. Fixture + test
- Save one real response to `tests/fixtures/<name>.json` (or `.xml`), trimmed to about 5 items.
- Add tests to `tests/test_sources_more.py` (or a new `tests/test_sources_<name>.py`). Parse the fixture with `parse(...)`, and drive `fetch` through `httpx.MockTransport`. Assert the field mapping, UTC times, the `since` filter, and that an HTTP error returns `[]`. Update `test_enabled_sources_only_returns_implemented_enabled`.

## 4. Verify
- Run `pytest -q` and `ruff check .`
- Run `python -m yellow run --dry-run --no-llm` and confirm the new source shows a non-zero count in the summary.
