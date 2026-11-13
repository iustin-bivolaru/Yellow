# Yellow

## Schedule and state

A GitHub Actions workflow (`.github/workflows/daily.yml`) runs daily at 9 AM Europe/Bucharest (crons at 06:00, 07:00 and 09:00 UTC; the later ones are retries and do nothing if today's digest exists).
Its state (seen items, tech registry, digests) is stored on the orphan `data` branch, never on `main`. To get it locally (move an existing `./data` aside first): `git fetch origin data && git worktree add data data`.
Trigger a manual run from the Actions tab (`force` skips the 9 AM gate, `no_llm` skips the Claude call).
