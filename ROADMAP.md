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
  - **Buy/Overweight** → opens a lot sized to a fixed notional (default $1,000,
    configurable via `/papersize`).
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
client (bot/ask.py). Holds the analysis lock (same GPU), strips `<think>` blocks, and
budgets the context (~4k chars per report, 24k total) for the small local model.

### 4.3 Position sizing & risk levels in the embed
Buy/Overweight embeds now carry a "Suggested sizing" field: a 2×ATR(14) stop, and — once
`/risk equity:… risk_pct:…` is configured — a share count that puts that % of equity at
risk between entry and stop, capped at 100% of equity (bot/sizing.py).

### 4.4 Paper equity curve vs SPY
The daily task snapshots the paper book into `papersnapshot` (upsert per day). /paper
grows a Performance section: P&L sparkline since the first snapshot, max drawdown, SPY
buy-and-hold over the same span, and the lot-by-lot open-book vs-SPY comparison shared
with /portfolio.

## Broker sync — track what you actually hold *(implemented)*

bot/broker.py mirrors the Webull account (read-only Trade API, same credentials) into
the bot: every held equity is auto-watchlisted so the daily sweep, watchdog, and
earnings triggers generate signals for it, and the transaction log is reconciled
*additively* — unknown holdings imported as a synthetic buy at broker avg cost (noted
"webull sync" via the new `transaction.note` column), quantity drifts adjusted at broker
prices, while bot-side positions absent at Webull are only flagged, never auto-sold.
Crypto accounts and non-standard instruments (CVR remnants etc.) are skipped. Runs
pre-market daily (12:35 UTC, posts only on changes) and on demand via `/webullsync`.
The bot still never places orders.

## Data sources — Webull real-time quotes *(implemented, awaiting API keys)*

bot/quotes.py wraps the official `webull-openapi-python-sdk` snapshot endpoint. Set
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
the bot itself at the container's web root (bot/docs_server.py, port 8080, host port via
`DOCS_HOST_PORT`). Rebuild the image to republish; `python -m zensical serve` for local
preview.

## Deliberate non-goals (for now)
- **Real order execution** — the bot informs decisions; it doesn't place trades.
- **Paper shorting** — Sell signals close longs only; revisit if the scorecard shows
  Sell calls have edge.
- **Intraday LLM analysis** — the local model is the bottleneck; alerts stay rule-based.
