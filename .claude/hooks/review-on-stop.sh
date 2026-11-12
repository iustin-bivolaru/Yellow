#!/usr/bin/env bash
# Stop hook: when Claude finishes a turn that left uncommitted code changes,
# run the `code-reviewer` agent in a fresh headless session (no conversation
# context) and feed its findings back to Claude.
set -uo pipefail

input="$(cat)"

# Never recurse (the reviewer's own session) and never loop: after Claude
# addresses one review, the next stop is let through.
[[ -n "${YELLOW_REVIEW_RUNNING:-}" ]] && exit 0
[[ "$(jq -r '.stop_hook_active // false' <<<"$input")" == "true" ]] && exit 0

cd "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}" || exit 0
git rev-parse --verify -q HEAD >/dev/null || exit 0

# Changed code files only (tracked + untracked), ignoring tooling/state/output.
changed="$(git status --porcelain -uall \
  | sed -E 's/^.{3}//; s/.* -> //' \
  | grep -Ev '^(\.claude/|\.idea/|\.venv/|data/|site/)' \
  | grep -E '\.(py|html|j2|css|js|json|ya?ml|toml|sh|cfg|ini)$' || true)"
[[ -z "$changed" ]] && exit 0

# Skip if this exact state was already reviewed.
state_dir=".claude/.review-state"; mkdir -p "$state_dir"
hash="$( { git diff HEAD -- $changed 2>/dev/null; while IFS= read -r f; do [[ -f "$f" ]] && cat "$f"; done <<<"$changed"; } | shasum | cut -d' ' -f1)"
[[ "$hash" == "$(cat "$state_dir/last-hash" 2>/dev/null)" ]] && exit 0

review="$(YELLOW_REVIEW_RUNNING=1 claude -p \
  --agent code-reviewer \
  --permission-mode dontAsk \
  --allowedTools "Read" "Grep" "Glob" \
    "Bash(git diff*)" "Bash(git status*)" "Bash(git ls-files*)" "Bash(git log*)" "Bash(git show*)" \
    "Bash(ls*)" "Bash(pytest*)" "Bash(ruff check*)" \
  --disallowedTools "Edit" "Write" "NotebookEdit" \
  --no-session-persistence \
  "Review the uncommitted changes in this repository." 2>&1)"
rc=$?

if [[ $rc -ne 0 || -z "$review" ]]; then
  jq -n --arg m "code-reviewer could not run (exit $rc): ${review:0:300}" '{systemMessage:$m}'
  exit 0
fi

echo "$hash" > "$state_dir/last-hash"
printf '%s\n' "$review" > "$state_dir/last-review.md"

if grep -q 'VERDICT: PASS' <<<"$review"; then
  jq -n '{systemMessage:"code-reviewer: PASS ✅"}'
  exit 0
fi

# Exit 2 → stderr goes back to Claude, which keeps working on the findings.
{
  echo "An independent code-reviewer (no context about this conversation) reviewed the uncommitted changes."
  echo "Address every blocker/major finding, or explain to the user why a finding is wrong. Full review: $state_dir/last-review.md"
  echo
  echo "$review"
} >&2
exit 2
