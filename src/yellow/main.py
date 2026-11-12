"""CLI entry point: python -m yellow run [--dry-run] [--no-llm]. Wired up in build step 8."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    print("yellow: the CLI is not implemented yet (build step 8)", file=sys.stderr)
    return 2
