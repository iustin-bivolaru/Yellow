"""Core data models (DTOs). All datetimes are timezone-aware UTC.

Field descriptions double as documentation and as the JSON-schema descriptions Claude sees
for the models used as structured output (ItemAnalysis).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, BeforeValidator, Field

from yellow.config import FALLBACK_CATEGORY
from yellow.text import is_http_url


def _to_utc(v: datetime) -> datetime:
    """Naive datetimes are taken as UTC; aware ones are converted to UTC."""
    return v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC)


def _clamp_importance(v: object) -> object:
    """Coerce to int and clamp to 1..5, so one odd LLM value can't sink the whole digest.

    Values that aren't numbers at all are passed through for normal validation to reject.
    """
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float, str)):
        try:
            n = int(float(v))
        except (ValueError, OverflowError):
            return v
        return max(1, min(5, n))
    return v


def _http_only(v: str | None) -> str | None:
    if v is not None and not is_http_url(v):
        raise ValueError("only absolute http(s) URLs are allowed")
    return v


UtcDatetime = Annotated[datetime, AfterValidator(_to_utc)]
HttpUrlStr = Annotated[str, AfterValidator(_http_only)]
Importance = Annotated[int, BeforeValidator(_clamp_importance)]


def item_id(canonical_url: str) -> str:
    """Stable short id derived from the canonical URL."""
    return hashlib.sha1(canonical_url.encode("utf-8")).hexdigest()[:12]


class Item(BaseModel):
    """A raw news item as collected from a source."""

    id: Annotated[str, Field(description="Stable 12-char id: sha1 of the canonical URL.")]
    title: Annotated[str, Field(description="Headline as published by the source (untrusted).")]
    url: Annotated[HttpUrlStr, Field(description="Link to the story itself (http/https only).")]
    source: Annotated[
        str, Field(description='Machine name of the adapter, e.g. "hackernews", "reddit", "rss".')
    ]
    source_name: Annotated[
        str, Field(description='Display name, e.g. "Hacker News", "r/LocalLLaMA", "Anthropic".')
    ]
    published: Annotated[
        UtcDatetime, Field(description="Publication time, normalized to UTC (naive = UTC).")
    ]
    snippet: Annotated[
        str | None, Field(description="Short plain-text excerpt or description, if any.")
    ] = None
    score: Annotated[
        int | None, Field(description="Points / upvotes / stars, when the source has them.")
    ] = None
    discussion_url: Annotated[
        HttpUrlStr | None, Field(description="Comments page (HN thread, Reddit post), if separate.")
    ] = None


class ItemAnalysis(BaseModel):
    """What the analyzer (Claude or keyword fallback) says about one item."""

    id: Annotated[str, Field(description="Id of the analyzed item, copied from the input.")]
    category: Annotated[str, Field(description="Exactly one category from the configured list.")]
    summary: Annotated[str, Field(description="Neutral 1-2 sentence summary of the story.")]
    importance: Annotated[
        Importance,
        Field(description="How much this matters to an AI/IT reader: 1 (minor) to 5 (major)."),
    ]
    technologies: Annotated[
        list[str],
        Field(
            default_factory=list,
            description="Named technologies, models, libraries or products mentioned, "
            "in canonical form (reuse registry names when they match).",
        ),
    ]


class DigestItem(Item):
    """An item enriched with its analysis, as rendered."""

    category: Annotated[str, Field(description="Assigned category.")] = FALLBACK_CATEGORY
    summary: Annotated[
        str | None, Field(description="1-2 sentence summary; None if not analyzed.")
    ] = None
    importance: Annotated[Importance, Field(description="1 (minor) to 5 (major).")] = 1
    technologies: Annotated[
        list[str], Field(default_factory=list, description="Canonical technology names.")
    ]


class TechRef(BaseModel):
    """A technology as shown on a digest page (chip / tag)."""

    name: Annotated[str, Field(description='Canonical display name, e.g. "Llama 4".')]
    slug: Annotated[str, Field(description="URL-safe id used for the tech page path.")]
    count_today: Annotated[int, Field(description="Mentions in today's digest.")] = 0


class Digest(BaseModel):
    """One day's digest. Persisted to data/digests/YYYY-MM-DD.json."""

    date: Annotated[date, Field(description="Digest date in the configured local timezone.")]
    generated_at: Annotated[UtcDatetime, Field(description="When the digest was built (UTC).")]
    analyzer: Annotated[
        str, Field(description='Model id that produced the analysis, or "keyword-fallback".')
    ]
    nutshell: Annotated[str, Field(description='Three-sentence "AI in a nutshell" intro.')]
    top5: Annotated[
        list[str], Field(default_factory=list, description="Ids of the five most important items.")
    ]
    items: Annotated[
        list[DigestItem], Field(default_factory=list, description="All items in the digest.")
    ]
    new_tech: Annotated[
        list[TechRef],
        Field(default_factory=list, description="Technologies first seen today (New on radar)."),
    ]
    trending_tech: Annotated[
        list[TechRef],
        Field(default_factory=list, description="Technologies at >= 2x their 7-day average."),
    ]


class Technology(BaseModel):
    """One entry in data/tech_registry.json."""

    name: Annotated[str, Field(description="Canonical display name.")]
    slug: Annotated[str, Field(description="URL-safe id, unique in the registry.")]
    first_seen: Annotated[date, Field(description="Local date of the first mention.")]
    last_seen: Annotated[date, Field(description="Local date of the latest mention.")]
    counts: Annotated[
        dict[str, int],
        Field(default_factory=dict, description='Mentions per local day, keyed "YYYY-MM-DD".'),
    ]
    items: Annotated[
        list[str], Field(default_factory=list, description="Ids of items that mentioned it.")
    ]
