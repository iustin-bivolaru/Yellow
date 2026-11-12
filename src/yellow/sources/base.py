"""Base class for news sources.

Adapters implement `_fetch(since)`. Callers use `fetch(since)`, which never raises: a failing
source logs a warning and returns [] so one broken feed can't break the daily run.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime

import httpx

from yellow.config import Config
from yellow.models import Item

log = logging.getLogger(__name__)


def make_client(cfg: Config) -> httpx.Client:
    """Shared HTTP client: generic User-Agent, timeout, redirects followed."""
    return httpx.Client(
        headers={"User-Agent": cfg.http.user_agent},
        timeout=cfg.http.timeout_seconds,
        follow_redirects=True,
    )


class Source(ABC):
    name: str  # machine name, matches the key under `sources:` in config.yaml

    def __init__(self, cfg: Config, client: httpx.Client) -> None:
        self.cfg = cfg
        self.client = client

    @abstractmethod
    def _fetch(self, since: datetime) -> list[Item]:
        """Return items published at or after `since` (UTC). May raise."""

    def fetch(self, since: datetime) -> list[Item]:
        try:
            items = self._fetch(since)
        except Exception as e:  # a source must never break the run
            log.warning("source %s failed: %s: %s", self.name, type(e).__name__, e)
            return []
        log.info("source %s: %d items", self.name, len(items))
        return items
