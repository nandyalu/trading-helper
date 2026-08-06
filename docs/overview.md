# How it works

## The moving parts

```
┌─────────────────────────────────────────────────────────────────┐
│ FastAPI app (backend/app.py)                                    │
│                                                                 │
│  Slash commands · ✅ reactions · scheduled tasks                │
└──────┬──────────────┬───────────────┬───────────────────────────┘
       │              │               │
       ▼              ▼               ▼
 TradingAgents   Rule-based       SQLite (data/trading.db)
 (local LLM      market logic     signals · outcomes · reports
 via Ollama)     (no LLM):        transactions · paper trades
 analysis        watchdog,        alerts · snapshots · settings
 pipeline        regime, sizing,
                 evaluation
       │              │
       ▼              ▼
   Ollama pool    Market data: Webull real-time quotes when
   (shared GPU)   configured, yfinance for everything else
```

Two kinds of intelligence, deliberately separated:

- **The LLM pipeline** (TradingAgents) runs the expensive, slow analysis:
  four analysts (market/technical, news, sentiment, fundamentals) feed a
  bull-vs-bear research debate, a trader drafts a plan, and a risk team
  settles on one of five decisions: **Buy, Overweight, Hold, Underweight,
  Sell**, usually with a price target and time horizon in the rationale.
- **Rule-based logic** does everything that must be fast, cheap, and
  trustworthy: grading outcomes, watching prices intraday, classifying the
  market regime, computing position sizes, reconciling your broker account.
  None of it involves a model, so none of it can hallucinate.

## The signal lifecycle

1. **Born** — an analysis runs (scheduled sweep, event trigger, or
   `/analyze`). The decision, full rationale, all analyst reports, the price
   at that moment, and the parsed time horizon are stored. The Discord embed
   gets a ✅ seeded on it.
2. **Actionable** — you can follow it as a paper trade (✅ reaction), ask
   questions about it (`/ask`), or act in your real account using the
   suggested stop/size from the embed.
3. **Watched** — while it matures, the intraday watchdog alerts if the price
   touches the signal's target or breaches a stop level on a held position.
4. **Graded** — when the time horizon arrives (default 30 days if the
   rationale didn't specify one), the bot fetches the full price window since
   the signal and grades it three ways:
   - **Absolute**: Buy passes if the price rose at all, Sell if it fell,
     Hold if it stayed within ±10%.
   - **vs SPY**: a Buy must have *beaten* SPY over the same window, a Sell
     must have *lagged* it (selling something that then underperformed the
     market was the right call), Hold passes if alpha stayed within ±10%.
   - **Target**: did the price *touch* the target at any point in the window
     (window high/low, not just the endpoint)?
5. **Aggregated** — every graded signal feeds `/scorecard` (win rates by
   decision type and ticker) and the weekly digest's rolling trend.

The vs-SPY grade exists because absolute grades lie in trending markets: a
Buy that gained 1% while SPY gained 5% "passed" absolutely but cost you money
against the obvious alternative.

## The daily schedule (all times UTC, weekdays)

| Time | What happens |
|---|---|
| 12:35 | **Webull sync** — real holdings mirrored into watchlist + positions (posts only on changes) |
| 12:45 | **Regime snapshot** — VIX, SPY vs 200-day average, 10Y–3M yield spread → 🟢/🟡/🔴 |
| 13:00 | **Earnings check** — fresh analysis for any tracked ticker reporting within 2 days |
| 13:30–20:00 (9:30–16:00 ET) | **Watchdog** every 15 min — move ≥5%, volume ≥2× average, stop breaches, target touches; big moves and volume spikes also trigger an immediate analysis (max one per ticker per day) |
| 21:30 | **Daily run** — matured signals graded and posted, paper book snapshotted, then the full watchlist sweep (unless `/dailysweep` turned it off) |
| Fri 23:00 | **Weekly digest** — the week's outcomes, win-rate trend, alerts, both books |

## Data sources

- **Webull OpenAPI** (when keys are configured): real-time snapshot quotes
  for every "price right now" — paper fills, alert checks, portfolio values.
  Requires a stock-quotes market-data subscription on the account; without
  it, or on any failure, the bot silently uses yfinance instead. Also the
  read-only Trade API for the account sync. The bot **never places orders**.
- **yfinance**: all historical bars (evaluation windows, ATR, 200-day
  average, volume baselines), the earnings calendar, VIX and treasury-yield
  indices, and the quote fallback.

## Storage

Everything lives in one SQLite file (`data/trading.db`, a Docker volume in
production). Schema changes ship as Alembic migrations that apply themselves
at container start. Notable tables: `signal` (one row per analysis, including
its grades), `signalreport` (the full analyst text, feeding `/ask`),
`transaction` / `papertransaction` (real and paper FIFO logs), `alert`
(watchdog dedupe + history), `papersnapshot` (the equity curve).
