# trading-helper — Claude Code context

Discord bot + FastAPI/Angular dashboard (`backend/`) delegating analysis to a
vendored multi-agent framework (`TradingAgents/`, registered as a git
submodule of this repo — see "Vendored TradingAgents repo" below for the
remote/branch details). See [README.md](README.md) and
[docs/overview.md](docs/overview.md) for architecture/commands — this file
only covers what those don't.

## Markdown conventions

Don't hard-wrap prose — write each sentence (or paragraph) on one line, no
matter how long. Zensical (the `docs/` site generator) sometimes mis-renders
a sentence that's been split across multiple source lines. Applies to every
`.md` file in the repo, not just `docs/`.

## Deployment topology (important, non-obvious)

Two copies of the compose config exist and are **not synced automatically**:

- `dockge/trading-bot.compose.yaml` — local-only working template
  (`dockge/` is gitignored, not tracked in this repo). Edit this one.
- `/opt/stacks/trading-bot/compose.yaml` + `.env` — the actually-deployed
  copy, managed via the Dockge UI. **Root-owned**, outside this repo, and
  already drifted from the template (Discord/Webull secrets are pasted in
  directly there instead of using `${VAR}` substitution). Applying a repo
  edit to the deployed stack means manually re-applying the diff in the
  Dockge UI's compose editor — never wholesale-replace its `environment:`
  block or you'll clobber the hardcoded secrets.

To inspect the live container: `docker logs trading-bot`, `docker exec
trading-bot env`. Don't sudo-edit `/opt/stacks/...` directly — hand the user
the exact diff/snippet to paste into the Dockge UI instead (their stated
preference).

## Ollama pool topology (deployed ≠ the repo template)

`dockge/ollama-pool.compose.yaml` describes **two** backends (`ollama-pool`,
`ollama-pool-b`) behind an nginx round-robin named `ollama-lb`. That is stale.
What actually runs (verified 2026-08-06):

- **Four** backends: `ollama-pool-a` … `ollama-pool-d`, one AMD card each
  (gfx1030, 8 GiB).
- `ollama-proxy` (image `ollama-proxy:local`) replaced nginx. It is a small
  FastAPI app: least-active-connections routing, `CONCURRENCY_PER_BACKEND=1`,
  `WAIT_TIMEOUT=600` (queues rather than 503s), and a `/healthz` endpoint
  reporting per-backend health and active count. Still on host port 11435.

**One analysis occupies exactly one GPU.** TradingAgents' graph is internally
sequential — analysts run one after another, then the debate, then the trader —
so a single `propagate()` never has more than one LLM request in flight. Extra
GPUs are only used by running *several analyses at once*.

That makes `TRADINGAGENTS_MAX_CONCURRENT_ANALYSES` (currently 4) the knob that
decides GPU utilization, and it should equal the backend count. Anything above
it just queues in the proxy.

Every multi-ticker caller must go through `analysis.run_analyses()`, which
dispatches with `asyncio.gather` and lets the shared semaphore do the bounding.
A `for ticker in …: await run_analysis_and_notify(ticker)` loop looks correct
and silently pins the whole sweep to one GPU — that bug shipped in the daily
sweep, the watchdog triggers, and the earnings check.

To check which backends served a run:
`docker logs --since 24h ollama-pool-a | grep "starting runner"` (an idle
backend has no recent entries), or `curl localhost:11435/healthz`.

## LLM provider switching

`TradingAgents/tradingagents/llm_clients/` is a full multi-provider
abstraction (ollama, google, openai, anthropic, azure, bedrock, etc.) —
switching providers is a config change, not a code change. Controlled via
three vars threaded through `dockge/trading-bot.compose.yaml`'s
`environment:` block into the stack `.env`:

- `LLM_PROVIDER` (defaults to `ollama`)
- `LLM_MODEL` (defaults to `qwen3:latest`) — used for both
  `TRADINGAGENTS_DEEP_THINK_LLM` and `TRADINGAGENTS_QUICK_THINK_LLM` (they
  share one value; splitting them needs a small code change in
  `TradingAgents/tradingagents/graph/trading_graph.py`)
- `GOOGLE_API_KEY` (passthrough, only relevant when `LLM_PROVIDER=google`)

**Current model (2026-08-06):** `gemma4-e2b-96k`, a custom Modelfile build of
`gemma4:e2b` with the context raised to 96k. A full analysis takes 2-3 minutes,
against roughly 15 for `qwen3:latest`.

This supersedes an earlier "known-bad model" note about `gemma4:e2b`. Stock
`gemma4:e2b` did hit a `GraphRecursionError` on ZBH — its reasoning loop never
terminated — but that was a context-length failure: tool-call history was being
truncated out from under the loop. At 96k the failure does not occur. Don't
revert to stock `gemma4:e2b` at the default context; `qwen3:latest` stays the
known-good slow fallback.

Analysis speed is what makes the 1-2 week trade horizon practical — signals
have to be produced faster than they expire — so treat a regression here as a
correctness problem, not a performance one.

**Gemini capacity note (2026-07-30):** `gemini-3.5-flash` returned 100%
persistent `503 UNAVAILABLE` ("high demand") over ~12h straight — looked
like a tier/capacity issue with that specific just-GA'd model, not a
transient blip. `gemini-3.1-flash-lite` worked reliably (16/16 calls
succeeded), ran a full analysis in <1 min vs Ollama's ~15 min, at roughly
$0.02–0.08/analysis. If revisiting Gemini, start with `flash-lite`, not
`3.5-flash`.

## Vendored TradingAgents repo

It's a real nested git repo, registered as a **git submodule** of this repo
(`.gitmodules`, pinned to a commit via a `160000` gitlink) — this repo tracks
which TradingAgents commit is checked out without flattening its history.
`git clone` needs `--recurse-submodules` (or `git submodule update --init`
afterward) to populate it.

**Remote-naming gotcha**: a fresh submodule checkout only gets one remote,
named `origin`, pointing at whatever URL is in `.gitmodules` — that's the
`fork` (nandyalu/TradingAgentsUI), not upstream. The two-remote setup
described below (`origin` = TauricResearch upstream, `fork` = our fork) is
this particular working copy's local addition, done once when the branch was
first built; it does not survive a fresh clone. To restore it after a fresh
clone: `cd TradingAgents && git remote rename origin fork && git remote add
origin https://github.com/TauricResearch/TradingAgents.git && git fetch origin`.

Remotes (in a working copy that's had the above applied):

- `origin` = `https://github.com/TauricResearch/TradingAgents.git` — kept
  only as a reference point for diffing; do not push here.
- `fork` = `https://github.com/nandyalu/TradingAgentsUI.git` — our fork.
  Checked-out branch is `trading-helper-custom`, based on `fork/main`
  (itself a few commits ahead of the old v0.3.1 pin we used to track) plus 9
  commits cherry-picked from open upstream PRs that weren't merged yet but
  were judged worth having:

  - #1189 unparseable ratings surface as REVIEW instead of a silent Hold
  - #1200 avoid inventing arguments in opening debate turns
  - #1071 simplified vendor routing + CircuitBreaker for LLM vendor resilience
  - #1149 custom Ollama Modelfile guide (fast/accurate profiles)
  - #1074 retry an undecodable JSON response body instead of aborting the run
  - #1082 probability + risk/reward review on every trader proposal
  - #1134 Reddit OAuth2 (100 QPM) with automatic fallback to the RSS scraper
    when `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET` are unset. **The OAuth path
    is effectively dead for this project**: Reddit's Responsible Builder Policy
    ended self-serve API app creation, so those credentials can't be obtained
    for a personal tool. RSS is the supported path — see
    [docs/setup.md](docs/setup.md). Don't treat 429 warnings as a bug.
  - #1122 candidate screener script + trade-horizon-aware analysis prompts
  - plus one local fix-up commit resolving integration issues between the
    above (an `UnboundLocalError` in `sentiment_analyst.py` that was latent
    in #1134's own diff, plus two test fixtures)

  Full upstream test suite (606 passed, 2 pre-existing skips) and
  trading-helper's own `backend/tests/` (80 passed) were both green against this
  branch before it was pushed.

To check whether `fork/main` has moved (new commits merged upstream into the
fork) before assuming a bug needs a local fix: `cd TradingAgents && git fetch
fork && git log HEAD..fork/main --oneline`. Check `git log --stat` on any new
commits before merging — don't blind-merge, and re-apply the same care used
for the original cherry-picks if `fork/main` and `trading-helper-custom`
diverge further. Dependencies (including `tradingagents` itself, installed
non-editable from `./TradingAgents` — see root `pyproject.toml`'s
`[tool.uv.sources]`) are managed with `uv`: to pick up new commits made here
in trading-helper's own venv, just `uv sync` — it re-resolves the local path
dependency automatically, no manual reinstall needed.

After committing inside `TradingAgents/` (new cherry-picks, a rebase onto a
moved `fork/main`, etc.), the parent repo still points at the old commit
until you also commit the updated gitlink here: `git add TradingAgents && git
commit -m "..."` from the trading-helper root. `git status` at the root shows
`TradingAgents` as dirty/ahead whenever the two are out of sync.

## The model invents price levels (important)

`gemma4-e2b` reasons acceptably in prose but does not reliably carry concrete
figures into structured numeric fields. On 2026-08-06, 3 of 8 signals came back
with fabricated entry / stop / target levels:

| Ticker | Real price | Model's entry |
|---|---|---|
| GOOG | $356.62 | $2,000.00 |
| VERI | $1.26 | $4.50 |
| VERI | $1.25 | $30.00 |

The numbers look like **prices the model remembers from training** — $2,000 is
roughly pre-split GOOG, $30 roughly VERI's 2021 range. Two runs on the same
stock the same day produced entries 24× apart, so it is invention, not stale
data and not another ticker bleeding in. The market analyst's own report had
the right prices throughout; the *trader* stage was simply never given a price.

Two defenses, both in place:

1. **The trader now receives the deterministic snapshot.**
   `build_verified_market_snapshot` (computed in Python from the same OHLCV,
   never by a model) goes into the trader prompt, which explicitly forbids
   recalled prices and says to omit levels rather than guess.
2. **`analysis._trade_plan_levels` discards levels far from the traded price**,
   using `max_level_deviation_pct` per horizon (swing 35%, position 70%).
   `risk_reward` and `expected_value_r` go out with them, since TradingAgents
   computes both *from* those levels. `win_probability` survives — it is the
   model's own estimate, not a derivation.

Defense 2 is the one that must never be removed. A prompt cannot make a 2B
model reliable, and a fabricated stop is worse than no stop: the watchdog arms
an alert at a price the stock may never reach, or fires one immediately.

`backend/scripts/scrub_implausible_levels.py` clears bad levels from rows
written before the check existed.

## Market data goes through the bar cache

`backend/services/bars.py` is a read-through cache over the `dailybar` table
(`(ticker, date)`). **Route any new daily-history read through `bars.get_bars()`,
not `yf.Ticker(...).history()`** — the whole point is that a completed session
never changes, so refetching one is waste and rate-limit risk.

Two legitimate direct yfinance uses remain, neither of them history:
`positions.get_current_price` (a quote, Webull's fallback) and
`watchdog.get_next_earnings_date` (the calendar).

Non-obvious rules the cache depends on:

- **Today's bar is never stored.** It is still moving. `include_today=True` gets
  it via a separate live request instead.
- **Pass `today=` when the caller has a market-relative date.** The watchdog
  does: after about 8pm ET the local clock is already tomorrow, so the default
  would treat the just-closed session as still in progress.
- **`_earliest_attempt` records what was asked for, not what came back.** Without
  it, a ticker with less history than requested refetches on every call forever.
- **`last_completed_session` ignores holidays deliberately.** The 30-minute
  recheck throttle absorbs the resulting extra request.

The table is pure cache; dropping it costs only a refetch.

## Reddit/social-sentiment data source

`TradingAgents/tradingagents/dataflows/reddit.py` scrapes Reddit's public RSS
search feed (no API key). Occasional `429`/warning logs are expected and
handled gracefully (retry-once-with-backoff, then degrades to "no posts
found" for that subreddit) — not a bug unless it fails on *every* run.
`stocktwits.py` exists in the same directory as an unused alternative if
Reddit ever becomes unreliable enough to matter.

The Webull OpenAPI SDK (`backend/services/quotes.py`, `backend/services/broker.py`) is market-data +
brokerage only (quotes, fundamentals, financials, trading) — it has no
news-article or social-sentiment endpoints, so it can't replace
`get_news`/`reddit.py`.
