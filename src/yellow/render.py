"""Render the static PWA into site/ from digests and the technology registry.

Also persists digests (data/digests/YYYY-MM-DD.json). Templates live in the repo's `templates/`.
All links in the generated pages are relative, so the site works from a GitHub Pages subpath.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import struct
import zlib
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from yellow.config import Config
from yellow.models import Digest, DigestItem, Technology
from yellow.tech_registry import slugify

log = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parents[2] / "templates"
_STATIC_FILES = ("style.css", "app.js", "icon.svg")
_SAFE_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_YELLOW_RGB = (0xFF, 0xD4, 0x00)
_INK_RGB = (0x1A, 0x1A, 0x1A)


# --- persistence ---------------------------------------------------------------------------


def save_digest(dir: Path, digest: Digest) -> Path:
    """Write `digest` atomically to `dir/YYYY-MM-DD.json` and return the path."""
    dir.mkdir(parents=True, exist_ok=True)
    path = dir / f"{digest.date.isoformat()}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(digest.model_dump_json(indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def load_digests(dir: Path, limit: int = 30) -> list[Digest]:
    """Load up to `limit` digests from `dir`, newest first. Corrupt files are logged and skipped."""
    if not dir.is_dir():
        return []
    out: list[Digest] = []
    for path in sorted(dir.glob("????-??-??.json"), reverse=True):
        if len(out) >= limit:
            break
        try:
            out.append(Digest.model_validate_json(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            log.warning("could not read %s (%s); skipping", path, e)
    return sorted(out, key=lambda d: d.date, reverse=True)


# --- helpers -------------------------------------------------------------------------------


def _env(cfg: Config) -> Environment:
    """Jinja environment: autoescape on, strict undefined, plus the local-time filter."""
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=True,
        undefined=StrictUndefined,
    )

    def localtime(value: datetime, day: date | None = None) -> str:
        """Format a UTC datetime in the configured timezone; add the date unless it is `day`."""
        local = value.astimezone(cfg.tz)
        return local.strftime("%H:%M" if local.date() == day else "%d %b %H:%M")

    env.filters["localtime"] = localtime
    env.globals["slugify"] = slugify
    return env


def _write(path: Path, text: str) -> None:
    """Write a UTF-8 text file, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _importance_order(item: DigestItem) -> tuple[int, int]:
    """Sort key: importance descending, then score descending (missing score counts as 0)."""
    return (-item.importance, -(item.score or 0))


def _categories(digest: Digest, cfg: Config) -> list[str]:
    """Categories present in the digest, in config order, then any unknown ones sorted."""
    present = {i.category for i in digest.items}
    known = [c for c in cfg.categories if c in present]
    return known + sorted(present - set(known))


def _tech_stories(
    tech: Technology, by_day: dict[str, dict[str, DigestItem]]
) -> list[dict[str, Any]]:
    """Stories that mention `tech` among the given digests, newest day first."""
    stories: list[dict[str, Any]] = []
    for day in sorted(tech.items, reverse=True):
        found = [by_day[day][i] for i in tech.items[day] if i in by_day.get(day, {})]
        found.sort(key=lambda it: it.published, reverse=True)
        stories.extend({"day": day, "item": it} for it in found)
    return stories


def _png(size: int) -> bytes:
    """A square yellow PNG with a dark ring in the middle, built with stdlib only."""
    mid = (size - 1) / 2
    outer, inner = (0.30 * size) ** 2, (0.14 * size) ** 2
    yellow, ink = bytes(_YELLOW_RGB), bytes(_INK_RGB)
    raw = bytearray()
    for y in range(size):
        raw.append(0)  # filter type: none
        dy2 = (y - mid) ** 2
        for x in range(size):
            d2 = dy2 + (x - mid) ** 2
            raw += ink if inner < d2 <= outer else yellow

    def chunk(tag: bytes, data: bytes) -> bytes:
        """One PNG chunk: length, tag, data, CRC."""
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def _manifest(cfg: Config) -> str:
    """The web app manifest as JSON text."""
    manifest = {
        "name": cfg.site.title,
        "short_name": cfg.site.title,
        "description": "Daily AI and IT news digest",
        "start_url": "./",
        "scope": "./",
        "display": "standalone",
        "theme_color": "#FFD400",
        "background_color": "#FFFDF5",
        "icons": [
            {"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "icon.svg", "sizes": "any", "type": "image/svg+xml"},
        ],
    }
    return json.dumps(manifest, indent=2) + "\n"


def _remove(path: Path) -> None:
    """Delete a generated subdirectory. A symlink is unlinked, never followed; errors raise."""
    if path.is_symlink():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _templates_hash() -> str:
    """Short hash of every file in templates/, so a code-only redeploy gets a new SW cache."""
    h = hashlib.sha1()
    for f in sorted(TEMPLATES_DIR.rglob("*")):
        if f.is_file():
            h.update(f.relative_to(TEMPLATES_DIR).as_posix().encode())
            h.update(f.read_bytes())
    return h.hexdigest()[:8]


# --- main entry point ----------------------------------------------------------------------


def render_site(
    out_dir: Path,
    digests: Sequence[Digest],
    registry: dict[str, Technology],
    cfg: Config,
) -> None:
    """Build the whole site in `out_dir`. `digests[0]` is today; the rest is the archive.

    Only the files this function writes plus the `day/` and `tech/` subdirectories are removed
    first, so nothing else in `out_dir` is ever deleted.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for sub in ("day", "tech"):
        _remove(out_dir / sub)

    env = _env(cfg)
    base: dict[str, Any] = {"cfg": cfg, "site_title": cfg.site.title}

    by_day = {d.date.isoformat(): {i.id: i for i in d.items} for d in digests}
    tech_pages = {
        slug: (tech, stories)
        for slug, tech in registry.items()
        if _SAFE_SLUG_RE.match(slug) and (stories := _tech_stories(tech, by_day))
    }
    tech_slugs = set(tech_pages)
    archive = [d.date.isoformat() for d in digests]

    if digests:
        digest_tpl = env.get_template("digest.html")
        for n, digest in enumerate(digests):
            items = sorted(digest.items, key=_importance_order)
            by_id = {i.id: i for i in digest.items}
            top = [by_id[i] for i in digest.top5 if i in by_id][:5]
            for root, path, is_today in ([("", out_dir / "index.html", True)] if n == 0 else []) + [
                ("../", out_dir / "day" / f"{digest.date.isoformat()}.html", False)
            ]:
                _write(
                    path,
                    digest_tpl.render(
                        **base,
                        digest=digest,
                        root=root,
                        is_today=is_today,
                        top=top,
                        feed=items,
                        categories=_categories(digest, cfg),
                        tech_slugs=tech_slugs,
                        archive=archive,
                    ),
                )
    else:
        _write(out_dir / "index.html", env.get_template("empty.html").render(**base, root=""))

    tech_tpl = env.get_template("tech.html")
    for slug, (tech, stories) in tech_pages.items():
        _write(
            out_dir / "tech" / f"{slug}.html",
            tech_tpl.render(
                **base,
                root="../",
                tech=tech,
                stories=stories,
                total=sum(tech.counts.values()),
                archive=archive,
            ),
        )

    stamp = digests[0].generated_at.strftime("%Y%m%d%H%M%S") if digests else "empty"
    stamp += "-" + _templates_hash()  # a CSS/JS/template change also renews the SW cache
    _write(
        out_dir / "sw.js",
        env.get_template("sw.js").render(cache_id=stamp, pages=[f"day/{d}.html" for d in archive]),
    )
    _write(out_dir / "manifest.json", _manifest(cfg))
    for name in _STATIC_FILES:
        shutil.copyfile(TEMPLATES_DIR / name, out_dir / name)
    for size in (192, 512):
        (out_dir / f"icon-{size}.png").write_bytes(_png(size))
    log.info(
        "rendered %d digest(s) and %d tech page(s) to %s", len(digests), len(tech_pages), out_dir
    )
