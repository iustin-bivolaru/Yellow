"""Collect items from all sources, drop duplicates and anything shown on a previous day.

data/seen.json remembers what was already published, by item id and by normalized title, so a
story re-posted under a different URL doesn't come back. Entries expire after
`caps.seen_retention_days`. The seen file is only updated by `mark_seen` + `save_seen`, which the
CLI calls after a digest was built successfully.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, Field

from yellow.models import Item
from yellow.sources.base import Source

log = logging.getLogger(__name__)

_NON_ALNUM_RE = re.compile(r"[\W_]+", re.UNICODE)
_TITLE_PREFIX_RE = re.compile(r"^(show|ask|launch|tell) hn\s*:\s*", re.IGNORECASE)
_MIN_TITLE_KEY_LEN = 12  # very short titles ("Update", "v2.0") are too generic to dedupe on


class Seen(BaseModel):
    """Contents of data/seen.json: key -> local date it was first published."""

    ids: dict[str, date] = Field(default_factory=dict)
    titles: dict[str, date] = Field(default_factory=dict)


def title_key(title: str) -> str | None:
    """Short hash of a normalized title, or None if the title is too short to be distinctive."""
    t = _TITLE_PREFIX_RE.sub("", unicodedata.normalize("NFKC", title).strip())
    norm = _NON_ALNUM_RE.sub(" ", t.casefold()).strip()
    if len(norm) < _MIN_TITLE_KEY_LEN:
        return None
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:12]


def fetch_all(sources: Sequence[Source], since: datetime) -> list[Item]:
    """Run every source concurrently. Source.fetch never raises, so one bad source can't hurt."""
    if not sources:
        return []
    with ThreadPoolExecutor(max_workers=min(8, len(sources))) as pool:
        results = list(pool.map(lambda s: s.fetch(since), sources))
    return [item for batch in results for item in batch]


def _rank(item: Item) -> tuple[int, int, int]:
    """Which copy of a duplicate to keep: highest score, then has a snippet, then has comments.

    Scores come from different scales (HN points, upvotes, stars); this only decides which
    source's copy is shown, so the rough comparison is fine.
    """
    return (item.score or 0, item.snippet is not None, item.discussion_url is not None)


def dedupe(items: Iterable[Item]) -> list[Item]:
    """Merge items that share an id (same canonical URL) or a normalized title.

    Merging is transitive (union-find), so A~B by URL and B~C by title end up as one story.
    The best-ranked copy wins; a missing snippet / discussion link is filled from the others.
    Order of first appearance is preserved.
    """
    items = list(items)
    parent = list(range(len(items)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    owner: dict[str, int] = {}
    for i, item in enumerate(items):
        keys = [f"id:{item.id}"]
        if tk := title_key(item.title):
            keys.append(f"t:{tk}")
        for k in keys:
            if k in owner:
                a, b = find(owner[k]), find(i)
                parent[max(a, b)] = min(a, b)  # smallest index is root: keeps first-seen order
            else:
                owner[k] = i

    grouped: dict[int, list[Item]] = {}
    for i, item in enumerate(items):
        grouped.setdefault(find(i), []).append(item)
    groups = [grouped[r] for r in sorted(grouped)]

    merged: list[Item] = []
    for group in groups:
        best = max(group, key=_rank)
        update: dict[str, object] = {}
        if best.snippet is None:
            update["snippet"] = next((i.snippet for i in group if i.snippet), None)
        if best.discussion_url is None:
            update["discussion_url"] = next(
                (i.discussion_url for i in group if i.discussion_url), None
            )
        merged.append(best.model_copy(update=update) if update else best)
    return merged


def filter_seen(items: Iterable[Item], seen: Seen, today: date) -> list[Item]:
    """Drop items whose id or normalized title was published on a day before `today`.

    Items first published today are kept, so a second run on the same day (manual dispatch,
    retry) rebuilds the same digest instead of an empty one.
    """
    fresh: list[Item] = []
    for item in items:
        tk = title_key(item.title)
        id_day = seen.ids.get(item.id)
        title_day = seen.titles.get(tk) if tk is not None else None
        if (id_day and id_day < today) or (title_day and title_day < today):
            continue
        fresh.append(item)
    return fresh


def mark_seen(seen: Seen, items: Iterable[Item], day: date) -> Seen:
    """Return a copy of `seen` with `items` recorded as published on `day` (keeps earlier dates)."""
    out = seen.model_copy(deep=True)
    for item in items:
        out.ids.setdefault(item.id, day)
        if tk := title_key(item.title):
            out.titles.setdefault(tk, day)
    return out


def prune_seen(seen: Seen, today: date, retention_days: int) -> Seen:
    """Forget entries older than `retention_days` before `today`."""
    cutoff = today - timedelta(days=retention_days)
    return Seen(
        ids={k: d for k, d in seen.ids.items() if d >= cutoff},
        titles={k: d for k, d in seen.titles.items() if d >= cutoff},
    )


def load_seen(path: Path) -> Seen:
    """Load data/seen.json. A missing file is empty; a corrupt one is logged and ignored."""
    if not path.exists():
        return Seen()
    try:
        return Seen.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError as e:
        log.warning("could not read %s (%s); starting with an empty seen list", path, e)
        return Seen()


def save_seen(path: Path, seen: Seen) -> None:
    """Write atomically, with sorted keys so the committed diff stays small."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "ids": {k: seen.ids[k].isoformat() for k in sorted(seen.ids)},
        "titles": {k: seen.titles[k].isoformat() for k in sorted(seen.titles)},
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


def collect(sources: Sequence[Source], since: datetime, seen: Seen, today: date) -> list[Item]:
    """Fetch, dedupe and drop already-published items. Newest first."""
    raw = fetch_all(sources, since)
    unique = dedupe(raw)
    fresh = filter_seen(unique, seen, today)
    log.info("collected %d items: %d after dedupe, %d new", len(raw), len(unique), len(fresh))
    return sorted(fresh, key=lambda i: i.published, reverse=True)
