"""Registry of source adapters. A source runs only if it is implemented and enabled in config."""

from __future__ import annotations

import logging

import httpx

from yellow.config import Config
from yellow.sources.base import Source
from yellow.sources.hackernews import HackerNewsSource
from yellow.sources.rss import RssSource

log = logging.getLogger(__name__)

REGISTRY: dict[str, type[Source]] = {
    HackerNewsSource.name: HackerNewsSource,
    RssSource.name: RssSource,
}


def enabled_sources(cfg: Config, client: httpx.Client) -> list[Source]:
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
