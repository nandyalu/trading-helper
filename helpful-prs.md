# Pending TradingAgents PRs worth watching

Excluding LLM-provider PRs as asked. Ranked by relevance to us:

**Directly fixes problems we've hit this session:**
- **#1134 — ✅ merged 2026-08-05** (`trading-helper-custom`) — Reddit OAuth2 support (100 QPM vs. the ~1 QPM RSS got throttled to in June 2026). Auto-detects REDDIT_CLIENT_ID/SECRET, falls back to RSS if unset — exactly the 429s we documented as "expected, degrades gracefully." This would make them mostly go away instead.
- **#1149 — ✅ merged 2026-08-05** (`trading-helper-custom`) — Official Ollama Modelfile guide + example fast/accurate profiles (Modelfile.trading-fast, Modelfile.trading-accurate). Validates the exact custom-Modelfile trick we used for gemma4-e2b-96k — worth diffing against once merged, they may have tuned params (temperature, generation cap) we didn't think to set.

**Reliability, relevant given we run small local models:**

- **#1189 — ✅ merged 2026-08-05** (`trading-helper-custom`) — Fixes the rating parser silently defaulting to "Hold" whenever it fails to parse a 5-tier rating from the LLM's output, instead surfacing a REVIEW sentinel. Small/local models are exactly where this bites — a gemma4-e2b-96k or qwen3 malformed rating currently becomes an invisible false "Hold" in our signals table today.
- **#1074 — ✅ merged 2026-08-05** (`trading-helper-custom`) — Retries a transient/malformed LLM response (including undecoded JSON) instead of aborting the whole multi-agent run. Directly reduces "Analysis failed for X" errors on flaky local inference.
- **#1200 — ✅ merged 2026-08-05** (`trading-helper-custom`) — Stops the bull/bear debate's opening turn from rebutting an argument that was never made (empty current_response mislabeled as the other side's claim) — a real hallucination source in the debate transcript we store as investment_plan.
- **#1071 — ✅ merged 2026-08-05** (`trading-helper-custom`) — CircuitBreaker + cleaner vendor fallback chain in dataflows/interface.py — same spirit as our Reddit degrade-gracefully pattern, applied uniformly.

**Feature-relevant to what we're building:**

- **#1082 — ✅ merged 2026-08-05** (`trading-helper-custom`) — Every Trader proposal gets a required win-probability + deterministic risk/reward/expected-value review, not just a narrative. Pairs directly with our sizing.py/price-target fields — richer structured data to store and show on the dashboard.
- **#1122 — ✅ merged 2026-08-05** (`trading-helper-custom`) — A cheap no-LLM-call candidate screener (yf.screen() + CoinGecko + a static futures list, filtered by risk/momentum/horizon). Could feed "suggested tickers to add to your watchlist" without spending GPU time.
- **#1076** — still unmerged. Someone's independently building almost exactly what we just built: a FastAPI/SSE backend (desk_server/) fronting the engine, plus TradingAgentsGraph.stream_run() and resolve_pending_entries(). Notably, their runs "execute on a dedicated single-worker pool" — i.e., they don't parallelize concurrent graph runs either, which is a useful data point for the concurrency plan below.

The 8 merged PRs above were cherry-picked onto `TradingAgents/`'s `trading-helper-custom`
branch (on our fork, `nandyalu/TradingAgentsUI`), on top of a refreshed `fork/main` base,
plus one local integration fix-up commit. See CLAUDE.md's "Vendored TradingAgents repo"
section for the branch/remote details. #1076 remains the one worth watching next time you
run `git fetch origin && git log HEAD..origin/main`.