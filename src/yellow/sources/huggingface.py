"""Hugging Face via its public API: today's daily papers and new trending models.

Trending models are rarely less than a day old, so they use their own age window
(sources.huggingface.model_max_age_days); data/seen.json keeps them from repeating on later days.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from yellow.models import Item, item_id
from yellow.sources.abstract_source import Source
from yellow.text import canonical_url, html_to_text, parse_iso_utc

PAPERS_URL = "https://huggingface.co/api/daily_papers"
MODELS_URL = "https://huggingface.co/api/models"
PAPER_PAGE = "https://huggingface.co/papers/{}"
MODEL_PAGE = "https://huggingface.co/{}"


class HuggingFaceSource(Source):
    """Hugging Face daily papers and new trending models."""

    name = "huggingface"

    def _fetch(self, since: datetime) -> list[Item]:
        """Fetch papers and models; either part may be switched off in config."""
        scfg = self.cfg.sources.huggingface
        limit = self.cfg.caps.max_items_per_source
        items: list[Item] = []
        if scfg.papers:
            resp = self.client.get(PAPERS_URL, params={"limit": limit})
            resp.raise_for_status()
            items += parse_papers(resp.json(), since)[:limit]
        if scfg.models:
            resp = self.client.get(
                MODELS_URL, params={"sort": "trendingScore", "direction": -1, "limit": limit}
            )
            resp.raise_for_status()
            cutoff = datetime.now(UTC) - timedelta(days=scfg.model_max_age_days)
            items += parse_models(resp.json(), cutoff)[: scfg.max_models]
        return items


def parse_papers(data: list[dict], since: datetime) -> list[Item]:
    """Turn a daily_papers response into Items listed on `since`'s UTC date or later."""
    items: list[Item] = []
    for entry in data:
        paper = entry.get("paper") or {}
        paper_id = paper.get("id")
        title = html_to_text(paper.get("title") or entry.get("title"), limit=300)
        added = parse_iso_utc(paper.get("submittedOnDailyAt") or entry.get("publishedAt"))
        # Daily-list times are midnight-truncated, so compare dates: a run 26h later still
        # sees yesterday's list. data/seen.json stops repeats.
        if not paper_id or not title or added is None or added.date() < since.date():
            continue
        url = PAPER_PAGE.format(paper_id)
        items.append(
            Item(
                id=item_id(canonical_url(url)),
                title=title,
                url=url,
                source="huggingface",
                source_name="HF Papers",
                published=added,
                snippet=html_to_text(paper.get("ai_summary") or paper.get("summary"), limit=500),
                score=paper.get("upvotes"),
            )
        )
    return items


def parse_models(data: list[dict], cutoff: datetime) -> list[Item]:
    """Turn a trending-models response into Items for models created at or after `cutoff`."""
    items: list[Item] = []
    for model in data:
        model_id = model.get("id") or model.get("modelId")
        created = parse_iso_utc(model.get("createdAt"))
        if not model_id or created is None or created < cutoff:
            continue
        url = MODEL_PAGE.format(model_id)
        details = [
            model.get("pipeline_tag"),
            model.get("library_name"),
            f"{model.get('likes', 0)} likes",
            f"{model.get('downloads', 0)} downloads",
        ]
        items.append(
            Item(
                id=item_id(canonical_url(url)),
                title=f"New trending model: {model_id}",
                url=url,
                source="huggingface",
                source_name="HF Models",
                published=created,
                snippet=" · ".join(d for d in details if d),
                score=model.get("likes"),
            )
        )
    return items
