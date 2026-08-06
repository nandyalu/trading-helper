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

Two kinds of intelligence run here, and the bot keeps them separate on purpose.

- **The LLM pipeline** (TradingAgents) runs the analysis. This work is expensive and slow. Four analysts — market/technical, news, sentiment, and fundamentals — feed a bull-vs-bear research debate. A trader drafts a plan, and a risk team picks one of five decisions: **Buy, Overweight, Hold, Underweight, Sell**. The rationale usually includes a price target and a time horizon.
- **Rule-based logic** handles everything that must be fast, cheap, and reliable: it grades outcomes, watches prices intraday, classifies the market regime, computes position sizes, and reconciles your broker account. No model is involved, so none of this can hallucinate.

## The signal lifecycle

1. **Born** — An analysis runs, from a scheduled sweep, an event trigger, or `/analyze`. The bot stores the decision, the full rationale, all analyst reports, the price at that moment, and the parsed time horizon. The Discord embed gets a ✅ seeded on it.
2. **Actionable** — You can follow the signal as a paper trade with the ✅ reaction, ask questions about it with `/ask`, or act on it in your real account using the suggested stop and size from the embed.
3. **Watched** — While the signal matures, the intraday watchdog sends an alert if the price touches the signal's target or breaches a stop level on a held position.
4. **Graded** — When the time horizon arrives (30 days by default, if the rationale did not specify one), the bot fetches the full price window since the signal and grades it three ways:
   - **Absolute**: A Buy passes if the price rose at all. A Sell passes if the price fell. A Hold passes if the price stayed within ±10%.
   - **vs SPY**: A Buy must have beaten SPY over the same window. A Sell must have lagged SPY — selling something that then underperformed the market was the right call. A Hold passes if alpha stayed within ±10%.
   - **Target**: Did the price touch the target at any point in the window (using the window's high and low, not just the endpoint)?
5. **Aggregated** — Every graded signal feeds `/scorecard` (win rates by decision type and ticker) and the weekly digest's rolling trend.

The vs-SPY grade exists because an absolute grade can mislead you in a trending market.
For example, a Buy that gained 1% while SPY gained 5% "passed" on the absolute grade, but it cost you money against the obvious alternative.

## The daily schedule (all times UTC, weekdays)

| Time | What happens |
|---|---|
| 12:35 | **Webull sync** — mirrors real holdings into the watchlist and positions (posts only when something changes) |
| 12:45 | **Regime snapshot** — VIX, SPY vs its 200-day average, and the 10Y–3M yield spread, shown as 🟢/🟡/🔴 |
| 13:00 | **Earnings check** — runs a fresh analysis for any tracked ticker that reports within 2 days |
| 13:30–20:00 (9:30–16:00 ET) | **Watchdog**, every 15 minutes — flags a move of 5% or more, volume at 2x the average or more, a stop breach, or a target touch. Big moves and volume spikes also trigger an immediate analysis, at most one per ticker per day |
| 21:30 | **Daily run** — grades and posts matured signals, snapshots the paper book, then sweeps the full watchlist (unless `/dailysweep` turned this off) |
| Fri 23:00 | **Weekly digest** — the week's outcomes, the win-rate trend, alerts, and both books |

## Data sources

- **Webull OpenAPI** (when keys are configured): gives real-time snapshot quotes for every "price right now" check — paper fills, alert checks, portfolio values. This needs a stock-quotes market-data subscription on the account. Without that subscription, or after any failure, the bot falls back to yfinance automatically. Webull also provides the read-only Trade API for the account sync. The bot **never places orders**.
- **yfinance**: provides all historical bars (evaluation windows, ATR, the 200-day average, volume baselines), the earnings calendar, the VIX and treasury-yield indices, and the quote fallback.

## Storage

Everything lives in one SQLite file, `data/trading.db` (a Docker volume in production).
Schema changes ship as Alembic migrations, and these migrations apply themselves at container start.
Notable tables: `signal` (one row per analysis, including its grades), `signalreport` (the full analyst text, feeding `/ask`), `transaction` and `papertransaction` (real and paper FIFO logs), `alert` (watchdog dedupe and history), and `papersnapshot` (the equity curve).
