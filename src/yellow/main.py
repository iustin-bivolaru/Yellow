"""CLI entry point: `python -m yellow run [--dry-run] [--no-llm] [--scheduled]`.

`run` wires the pipeline: collect -> analyze -> registry -> render -> save state. State
(digest, registry, seen) is written only after the site rendered, and never on `--dry-run`.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from yellow.analyze import KEYWORD_ANALYZER, analyze
from yellow.collect import collect, load_seen, mark_seen, prune_seen, save_seen
from yellow.config import Config, load_config, project_root
from yellow.models import Digest
from yellow.render import load_digests, render_site, save_digest
from yellow.sources import enabled_sources
from yellow.sources.abstract_source import Source, make_client
from yellow.tech_registry import (
    annotate_digest,
    known_names,
    load_registry,
    save_registry,
    update_registry,
)

log = logging.getLogger("yellow")


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for the CLI."""
    parser = argparse.ArgumentParser(prog="yellow", description="Daily AI/IT news digest.")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="collect, analyze, render and save state")
    run_p.add_argument("--dry-run", action="store_true", help="write site/ only, not data/")
    run_p.add_argument("--no-llm", action="store_true", help="keyword-only digest, no API call")
    run_p.add_argument(
        "--scheduled",
        action="store_true",
        help="exit early before run_hour locally or when today's digest exists",
    )
    run_p.add_argument("--data-dir", type=Path, default=None, help="default: <repo>/data")
    run_p.add_argument("--site-dir", type=Path, default=None, help="default: <repo>/site")
    return parser


def run(
    *,
    data_dir: Path,
    site_dir: Path,
    dry_run: bool = False,
    use_llm: bool = True,
    scheduled: bool = False,
    cfg: Config | None = None,
    now: datetime | None = None,
    sources: Sequence[Source] | None = None,
    client: Any = None,
) -> int:
    """Run the whole pipeline once and return the exit code (0 on success).

    Args:
        data_dir: Directory holding seen.json, tech_registry.json and digests/.
        site_dir: Output directory for the rendered site.
        dry_run: Skip every write under `data_dir`.
        use_llm: False for the keyword-only digest.
        scheduled: Apply the run-hour gate (skip before run_hour or when today's digest exists).
        cfg: Config; loaded from config.yaml when None.
        now: Current UTC time (injectable for tests).
        sources: Sources to use; the enabled ones from config when None.
        client: Anthropic client passed to `analyze` (api backend only).
    """
    cfg = cfg or load_config()
    now = now or datetime.now(UTC)
    local = now.astimezone(cfg.tz)
    today: date = local.date()
    digests_dir = data_dir / "digests"
    digest_path = digests_dir / f"{today.isoformat()}.json"

    if scheduled and (local.hour < cfg.run_hour or digest_path.exists()):
        why = "digest already exists" if digest_path.exists() else "before run_hour"
        log.info("scheduled run skipped: %s (local %s, run_hour %d)", why, local, cfg.run_hour)
        return 0

    existing = _load_today(digest_path)
    seen = load_seen(data_dir / "seen.json")
    registry = load_registry(data_dir / "tech_registry.json")

    with make_client(cfg) as http:
        items = collect(
            sources if sources is not None else enabled_sources(cfg, http),
            now - timedelta(hours=cfg.caps.lookback_hours),
            seen,
            today=today,
        )

    digest: Digest | None
    save_state = False
    if not items:
        digest = existing
        if existing:
            log.warning("nothing collected; keeping the existing digest for %s", today)
        else:
            log.warning("nothing collected and no digest for %s; nothing saved, retry later", today)
    else:
        digest = analyze(
            items,
            cfg,
            day=today,
            now=now,
            known_tech=known_names(registry),
            use_llm=use_llm,
            client=client,
        )
        if (
            existing
            and existing.analyzer != KEYWORD_ANALYZER
            and digest.analyzer == KEYWORD_ANALYZER
        ):
            log.warning(
                "keyword fallback would replace the %s digest; keeping it", existing.analyzer
            )
            digest = existing
        else:
            registry = update_registry(registry, digest)
            digest = annotate_digest(digest, registry, cfg.registry)
            save_state = not dry_run

    archive = [d for d in load_digests(digests_dir, cfg.site.archive_days) if d.date != today]
    digests = ([digest] if digest else []) + archive
    render_site(site_dir, digests[: cfg.site.archive_days], registry, cfg)

    if save_state and digest:
        # The digest goes last: its file is the "done" marker the scheduled gate checks.
        save_registry(data_dir / "tech_registry.json", registry)
        seen = prune_seen(mark_seen(seen, items, today), today, cfg.caps.seen_retention_days)
        save_seen(data_dir / "seen.json", seen)
        save_digest(digests_dir, digest)

    if digest is None:
        return 0
    log.info(
        "digest %s: %d items, %d categories, %d new tech, %d trending, analyzer=%s%s",
        today,
        len(digest.items),
        len({i.category for i in digest.items}),
        len(digest.new_tech),
        len(digest.trending_tech),
        digest.analyzer,
        " (dry run, nothing saved)" if dry_run else "",
    )
    return 0


def _load_today(path: Path) -> Digest | None:
    """Load today's saved digest; a missing or corrupt file counts as no digest."""
    if not path.is_file():
        return None
    try:
        return Digest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.warning("could not read %s (%s); treating it as missing", path, e)
        return None


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, run the command and return the process exit code (0, 1 or 2)."""
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request is noise
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as e:  # argparse exits 2 on bad usage, 0 on --help
        return e.code if isinstance(e.code, int) else 2
    root = project_root()
    try:
        return run(
            data_dir=args.data_dir or root / "data",
            site_dir=args.site_dir or root / "site",
            dry_run=args.dry_run,
            use_llm=not args.no_llm,
            scheduled=args.scheduled,
        )
    except Exception:
        log.exception("run failed")
        return 1
