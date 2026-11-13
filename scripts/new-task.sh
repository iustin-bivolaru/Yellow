#!/usr/bin/env bash
# Start a task branch from origin/main (local steps only; no network).
#
# Precondition: run `git fetch origin` first (as its own command; the sandbox only lets
# network git run that way).
#
# Usage: scripts/new-task.sh <type>/<short-name>
#        scripts/new-task.sh --tidy   (housekeeping only; no branch, dirty tree allowed)
# Exit codes: 0 ok, 1 refused or failed, 2 bad usage, 3 the user must switch branches by hand
# (the diff to origin/main touches sandbox-protected paths).
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/new-task.sh <type>/<short-name>
  --tidy: only fast-forward local main and delete merged local branches.
  type: feat|fix|refactor|perf|test|docs|chore|ci|build
  Run `git fetch origin` first. Creates the branch from origin/main with --no-track,
  fast-forwards local main and deletes local branches already merged into origin/main.
EOF
}

# Housekeeping (local refs only): fast-forward main, delete merged branches with -d.
# $1 = a branch to keep (the new one); the current branch is never touched.
tidy() {
  local keep="${1:-}" current b deleted=0
  current="$(git branch --show-current)"
  if [[ "$current" != "main" ]] \
    && git show-ref --verify --quiet refs/heads/main \
    && git merge-base --is-ancestor main origin/main \
    && [[ "$(git rev-parse main)" != "$(git rev-parse origin/main)" ]]; then
    git update-ref refs/heads/main origin/main
    echo "fast-forwarded local main to origin/main"
  fi
  while IFS= read -r b; do
    [[ -z "$b" || "$b" == "main" || "$b" == "$keep" || "$b" == "$current" ]] && continue
    if git branch -d "$b" >/dev/null 2>&1; then
      echo "deleted merged branch: $b"
      deleted=$((deleted + 1))
    else
      echo "could not delete $b (left as is)" >&2
    fi
  done < <(git branch --merged origin/main --format='%(refname:short)')
  if [[ "$deleted" -eq 0 ]]; then
    echo "no merged branches to delete"
  fi
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi
if [[ "${1:-}" == "--tidy" && $# -eq 1 ]]; then
  cd "$(git rev-parse --show-toplevel)"
  if ! git rev-parse --verify --quiet origin/main >/dev/null; then
    echo "error: origin/main not found; run 'git fetch origin' first" >&2
    exit 1
  fi
  tidy ""
  exit 0
fi
if [[ $# -ne 1 ]]; then
  usage >&2
  exit 2
fi

name="$1"
cd "$(git rev-parse --show-toplevel)"

if ! [[ "$name" =~ ^(feat|fix|refactor|perf|test|docs|chore|ci|build)/[a-z0-9][a-z0-9-]*$ ]]; then
  echo "error: bad branch name '$name' (expected <type>/<short-name>, lowercase, dashes)" >&2
  usage >&2
  exit 2
fi

if git show-ref --verify --quiet "refs/heads/$name"; then
  echo "error: branch '$name' already exists locally" >&2
  exit 1
fi

if ! git rev-parse --verify --quiet origin/main >/dev/null; then
  echo "error: origin/main not found; run 'git fetch origin' first" >&2
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "error: working tree is dirty; commit or discard changes first" >&2
  git status --short >&2
  exit 1
fi

# Paths the Claude Bash sandbox write-protects: a switch touching them half-fails.
protected='^(\.claude/settings[^/]*\.json|\.claude/hooks/|\.claude/skills/|\.claude/agents/|\.env\.example$)'
touched="$(git diff --name-only HEAD origin/main | grep -E "$protected" || true)"
if [[ -n "$touched" ]]; then
  echo "The switch would touch sandbox-protected paths:" >&2
  echo "$touched" | sed 's/^/  /' >&2
  echo "Run this yourself (with the ! prefix), then run scripts/new-task.sh --tidy:" >&2
  echo "  git switch --no-track -c $name origin/main"
  exit 3
fi

# --no-track: tracking would write .git/config, which the sandbox blocks mid-switch.
git switch --no-track -c "$name" origin/main

current="$(git branch --show-current)"
if [[ "$current" != "$name" ]]; then
  echo "error: expected to be on '$name' but on '${current:-detached HEAD}'" >&2
  exit 1
fi
if [[ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]]; then
  echo "error: HEAD is not at origin/main after the switch" >&2
  exit 1
fi

tidy "$name"

echo "ready: on $name at $(git rev-parse --short HEAD) (origin/main), no upstream set"
