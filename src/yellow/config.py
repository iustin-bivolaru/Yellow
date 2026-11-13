"""Load and validate config.yaml. Every model rejects unknown keys, so typos fail loudly."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

FALLBACK_CATEGORY = "Other Tech"


def project_root() -> Path:
    """Repo root: $YELLOW_ROOT if set, else the current working directory.

    Not derived from __file__, so it also works for non-editable installs (CI uses `pip install .`).
    """
    return Path(os.environ.get("YELLOW_ROOT") or Path.cwd()).resolve()


class _Strict(BaseModel):
    """Base for all config models: unknown keys are rejected."""

    model_config = ConfigDict(extra="forbid")


class SiteConfig(_Strict):
    """Settings for the generated site (title, base URL, archive length)."""

    title: Annotated[str, Field(description="Site name shown in the header and manifest.")] = (
        "Yellow"
    )
    base_url: Annotated[
        str, Field(description='Path prefix, e.g. "/<repo-name>/" for a GitHub Pages project site.')
    ] = ""
    archive_days: Annotated[
        int, Field(gt=0, description="How many past days the archive section lists.")
    ] = 30


class HttpConfig(_Strict):
    """Settings for the shared HTTP client used by all sources."""

    user_agent: Annotated[
        str, Field(description="Generic User-Agent sent to every source (no personal info).")
    ] = "YellowDigest/0.1 (daily news digest)"
    timeout_seconds: Annotated[
        float, Field(gt=0, description="Per-request timeout in seconds.")
    ] = 20


class LLMConfig(_Strict):
    """Settings for the single Claude call made by analyze.py."""

    model: Annotated[
        str, Field(description="Claude model id: claude-haiku-5-5 or claude-sonnet-5-5.")
    ] = "claude-haiku-5-5"
    effort: Annotated[
        Literal["low", "medium", "high"], Field(description="Reasoning effort for the call.")
    ] = "low"
    max_tokens: Annotated[int, Field(gt=0, description="Output token limit for the call.")] = 16000
    max_items: Annotated[int, Field(gt=0, description="Most items sent to Claude in one run.")] = (
        150
    )
    snippet_chars: Annotated[
        int, Field(gt=0, description="Snippets are truncated to this length before sending.")
    ] = 300

    @field_validator("model")
    @classmethod
    def no_opus(cls, v: str) -> str:
        """Reject Opus models, which are too expensive for a daily digest."""
        if "opus" in v.lower():
            raise ValueError("Opus is not allowed for Yellow; use claude-haiku-5-5 or sonnet")
        return v


class CapsConfig(_Strict):
    """Limits on how far back sources look and how much data is kept."""

    lookback_hours: Annotated[
        int, Field(gt=0, description="Sources return items published within this many hours.")
    ] = 26
    max_items_per_source: Annotated[
        int, Field(gt=0, description="Most items one source (or one RSS feed) may return.")
    ] = 40
    seen_retention_days: Annotated[
        int, Field(gt=0, description="Days data/seen.json remembers a published item.")
    ] = 30


# --- per-source settings -------------------------------------------------------------------


class SourceConfig(_Strict):
    """Settings common to every source: just the on/off switch."""

    enabled: Annotated[
        StrictBool,  # StrictBool: the string "false" is an error, not truthy
        Field(description="Whether this source runs."),
    ] = False


class HackerNewsConfig(SourceConfig):
    """Hacker News settings: minimum points for a story to be included."""

    min_points: Annotated[
        int, Field(ge=0, description="Stories below this many points are skipped.")
    ] = 50


class RedditConfig(SourceConfig):
    """Reddit settings: which subreddits to read."""

    subreddits: Annotated[
        list[str], Field(default_factory=list, description='Subreddit names without "r/".')
    ]


class ArxivConfig(SourceConfig):
    """arXiv settings: which categories to read and how many papers to keep."""

    categories: Annotated[
        list[str], Field(default_factory=list, description='arXiv categories, e.g. "cs.AI".')
    ]
    max_items: Annotated[int, Field(gt=0, description="Most papers kept per run.")] = 15


class RssFeed(_Strict):
    """One RSS/Atom feed: display name and URL."""

    name: Annotated[str, Field(description="Display name shown as the item's source badge.")]
    url: Annotated[str, Field(description="Feed URL (RSS or Atom).")]


class RssConfig(SourceConfig):
    """RSS settings: the list of feeds to read."""

    feeds: Annotated[
        list[RssFeed], Field(default_factory=list, description="Feeds to read, in any order.")
    ]


class XConfig(SourceConfig):
    """X/Twitter settings. Disabled by default because the API is paid."""

    @model_validator(mode="after")
    def needs_token(self) -> XConfig:
        """Require X_BEARER_TOKEN in the environment when the X source is enabled."""
        if self.enabled and not os.environ.get("X_BEARER_TOKEN"):
            raise ValueError("sources.x is enabled but X_BEARER_TOKEN is not set")
        return self


class SourcesConfig(_Strict):
    """Known sources only: an unknown or misspelled source name is a validation error."""

    hackernews: Annotated[
        HackerNewsConfig, Field(default_factory=HackerNewsConfig, description="Hacker News.")
    ]
    reddit: Annotated[RedditConfig, Field(default_factory=RedditConfig, description="Reddit RSS.")]
    arxiv: Annotated[ArxivConfig, Field(default_factory=ArxivConfig, description="arXiv papers.")]
    huggingface: Annotated[
        SourceConfig,
        Field(default_factory=SourceConfig, description="Hugging Face papers and models."),
    ]
    github_trending: Annotated[
        SourceConfig,
        Field(default_factory=SourceConfig, description="Fast-rising new GitHub AI repos."),
    ]
    x: Annotated[XConfig, Field(default_factory=XConfig, description="X/Twitter (paid; off).")]
    rss: Annotated[RssConfig, Field(default_factory=RssConfig, description="RSS/Atom feeds.")]


# --- top level -----------------------------------------------------------------------------


class Config(_Strict):
    """The whole of config.yaml, validated."""

    timezone: Annotated[str, Field(description="IANA timezone for display and the run-hour gate.")]
    run_hour: Annotated[
        int, Field(ge=0, le=23, description="Local hour at which the scheduled run publishes.")
    ] = 9
    site: Annotated[SiteConfig, Field(default_factory=SiteConfig, description="Site output.")]
    http: Annotated[HttpConfig, Field(default_factory=HttpConfig, description="HTTP client.")]
    llm: Annotated[LLMConfig, Field(default_factory=LLMConfig, description="The Claude call.")]
    caps: Annotated[CapsConfig, Field(default_factory=CapsConfig, description="Limits.")]
    categories: Annotated[
        list[str], Field(description="News categories; must include the fallback category.")
    ]
    sources: Annotated[
        SourcesConfig, Field(default_factory=SourcesConfig, description="Per-source settings.")
    ]

    @field_validator("timezone")
    @classmethod
    def valid_tz(cls, v: str) -> str:
        """Reject timezone names that zoneinfo doesn't know."""
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError(f"unknown timezone {v!r}") from e
        return v

    @field_validator("categories")
    @classmethod
    def valid_categories(cls, v: list[str]) -> list[str]:
        """Require unique categories that include the fallback category."""
        if len(set(v)) != len(v):
            raise ValueError("categories must be unique")
        if FALLBACK_CATEGORY not in v:
            raise ValueError(f"categories must include the fallback {FALLBACK_CATEGORY!r}")
        return v

    @property
    def tz(self) -> ZoneInfo:
        """The configured timezone as a ZoneInfo."""
        return ZoneInfo(self.timezone)

    def source_enabled(self, name: str) -> bool:
        """Return whether the source called `name` is enabled in config."""
        return getattr(self.sources, name).enabled


def load_config(path: Path | None = None) -> Config:
    """Load and validate config.yaml (default: the one at the project root)."""
    with open(path or project_root() / "config.yaml", encoding="utf-8") as f:
        return Config.model_validate(yaml.safe_load(f))
