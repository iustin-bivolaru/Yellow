"""Registry of source adapters. A source runs only if it is implemented and enabled in config."""

from __future__ import annotations

import logging

import httpx

from yellow.config import Config
from yellow.sources.abstract_source import Source
from yellow.sources.arxiv import ArxivSource
from yellow.sources.github_trending import GithubTrendingSource
from yellow.sources.hackernews import HackerNewsSource
from yellow.sources.huggingface import HuggingFaceSource
from yellow.sources.reddit import RedditSource
from yellow.sources.rss import RssSource
from yellow.sources.x import XSource

log = logging.getLogger(__name__)

REGISTRY: dict[str, type[Source]] = {
    cls.name: cls
    for cls in (
        HackerNewsSource,
        RedditSource,
        ArxivSource,
        HuggingFaceSource,
        GithubTrendingSource,
        XSource,
        RssSource,
    )
}


def enabled_sources(cfg: Config, client: httpx.Client) -> list[Source]:
    """Instantiate every source that is enabled in config and implemented."""
    sources: list[Source] = []
    for name in type(cfg.sources).model_fields:
        if not cfg.source_enabled(name):
            continue
        cls = REGISTRY.get(name)
        if cls is None:
            log.warning("source %s is enabled but not implemented yet; skipping", name)
            continue
        sources.append(cls(cfg, client))
    return sources
