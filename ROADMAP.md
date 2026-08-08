# Trading Helper — Feature Roadmap

The bot already generates TradingAgents signals, tracks pass/fail outcomes, and logs real
transactions. The theme of this roadmap: **close the feedback loop** — read that accumulated
data back, measure whether the signals are worth following, and act on them with less friction.

## Phase 1 — Measure & follow the signals *(implemented — deploys with the next image build)*

### 1.1 Benchmark-relative signal evaluation
An absolute pass (price went up after a Buy) is meaningless in a rising market. When a
signal's evaluation date arrives:

- Fetch the ticker's and SPY's price window from signal date → evaluation date.
- Grade twice: **absolute** (existing rule, unchanged for continuity) and **vs SPY**
  (Buy passes only if the ticker beat SPY; Sell passes only if it lagged SPY; Hold passes
  if alpha stayed within ±10%).
- Store `alpha_pct` (ticker % move − SPY % move) per signal.
- Track **price-target hits**: the rationale's price target counts as hit if the price
  touched it at any point in the window (window high/low), not just at the end.

### 1.2 `/scorecard` — the track record
Aggregates resolved signals so we know *when to trust the bot*:

- Overall: resolved count, absolute win rate, vs-SPY win rate, price-target hit rate.
- Per decision type (Buy/Hold/Sell/…): win rates + average move.
- Per ticker: win rate (is it better at some names?).
- Optional `ticker:` filter.

### 1.3 Paper trading via reactions + `/paper`
Follow a signal without real money, with one click:

- The bot seeds a ✅ reaction on every analysis embed it posts.
- Clicking ✅ executes that signal as a paper trade **at the current price** (an honest
  fill — you can't trade at a past price):
  - **Buy/Overweight** → opens a lot sized the same way a real one would be: the ATR
    risk sizing from `/risk`, limited by the per-position cap. Falls back to a fixed
    notional (default $1,000, configurable via `/papersize`) only when no account
    equity is set. Matching the two books is what makes the paper equity curve
    evidence about the real account.
  - **Sell/Underweight** → closes the entire open paper position (FIFO), reporting
    realized P&L. No shorting in v1 — reacting to a Sell with no open position just says so.
  - **Hold** → nothing to execute; the bot replies saying so.
  - One execution per signal (repeat reactions are ignored).
- `/paper` — portfolio view: per ticker shares, avg cost, current value, unrealized P&L,
  plus totals and realized P&L to date.
- `/paperclose <ticker>` — manual exit at the current price when you don't want to wait
  for a Sell signal.
- Paper trades live in their own `papertransaction` table (same shape as real
  transactions) and reuse the existing FIFO position math.

## Phase 2 — Watch the market between runs *(implemented — deploys with the next image build)*

### 2.1 Intraday alert watchdog (no LLM)
A 15-minute loop during US market hours (9:30–16:00 ET) over watchlist + held (real and
paper) tickers, alerting on: daily moves ≥5%, volume ≥2× the 20-day average, price ≥10%
below a held position's avg cost, and touches of a signal's price target. Thresholds and
on/off via `/alertconfig`; alerts dedupe through the `alert` table (per ticker per day;
targets once per signal) so restarts never re-spam.

### 2.2 Event-driven analysis triggers
Big-move and volume alerts also trigger an immediate TradingAgents run (max one per
ticker per day — skipped if the ticker already has a signal today). A separate pre-market
task (13:00 UTC) runs a fresh analysis for tracked tickers reporting earnings within
2 days. The fixed daily sweep can now be turned off with `/dailysweep` — signal
evaluation still runs nightly either way.

## Phase 3 — Portfolio-level intelligence *(implemented — deploys with the next image build)*

### 3.1 `/portfolio` dashboard
Per-position weights, concentration warnings (≥30% of the book, only when holding 2+
names), unrealized/realized/total P&L, and an honest vs-SPY comparison: every open FIFO
lot is measured against putting the same dollars into SPY on the same date, weighted by
cost. Lots with no benchmark bar yet (e.g. bought today pre-market) are excluded from
both sides.

### 3.2 Weekly digest
Friday 23:00 UTC (and `/digest` on demand): signals resolved that week with outcomes and
vs-SPY verdicts, new signals by decision, win rate last-30-days vs all-time, alerts fired
by type, and a snapshot of both books.

### 3.3 Market regime snapshot
Weekday pre-market post at 12:45 UTC (and `/regime` on demand): VIX with a plain-English
level, SPY vs its 200-day average, and the 10Y–3M treasury spread, classified 🟢/🟡/🔴 by
a simple negative-count rule. Sourced entirely from yfinance (^VIX, SPY, ^TNX−^IRX) since
no FRED key is configured; each indicator degrades independently if a fetch fails.
*Still open:* injecting the regime line into the TradingAgents analysis prompt.

## Phase 4 — Deeper analysis & interaction *(implemented — deploys with the next image build)*

### 4.1 Persist full analyst reports
Every new signal stores the four analyst reports plus both research/trader plans in the
`signalreport` table (one row per report type). Pre-existing signals only have the
rationale; /ask says so when answering about them.

### 4.2 `/ask <ticker> <question>`
Q&A over the latest signal's stored reports using the graph's own quick-think Ollama
client (backend/services/ask.py). Holds the analysis lock (same GPU), strips `<think>` blocks, and
budgets the context (~4k chars per report, 24k total) for the small local model.

### 4.3 Position sizing & risk levels in the embed
Buy/Overweight embeds now carry a "Suggested sizing" field: a 2×ATR(14) stop, and — once
`/risk equity:… risk_pct:…` is configured — a share count that puts that % of equity at
risk between entry and stop, then limited to `max_position_pct` of equity (20% by
default). The field also warns when `max_positions` names are already open
(backend/services/sizing.py).

The position cap is not redundant with risk sizing. Risk sizing bounds the loss if the
stop is hit; the cap bounds concentration. A low-ATR stock produces a large share count
from a small risk budget, and the earlier 100%-of-equity limit was no limit at all for
anyone holding more than one name.

### 4.4 Paper equity curve vs SPY
The daily task snapshots the paper book into `papersnapshot` (upsert per day). /paper
grows a Performance section: P&L sparkline since the first snapshot, max drawdown, SPY
buy-and-hold over the same span, and the lot-by-lot open-book vs-SPY comparison shared
with /portfolio.

## Phase 5 — Retarget at 1-2 week swing trades *(implemented)*

Every analysis before this ran at TradingAgents' default `position` horizon — a
roughly 6-month thesis — because `propagate()` was never passed a `horizon`. The
recorded signals answered a question the user was not asking.

### 5.1 Horizon threaded end to end
A `horizon` setting (`swing` by default) reaches `graph.propagate()`, so it changes what
the analysis weights. In the vendored fork, `get_horizon_instruction` now states 1 to 2
weeks rather than "a few days", and a new `get_indicator_instruction` steers the market
analyst toward indicators that resolve inside that window — the base prompt leads with
the 50 and 200 SMA, which its own text calls unsuited to frequent entries.

The horizon also sets both grading parameters, because both scale with the window:
signals are graded after 14 days rather than 30, and a Hold passes within ±4% rather than
±10%. A ±10% band over two weeks passes almost every Hold, which makes the grade
meaningless.

Each `signal` row records its own horizon, so changing the setting never re-grades older
signals by new rules.

### 5.2 Small-account sizing limits
See 4.3 — a per-position cap and a max-open-positions warning, and paper buys now using
the same sizing as real ones.

### 5.3 Start fresh
`backend/scripts/reset_signals.py` deletes signals and everything derived from them
(reports, paper trades, paper snapshots), in foreign-key order. It is deliberately a
script and not a migration: a migration would run on every deployment. Real transactions,
the watchlist, settings, and the price cache survive.

### 5.4 The trade plan is kept, not discarded
TradingAgents computes an entry price, a stop-loss, a win probability, a risk/reward
ratio, and an expected value for every analysis — on `TraderProposal`, one stage before
the portfolio manager. `PortfolioDecision` carries none of it, and `record_signal` read
only the final decision text, so all of it was thrown away.

Five nullable columns on `signal` now keep it, parsed from
`final_state["trader_investment_plan"]` by pure extractors in
backend/services/signals.py. The risk/reward and expected value are computed in
TradingAgents from the levels rather than asserted by the model, so they stay consistent
with the levels shown beside them. Nullable matters: a missing stop read as 0.0 would
look like a stop at $0.

The Discord embed grows a "Trade plan" field and the signal detail page a matching
section. Both also now show `alpha_pct`, `outcome_vs_benchmark`, and `price_target_hit`,
which were stored but never rendered on the web.

### 5.5 Stop alerts keyed to the analysis
The watchdog gains a `signal_stop` alert that fires when a held ticker reaches the stop
level its own analysis named. The existing `stop_loss` alert (a fixed percentage below
your average cost) stays, with a separate dedupe key.

They are deliberately independent, because they answer different questions: `signal_stop`
means the thesis is broken, `stop_loss` means you are down a set amount on what you
actually paid. Either can be true without the other, and a position with no signal behind
it has only the second.

When the trader names no stop on a Buy, `record_signal` falls back to the same
2×ATR(14) level the sizing field already displays, so every actionable Buy has an exit
the watchdog can watch.

### 5.6 Alerts are visible outside Discord
`GET /api/alerts` plus an Alerts page. The alert log existed and was written on every
scan, but only ever surfaced in the weekly digest. At a 1-2 week horizon the alerts are
the channel that matters most.

*Still open:* the conviction filter (thresholds on win probability and risk/reward, with
the scorecard split by band) and calibrating the stated win probability against realized
outcomes. Both need a few months of swing signals first.

## Phase 6 — The dashboard as the place you look *(implemented)*

Discord is good at telling you something happened. It is bad at showing what happened, and
worse at showing whether any of it worked. The web app existed but was a set of separate
tables — the price chart knew nothing about the signals, and the signals knew nothing about
the alerts.

### 6.1 The chart carries the analysis
`GET /api/tickers/{t}/events` returns bars, signals, alerts, and trades in one call, because
the chart overlays and the timeline below them are the same events drawn two ways; fetching
them separately let the two disagree mid-flight.

The chart draws signal arrows (up for Buy-ish, down for Sell-ish), trade squares, alert dots,
and dashed stop and target lines from the signal currently in force. Entries sit below the bar
and exits above it so they cannot overlap.

### 6.2 One timeline per ticker
Signals, alerts, and trades merged newest-first, with the graded outcome on each signal. Three
tables, three shapes, one list — the reader should not have to interleave them by eye.

### 6.3 An Overview page
A landing page that answers "is there anything I should do?" — held tickers whose newest
analysis says exit, and recent stop/target alerts, above everything else. Informational alerts
(big move, volume) stay off it. The win rate shows a raw count until ~20 signals have resolved.

### 6.4 /docs belongs to the docs
FastAPI registers its Swagger UI at construction, before the Zensical site is mounted, so
`/docs` served the API reference and the real docs were unreachable. The API reference moved to
`/api/docs`, alongside `/api/redoc` and `/api/openapi.json`.

### 6.5 The in-progress bar (a correctness fix, found via a blank chart)
While a session is open, yfinance appends a row for that day with a volume but NaN prices.
Every reader took `.iloc[-1]`, so the NaN propagated silently — it reaches JSON as `null`, not
as an error. Three consequences, all live before this fix:

- `get_price_window` returned a NaN `last_close`, so **graded signals stored NaN and their
  pass/fail came out wrong** — NaN compares false against every threshold, so a Buy that won
  was recorded as a loss.
- `open_book_vs_spy` returned NaN, so the **vs-SPY comparison silently reached the dashboard
  as null** rather than as a number.
- `fetch_regime` lost the SPY price and the SPY-vs-200-day reading.

`drop_incomplete_bars` in backend/services/positions.py is now applied at every yfinance read.
For the watchdog it deliberately makes the scan skip a ticker rather than alert on a NaN.

## Phase 7 — Actually use the GPU pool *(implemented)*

The Ollama pool grew to four cards behind `ollama-proxy`, and
`TRADINGAGENTS_MAX_CONCURRENT_ANALYSES` was raised to 4 to match — but a sweep of
8 tickers still ran on one GPU, taking about four times longer than it needed to.

The cause was in this repo, not the pool. `analysis.propagate_ticker` has always
held a semaphore to bound concurrent runs, but three callers awaited each ticker in
a loop, so the semaphore never saw more than one caller at a time:

- `_daily_signals_job` — the daily watchlist sweep
- `_alert_watchdog_job` — big-move and volume triggers
- `_earnings_check_job` — pre-market earnings runs

Only the `POST /api/tickers/analyze-all` route dispatched concurrently, so the
manual button used every GPU while every scheduled job used one.

`analysis.run_analyses()` is now the single dispatch path for all four, with
per-ticker error isolation and an optional per-failure callback (the scheduler
posts to Discord, the route just logs). The route's inline `asyncio.gather` is
gone, so the two cannot drift apart again.

**The thing to remember:** one analysis occupies exactly one GPU. TradingAgents'
graph is internally sequential, so it never has more than one LLM request in
flight. GPU utilization is entirely a function of how many analyses run at once,
which makes a sequential `await` loop indistinguishable from having one card.

## Phase 8 — Stop refetching bars that cannot change *(implemented)*

Every caller fetched its own yfinance history. The intraday watchdog pulled roughly
a month of bars per ticker **every 15 minutes** to read two closes and a volume
average, then discarded the rest; the chart (180d), the ATR (3mo), and signal
grading each refetched overlapping ranges of the same bars independently.

`backend/services/bars.py` is now a read-through cache over a `dailybar` table
keyed `(ticker, date)`. It works because **a completed session never changes**.

The bar for the day in progress is deliberately never stored — caching it would
freeze a mid-session snapshot and serve it as a close to the next reader. Callers
that need it pass `include_today=True` and get a separate live request.

Three cases decide whether a cache like this actually helps or quietly degrades
into "fetch every time", and each has a test:

- **A ticker with less history than requested** (a recent listing, or a 365-day
  chart of a stock that has traded for 200) looks permanently incomplete.
  `_earliest_attempt` records what was *asked for*, not what came back, which is
  what makes "we asked and this is all there is" distinguishable from "we never
  asked".
- **A market holiday** means no new session closes, so the "is the cache behind?"
  check can never be satisfied. A 30-minute recheck throttle absorbs it.
- **A widened range** (the user switching the chart from 90 days to 365) must
  fetch immediately and not wait out that throttle.

Measured on a warm cache: the ATR, the chart, and grading make **no** yfinance
history call at all. The watchdog still makes one per tick — it needs the current
price and volume, which is irreducible — but the payload is one bar instead of
about twenty-one.

`last_completed_session` ignores market holidays on purpose. Being wrong in the
conservative direction costs one extra request, which the throttle then absorbs;
modeling the NYSE calendar would not pay for itself.

The table is pure cache — dropping it costs nothing but a refetch. Growth is
about 250 rows per ticker per year, so no pruning is needed.

## Phase 9 — Import holdings with their real purchase dates *(implemented)*

A Webull position snapshot carries **no acquisition date** — confirmed against the
documented schema, which is why `broker._parse_opened_at` never matched anything
and every imported holding was dated the day the sync ran. That anchored each
lot's benchmark entry on the import date, so SPY got days to move while the
position was credited with months of gains and the vs-SPY alpha came out
meaningless.

Order History does carry it. `fetch_order_fills` pages it read-only, and
`reconstruct_open_lots` walks the buys newest-first — FIFO sells oldest first, so
what is still held is the newest buys — until they cover the broker's quantity.
The result is one dated transaction per real lot, at the real fill price rather
than the broker's blended average.

Shares the history cannot explain come back as a single date-unknown remainder
and stay out of the benchmark comparison. That covers holdings transferred in,
anything bought before the 2018 horizon, and fractional dividend shares that
never came through an order.

`fix_import_dates --from-webull` applies the same rebuild to holdings imported
before this existed.

Three things about the endpoint that the docs do not make obvious, each of which
silently returns nothing or fails: rows are combo wrappers with the real orders
nested under `orders`; `page_size` must be 10-100; and the documented rate limit
is optimistic. See CLAUDE.md.

## Phase 10 — Stop chasing tickers that no longer trade *(implemented)*

A delisted symbol does not fail cleanly. AILEQ, held and delisted, kept returning
data: five bars across two months, all at $0.000001. To the bar cache that looked
like a ticker merely behind, so it refetched every 30 minutes forever; the
watchdog polled it every 15; and the daily sweep spent minutes of GPU analyzing a
company with no market before failing to record the signal for want of a price.

`backend/services/listings.py` marks a ticker inactive once no fresh bar has
appeared for seven trading days, and every fetch path checks it. The rule is
deliberately about freshness rather than price — a real penny stock at $0.0001 is
still real, and a price threshold would retire it by mistake.

Inactive is not permanent: one recheck a day means a lifted halt recovers on its
own. `/ignore` and `/unignore` are the manual override, and a manual setting is
never overwritten by detection. A held position still appears in the portfolio;
there is simply nothing to fetch for it.

Writing this also exposed that the test suite had been writing ticker state into
the developer's real database — a "NOTREAL" symbol from one test was marked
inactive there, and the next run of that same test read it back and failed on an
assertion about fetch counts. The isolation fixture is now autouse and
unconditional.

## Broker sync — track what you actually hold *(implemented)*

backend/services/broker.py mirrors the Webull account (read-only Trade API, same credentials) into
the bot: every held equity is auto-watchlisted so the daily sweep, watchdog, and
earnings triggers generate signals for it, and the transaction log is reconciled
*additively* — unknown holdings imported as a synthetic buy at broker avg cost (noted
"webull sync" via the new `transaction.note` column), quantity drifts adjusted at broker
prices, while bot-side positions absent at Webull are only flagged, never auto-sold.
Crypto accounts and non-standard instruments (CVR remnants etc.) are skipped. Runs
pre-market daily (12:35 UTC, posts only on changes) and on demand via `/webullsync`.
The bot still never places orders.

## Data sources — Webull real-time quotes *(implemented, awaiting API keys)*

backend/services/quotes.py wraps the official `webull-openapi-python-sdk` snapshot endpoint. Set
`WEBULL_APP_KEY` / `WEBULL_APP_SECRET` in `.env` (plus `WEBULL_SANDBOX=1` to target
`api.sandbox.webull.com` with test keys) and every `get_current_price` call — paper
fills, alerts, portfolio views — upgrades from yfinance's delayed close to Webull's
real-time snapshot. No keys, a failed call, or a 401 (which disables Webull until
restart) all fall back to yfinance transparently. Historical bars (windows, ATR,
regime) intentionally stay on yfinance. The SDK is baked into the Docker image and the
compose file passes the env vars through.

## Documentation *(implemented)*

Markdown docs in `docs/` (overview, command reference, daily workflow, finding-your-edge
guide) built into a static site with [Zensical](https://zensical.org) (`zensical.toml`,
own Docker build stage — the generator never reaches the runtime image) and served by
the bot itself at the container's web root (backend/app.py, port 8080, host port via
`DOCS_HOST_PORT`). Rebuild the image to republish; `python -m zensical serve` for local
preview.

## Deliberate non-goals (for now)
- **Real order execution** — the bot informs decisions; it doesn't place trades.
- **Paper shorting** — Sell signals close longs only; revisit if the scorecard shows
  Sell calls have edge.
- **Intraday LLM analysis** — the local model is the bottleneck; alerts stay rule-based.
