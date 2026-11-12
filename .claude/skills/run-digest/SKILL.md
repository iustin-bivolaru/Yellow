---
name: run-digest
description: Run the Yellow news pipeline locally and preview the phone UI. Use when asked to run, test end-to-end, preview, or debug a digest build.
---

# Run the digest locally

1. Activate the env and make sure deps are installed:
   ```bash
   source .venv/bin/activate && pip install -e ".[dev]" -q
   ```
2. Pick a mode:
   - **Free / offline-ish** (real sources, no Claude call): `python -m yellow run --dry-run --no-llm`
   - **Full run** (costs a fraction of a cent on Haiku): `python -m yellow run --dry-run`. It needs `ANTHROPIC_API_KEY`. If the key isn't set, ask the user rather than skipping.
   - `--dry-run` must not write to `data/` (no seen/registry updates). It only writes `site/`.
3. Check the console summary: items per source, how many were dropped as duplicates or already seen, and how many went to the LLM. If a source returned 0, look at its warning and say so in your report.
4. Preview: `python -m http.server -d site 8000`, run in the background, then open http://localhost:8000. If the browser tool is available, check it at phone width (390×844) in light and dark mode.
5. Report: item counts, the categories that came out, the "New on radar" technologies, any source failures, and the token usage/cost printed by `analyze.py`.

Don't commit `site/`. Don't commit `data/` changes from a local run unless the user asks.
