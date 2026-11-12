#!/usr/bin/env bash
# PostToolUse (Edit|Write): format + autofix the edited .py file with ruff.
# Deterministic and free (no model tokens). Remaining lint errors go back to Claude (exit 2).
set -uo pipefail

f="$(jq -r '.tool_response.filePath // .tool_input.file_path // empty')"
[[ "$f" == *.py && -f "$f" ]] || exit 0

root="${CLAUDE_PROJECT_DIR:-.}"
ruff="$root/.venv/bin/ruff"
[[ -x "$ruff" ]] || exit 0

"$ruff" format -q "$f" >/dev/null 2>&1
"$ruff" check -q --fix "$f" >/dev/null 2>&1
if ! out="$("$ruff" check -q --output-format concise "$f" 2>&1)"; then
  echo "ruff found issues it could not auto-fix in $f:" >&2
  echo "$out" | head -20 >&2
  exit 2
fi
exit 0
