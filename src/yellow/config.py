"""Load and validate config.yaml. Every model rejects unknown keys, so typos fail loudly."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal
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
    model_config = ConfigDict(extra="forbid")


class SiteConfig(_Strict):
    title: str = "Yellow"
    base_url: str = ""
    archive_days: int = Field(default=30, gt=0)


class HttpConfig(_Strict):
    user_agent: str = "YellowDigest/0.1 (daily news digest)"
    timeout_seconds: float = Field(default=20, gt=0)


class LLMConfig(_Strict):
    model: str = "claude-haiku-5-5"
    effort: Literal["low", "medium", "high"] = "low"
    max_tokens: int = Field(default=16000, gt=0)
    max_items: int = Field(default=150, gt=0)
    snippet_chars: int = Field(default=300, gt=0)

    @field_validator("model")
    @classmethod
    def no_opus(cls, v: str) -> str:
        if "opus" in v.lower():
            raise ValueError("Opus is not allowed for Yellow; use claude-haiku-5-5 or sonnet")
        return v


class CapsConfig(_Strict):
    lookback_hours: int = Field(default=26, gt=0)
    max_items_per_source: int = Field(default=40, gt=0)
    seen_retention_days: int = Field(default=30, gt=0)


# --- per-source settings -------------------------------------------------------------------


class SourceConfig(_Strict):
    enabled: StrictBool = False  # StrictBool: the string "false" is an error, not truthy


class HackerNewsConfig(SourceConfig):
    min_points: int = Field(default=50, ge=0)


class RedditConfig(SourceConfig):
    subreddits: list[str] = Field(default_factory=list)


class ArxivConfig(SourceConfig):
    categories: list[str] = Field(default_factory=list)
    max_items: int = Field(default=15, gt=0)


class RssFeed(_Strict):
    name: str
    url: str


class RssConfig(SourceConfig):
    feeds: list[RssFeed] = Field(default_factory=list)


class XConfig(SourceConfig):
    @model_validator(mode="after")
    def needs_token(self) -> XConfig:
        if self.enabled and not os.environ.get("X_BEARER_TOKEN"):
            raise ValueError("sources.x is enabled but X_BEARER_TOKEN is not set")
        return self


class SourcesConfig(_Strict):
    """Known sources only: an unknown or misspelled source name is a validation error."""

    hackernews: HackerNewsConfig = Field(default_factory=HackerNewsConfig)
    reddit: RedditConfig = Field(default_factory=RedditConfig)
    arxiv: ArxivConfig = Field(default_factory=ArxivConfig)
    huggingface: SourceConfig = Field(default_factory=SourceConfig)
    github_trending: SourceConfig = Field(default_factory=SourceConfig)
    x: XConfig = Field(default_factory=XConfig)
    rss: RssConfig = Field(default_factory=RssConfig)


# --- top level -----------------------------------------------------------------------------


class Config(_Strict):
    timezone: str
    run_hour: int = Field(default=9, ge=0, le=23)
    site: SiteConfig = Field(default_factory=SiteConfig)
    http: HttpConfig = Field(default_factory=HttpConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    caps: CapsConfig = Field(default_factory=CapsConfig)
    categories: list[str]
    sources: SourcesConfig = Field(default_factory=SourcesConfig)

    @field_validator("timezone")
    @classmethod
    def valid_tz(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError(f"unknown timezone {v!r}") from e
        return v

    @field_validator("categories")
    @classmethod
    def valid_categories(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("categories must be unique")
        if FALLBACK_CATEGORY not in v:
            raise ValueError(f"categories must include the fallback {FALLBACK_CATEGORY!r}")
        return v

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def source_enabled(self, name: str) -> bool:
        return getattr(self.sources, name).enabled


def load_config(path: Path | None = None) -> Config:
    with open(path or project_root() / "config.yaml", encoding="utf-8") as f:
        return Config.model_validate(yaml.safe_load(f))
