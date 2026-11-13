#!/usr/bin/env bash
# PreToolUse hook (Bash): no direct commits or pushes to main. Work happens on a task branch,
# goes up as a pull request, and the user merges it. Exit 2 blocks the call and tells Claude why.
set -u

cmd=$(jq -r '.tool_input.command // empty')
[ -z "$cmd" ] && exit 0

# Only git commit / git push (also `git -C dir commit`) are checked.
echo "$cmd" | grep -Eq '(^|[^[:alnum:]_-])git([[:space:]]+-C[[:space:]]+[^[:space:]]+)?[[:space:]]+(commit|push)([[:space:]]|$)' || exit 0

branch=$(git -C "${CLAUDE_PROJECT_DIR:-.}" branch --show-current 2>/dev/null)

if [ "$branch" = "main" ]; then
  echo "Blocked: you are on main. Create a task branch first (git switch -c <type>/<short-name>), commit there, push it and open a PR; the user merges it." >&2
  exit 2
fi

# Pushing straight to main from another branch (git push origin main, HEAD:main, ...).
if echo "$cmd" | grep -Eq 'git([[:space:]]+-C[[:space:]]+[^[:space:]]+)?[[:space:]]+push.*([[:space:]:]|^)main([[:space:]]|$)'; then
  echo "Blocked: pushing to main directly. Push the task branch and open a PR instead; the user merges it." >&2
  exit 2
fi

exit 0
