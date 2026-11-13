"""Technology registry: first-seen / trending tracking, stored in data/tech_registry.json.

The registry maps a slug to a `Technology`. All functions are pure except load/save.
`update_registry` is idempotent for a same-day rerun: that day's counts are overwritten, not added.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from datetime import date, timedelta
from pathlib import Path

from yellow.config import RegistryConfig
from yellow.models import Digest, Technology, TechRef

log = logging.getLogger(__name__)

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
# Symbols that tell technologies apart ("C", "C++", "C#", ".NET"), spelled out before stripping.
_SYMBOLS = (("+", " plus "), ("#", " sharp "))


def slugify(name: str) -> str:
    """URL-safe slug: ascii-folded, lowercase, runs of non-alphanumerics become one "-".

    "+", "#" and a leading "." are spelled out, so "C++", "C#" and ".NET" stay distinct
    ("c-plus-plus", "c-sharp", "dot-net").

    Names with no ascii alphanumerics (e.g. CJK) fall back to "t-" + a short sha1 of the name.
    """
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    text = folded.strip().lower()
    if text.startswith("."):
        text = "dot " + text[1:]
    for symbol, word in _SYMBOLS:
        text = text.replace(symbol, word)
    slug = _NON_ALNUM_RE.sub("-", text).strip("-")
    if slug:
        return slug
    return "t-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]


def load_registry(path: Path) -> dict[str, Technology]:
    """Load data/tech_registry.json. Missing: empty; corrupt: logged, empty."""
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("top level is not an object")
        return {slug: Technology.model_validate(t) for slug, t in raw.items()}
    except (OSError, ValueError) as e:
        log.warning("could not read %s (%s); starting with an empty registry", path, e)
        return {}


def save_registry(path: Path, registry: dict[str, Technology]) -> None:
    """Write atomically; sort_keys orders slugs and dates so the daily diff stays small."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {slug: tech.model_dump(mode="json") for slug, tech in registry.items()}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _mentions(digest: Digest) -> dict[str, tuple[str, list[str]]]:
    """Per slug: first-seen spelling and the ids of the digest items that mention it (once each)."""
    out: dict[str, tuple[str, list[str]]] = {}
    for item in digest.items:
        for name in item.technologies:
            name = name.strip()
            if not name:
                continue
            slug = slugify(name)
            _, ids = out.setdefault(slug, (name, []))
            if item.id not in ids:
                ids.append(item.id)
    return out


def update_registry(registry: dict[str, Technology], digest: Digest) -> dict[str, Technology]:
    """Return a new registry with `digest`'s day applied; the input is not modified.

    The day's counts and item ids are overwritten (so reruns are idempotent), removed from
    technologies the digest no longer mentions, and technologies left without counts are dropped.
    """
    day = digest.date.isoformat()
    mentions = _mentions(digest)
    out: dict[str, Technology] = {}
    for slug in registry.keys() | mentions.keys():
        tech = registry[slug].model_copy(deep=True) if slug in registry else None
        if slug in mentions:
            name, ids = mentions[slug]
            if tech is None:
                tech = Technology(
                    name=name, slug=slug, first_seen=digest.date, last_seen=digest.date
                )
            tech.counts[day] = len(ids)
            tech.items[day] = ids
        elif tech is not None:
            tech.counts.pop(day, None)
            tech.items.pop(day, None)
        if tech is None or not tech.counts:
            continue
        dates = [date.fromisoformat(d) for d in tech.counts]
        tech.first_seen, tech.last_seen = min(dates), max(dates)
        out[slug] = tech
    return out


def _ref_sort_key(ref: TechRef) -> tuple[int, str]:
    """Sort by mentions descending, then name."""
    return (-ref.count_today, ref.name.casefold())


def annotate_digest(digest: Digest, registry: dict[str, Technology], cfg: RegistryConfig) -> Digest:
    """Return a copy of `digest` with `new_tech` and `trending_tech` filled from the registry.

    Trending: not new, at least `trending_min_count` mentions today, and at least
    `trending_factor` times the average daily count over the `trending_window_days` days
    before the digest date (missing days count as 0).
    """
    day = digest.date
    window = [(day - timedelta(days=n)).isoformat() for n in range(1, cfg.trending_window_days + 1)]
    new: list[TechRef] = []
    trending: list[TechRef] = []
    for slug, tech in registry.items():
        today = tech.counts.get(day.isoformat(), 0)
        if today <= 0:
            continue
        ref = TechRef(name=tech.name, slug=slug, count_today=today)
        if tech.first_seen == day:
            new.append(ref)
            continue
        average = sum(tech.counts.get(d, 0) for d in window) / cfg.trending_window_days
        if today >= cfg.trending_min_count and today >= cfg.trending_factor * average:
            trending.append(ref)
    return digest.model_copy(
        update={
            "new_tech": sorted(new, key=_ref_sort_key)[: cfg.max_new],
            "trending_tech": sorted(trending, key=_ref_sort_key)[: cfg.max_trending],
        }
    )


def known_names(registry: dict[str, Technology]) -> list[str]:
    """Technology names ordered by total mentions descending, then name."""
    techs = sorted(registry.values(), key=lambda t: (-sum(t.counts.values()), t.name.casefold()))
    return [t.name for t in techs]
