"""X/Twitter: a disabled stub. X's read API is paid, so this source stays off.

config.py refuses `sources.x.enabled: true` unless X_BEARER_TOKEN is set. Implement `_fetch`
here (X API v2 recent search) when the user decides to pay for access.
"""

from __future__ import annotations

import logging
from datetime import datetime

from yellow.models import Item
from yellow.sources.abstract_source import Source

log = logging.getLogger(__name__)


class XSource(Source):
    """Placeholder for X/Twitter; always returns no items."""

    name = "x"

    def _fetch(self, since: datetime) -> list[Item]:
        """Return [] with a warning: the X adapter is not implemented."""
        log.warning("source x is enabled but not implemented (paid API); returning no items")
        return []
