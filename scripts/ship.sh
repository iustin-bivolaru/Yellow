#!/usr/bin/env bash
# Check and commit the current task branch (local steps only), then print the network commands.
#
# Usage: scripts/ship.sh "<type>(<scope>): <summary>" ["<body>"]
# Env:   SHIP_CHECK_CMD  overrides the check command, only when SHIP_TEST_MODE=1 is also set (tests only).
#        Default: .venv/bin/ruff format --check . && .venv/bin/ruff check . && .venv/bin/pytest -q
# Exit codes: 0 ok, 1 refused or failed, 2 bad usage.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/ship.sh "<type>(<scope>): <summary>" ["<body>"]
  Runs the checks, stages everything, commits, then prints the push and PR commands.
  Env SHIP_CHECK_CMD (with SHIP_TEST_MODE=1) overrides the check command (tests only).
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi
if [[ $# -lt 1 || $# -gt 2 ]]; then
  usage >&2
  exit 2
fi

subject="$1"
body="${2:-}"
cd "$(git rev-parse --show-toplevel)"

branch="$(git branch --show-current)"
if [[ -z "$branch" ]]; then
  echo "error: detached HEAD; switch to a task branch" >&2
  exit 1
fi
if [[ "$branch" == "main" ]]; then
  echo "error: refusing to ship from main; use scripts/new-task.sh first" >&2
  exit 1
fi

type_re='(feat|fix|refactor|perf|test|docs|chore|ci|build)'
if ! [[ "$subject" =~ ^${type_re}(\([a-z0-9-]+\))?!?:\ [a-z0-9] ]]; then
  echo "error: subject must look like 'type(scope): lowercase summary'" >&2
  usage >&2
  exit 2
fi
if [[ "$subject" == *. ]]; then
  echo "error: subject must not end with a period" >&2
  exit 2
fi
if [[ ${#subject} -gt 72 ]]; then
  echo "error: subject is ${#subject} chars (max 72)" >&2
  exit 2
fi
if printf '%s\n%s\n' "$subject" "$body" | grep -Eiq 'co-authored-by|generated with|claude code|noreply@anthropic\.com|🤖'; then
  echo "error: no attribution text allowed (Co-Authored-By, Generated with, Claude Code, noreply@anthropic.com)" >&2
  exit 2
fi

check_cmd=".venv/bin/ruff format --check . && .venv/bin/ruff check . && .venv/bin/pytest -q"
if [[ -n "${SHIP_CHECK_CMD:-}" ]]; then
  if [[ "${SHIP_TEST_MODE:-}" == "1" ]]; then
    check_cmd="$SHIP_CHECK_CMD"
  else
    echo "warning: SHIP_CHECK_CMD ignored (it needs SHIP_TEST_MODE=1)" >&2
  fi
fi
echo "running checks: $check_cmd"
if ! bash -c "$check_cmd"; then
  echo "error: checks failed; nothing committed" >&2
  exit 1
fi

git add -A

while IFS= read -r -d '' path; do
  base="${path##*/}"
  if [[ "$base" == .env* && "$base" != ".env.example" ]]; then
    git reset -q -- "$path"
    echo "error: refusing to commit secret file: $path (unstaged it)" >&2
    exit 1
  fi
done < <(git diff --cached --name-only -z)

if git diff --cached --quiet; then
  ahead=1
  if git rev-parse --verify --quiet origin/main >/dev/null; then
    ahead="$(git rev-list --count origin/main..HEAD)"
  fi
  if [[ "$ahead" -eq 0 ]]; then
    echo "nothing to ship: no changes and no commits ahead of origin/main" >&2
    exit 1
  fi
  echo "nothing new to commit; $ahead commit(s) already ahead of origin/main"
else
  if [[ -n "$body" ]]; then
    git commit -q -m "$subject" -m "$body"
  else
    git commit -q -m "$subject"
  fi
  echo "committed: $(git log -1 --format='%h %s')"
fi

pr_body="${body:-$subject}"
echo
echo "Next, run each as its own command:"
printf 'git push origin %q\n' "$branch"
printf 'gh pr create --base main --head %q --title %q --body %q\n' "$branch" "$subject" "$pr_body"
