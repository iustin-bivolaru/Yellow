"""GitHub search API: recently created AI repos that already gained many stars.

GitHub has no official "trending" API, so this approximates it: repos created within
sources.github_trending.created_within_days, matching the query, sorted by stars.
Uses GITHUB_TOKEN from the environment when set (Actions provides one) for a higher rate limit.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from yellow.models import Item, item_id
from yellow.sources.abstract_source import Source
from yellow.text import canonical_url, html_to_text, is_http_url, parse_iso_utc

API_URL = "https://api.github.com/search/repositories"


class GithubTrendingSource(Source):
    """New, fast-rising AI repositories on GitHub."""

    name = "github_trending"

    def _fetch(self, since: datetime) -> list[Item]:
        """Run one search query and parse it."""
        scfg = self.cfg.sources.github_trending
        created_after = (datetime.now(UTC) - timedelta(days=scfg.created_within_days)).date()
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if token := os.environ.get("GITHUB_TOKEN"):
            headers["Authorization"] = f"Bearer {token}"
        resp = self.client.get(
            API_URL,
            params={
                "q": f"{scfg.query} created:>{created_after.isoformat()} stars:>={scfg.min_stars}",
                "sort": "stars",
                "order": "desc",
                "per_page": min(scfg.max_items, self.cfg.caps.max_items_per_source),
            },
            headers=headers,
        )
        resp.raise_for_status()
        return parse(resp.json())


def parse(data: dict) -> list[Item]:
    """Turn a repository search response into Items (forks are skipped)."""
    items: list[Item] = []
    for repo in data.get("items", []):
        name = repo.get("full_name")
        url = repo.get("html_url")
        created = parse_iso_utc(repo.get("created_at"))
        if not name or not is_http_url(url) or created is None or repo.get("fork"):
            continue
        description = html_to_text(repo.get("description"), limit=400)
        details = [repo.get("language"), ", ".join(repo.get("topics") or [])[:200] or None]
        extra = " · ".join(d for d in details if d)
        snippet = extra or None  # the description is already in the title
        items.append(
            Item(
                id=item_id(canonical_url(url)),
                title=f"{name}: {description}" if description else name,
                url=url,
                source="github_trending",
                source_name="GitHub",
                published=created,
                snippet=snippet,
                score=repo.get("stargazers_count"),
            )
        )
    return items
