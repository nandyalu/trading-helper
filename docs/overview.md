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

## Where things are served

One process serves four things on the same port:

| Path | What |
|---|---|
| `/` | The dashboard. Start here. |
| `/docs` | These pages. |
| `/api/…` | The JSON API. |
| `/api/docs` | The interactive API reference, generated from the code. |

The API reference used to sit at `/docs` and hid this site completely, because FastAPI registers that route before the docs are mounted.

## Discord and the dashboard

The two are for different jobs, and neither is a lesser version of the other.

**Discord tells you when something happens.** A signal lands, a stop is reached, a target is touched — it arrives where you already are, and you can follow a signal into the paper book with one ✅.

**The dashboard tells you what is happening and what already happened.** It is where the price chart, the analysis, the signals, the alerts, and your own trades sit on one time axis, so you can see whether the bot's calls actually worked.

The dashboard needs no Discord account, and Discord needs no dashboard. Run either, or both.

## The signal lifecycle

1. **Born** — An analysis runs, from a scheduled sweep, an event trigger, or `/analyze`. The bot stores the decision, the full rationale, all analyst reports, the price at that moment, the parsed time horizon, and the trade plan (see below). The Discord embed gets a ✅ seeded on it.
2. **Actionable** — You can follow the signal as a paper trade with the ✅ reaction, ask questions about it with `/ask`, or act on it in your real account using the stop and size from the embed.
3. **Watched** — While the signal matures, the intraday watchdog sends an alert if the price touches the signal's target or reaches a stop level on a held position.
4. **Graded** — When the time horizon arrives, the bot fetches the full price window since the signal and grades it three ways:
   - **Absolute**: A Buy passes if the price rose at all. A Sell passes if the price fell. A Hold passes if the price stayed inside the horizon's band.
   - **vs SPY**: A Buy must have beaten SPY over the same window. A Sell must have lagged SPY — selling something that then underperformed the market was the right call. A Hold passes if alpha stayed inside the same band.
   - **Target**: Did the price touch the target at any point in the window (using the window's high and low, not just the endpoint)?
5. **Aggregated** — Every graded signal feeds `/scorecard` (win rates by decision type and ticker) and the weekly digest's rolling trend.

The vs-SPY grade exists because an absolute grade can mislead you in a trending market.
For example, a Buy that gained 1% while SPY gained 5% "passed" on the absolute grade, but it cost you money against the obvious alternative.

## The trade plan

Every signal carries five numbers beyond the decision itself, taken from the trader stage of the analysis:

| Field | What it means |
|---|---|
| Entry price | The level the trader proposed entering at |
| Stop loss | The level at which the thesis is wrong |
| Win probability | The model's own estimate that the thesis plays out, 0 to 100 |
| Risk / reward | Reward divided by risk, from the entry, stop, and target |
| Expected value | `p × rr − (1 − p)`, in R-multiples. Positive means the bet pays at the stated probability |

The last two are computed in Python from the levels, not asserted by the model, so they always agree with the levels shown beside them.
The win probability is the one number the model produces rather than derives, which makes it the one worth checking against your own scorecard before trusting.

Any of these can be absent — the model states them only when it has a view.
Absent is stored as null, never as zero, so a missing stop can never be read as a stop at $0.

When the trader names no stop on a Buy, the bot substitutes the same 2×ATR(14) level the sizing field shows, so every actionable Buy has an exit.

## Stop alerts

Two alerts watch a held position, and they answer different questions:

- **Thesis broken** (`signal_stop`) — price reached the level the analysis named. The decision to exit was made at entry; this is the reminder to carry it out.
- **Below your cost** (`stop_loss`) — price is a set percentage below what you actually paid. A backstop for the account, unrelated to any thesis, and the only one available for a position with no signal behind it.

Either can fire without the other, and each fires at most once, so neither hides the other.

## Trade horizon

Every analysis runs at one of two horizons, set with `/horizon` or on the settings page.
The horizon reaches the analysis prompts, so it changes what the model looks at, and it sets both grading parameters.

| | Swing | Position |
|---|---|---|
| Intended hold | 1 to 2 weeks | Around 6 months |
| Graded after | 14 days | 30 days |
| Hold passes within | ±4% | ±10% |
| The analysis weights | Near-term momentum, technical setup, immediate catalysts | Durable trends and fundamentals |
| Market analyst prefers | 10 EMA, MACD, RSI, Bollinger, ATR, VWMA, MFI | The full indicator set, including the 50 and 200 SMA |

The two bands differ because both scale with the length of the window.
A ±10% band over six months is reasonably tight; over two weeks it is so wide that almost every Hold passes, and the grade stops telling you anything.

Each signal records the horizon it was made under, so changing the setting never re-grades older signals by new rules.
It does mean a scorecard covering both horizons is comparing two different questions — start fresh after a switch.

## The analysis model

Every analysis runs on one LLM, chosen with `/model` or on the settings page, from whatever the configured endpoint has pulled.
The default is the model the stack's `TRADINGAGENTS_DEEP_THINK_LLM` names, so leaving the setting alone changes nothing.

Each signal records the model that produced it, and the scorecard grows a "By model" table as soon as a second model has resolved signals.
That table is the only reason to switch: a new model's win rate has to be readable next to the old one's, not blended into it.
Give it enough signals to mean something — a win rate under 20 resolved signals is noise whichever model produced it.

Two things go wrong more often than a bad answer does:

- **A model with a small context window fails partway through.** The analysis carries the whole tool-call history, and once that no longer fits, the reasoning loop stops terminating and the run dies with a `GraphRecursionError`. This is why the default is a custom `gemma4-e2b-96k` build rather than stock `gemma4:e2b` — same weights, 96k of context instead of 8k.
- **A model that answers in another language produces signals nothing can read.** The decision, the price levels, and the trade plan are all parsed out of the text. A rationale in Indonesian is not wrong, it is simply invisible to every stage after it.

Watch the logs after a switch, not just the win rate.

### What a run costs

Every signal also records how long its analysis took, how many LLM calls it made, and how many tokens went in and came back out.
The Discord embed carries a short version in its footer; the signal detail page shows all of it.

This is here for one decision: whether to keep self-hosting or move to a cloud provider.
The two are not billed in the same currency — a local model costs GPU time on hardware you already own, a hosted one costs tokens on an invoice, and providers charge several times more for output tokens than input ones.
Recording both, per run, from the provider's own accounting rather than an estimate, is what makes the comparison an arithmetic problem instead of a guess.

A run that was never measured stores nothing rather than zero, and shows nothing rather than a free run.

## The auto trader

A simulated Webull account the model trades on its own, inside a budget you set (default $1,000).
It runs on two triggers.

Each weekday at 13:35 UTC — five minutes after the US open — it decides on everything the previous evening's sweep produced.
And whenever an intraday analysis is triggered during market hours, by an unusual move or a volume spike, it decides again on the spot, at most once every 30 minutes.

The split is deliberate. The nightly sweep lands at 21:30 UTC, which is 17:30 in New York — nothing placed then can fill, and deciding its eight signals one at a time would hand the budget out first-come-first-served instead of weighing them against each other.
An intraday trigger is the opposite: it arrives while the market is open, and a move worth analyzing at 11:00 is worth nothing by the next morning.

**No order can reach a real account.** The app holds sandbox credentials only, and the order path refuses to run unless the sandbox flag is set, refuses any account that is not the simulated individual-cash one, and refuses an account whose number is not marked simulated.
The real-portfolio sync is switched off in sandbox mode for the same reason: it reconciles the real transaction log, and pointing it at the simulated account would write paper positions into it.

The model chooses what to buy and how much. The app only refuses orders that cannot be executed as stated — spending cash that is not there, selling shares that are not held, fractional shares.
An order that costs more than the cash left is dropped rather than resized, because resizing would quietly turn its decision into a different one.

Two details worth knowing when reading the page:

- **The simulated account holds far more than the budget.** Webull funds it with $1,000,000, so the budget is enforced by the app, from the agent's own filled orders, and the account's buying power is never consulted.
- **A pending order has moved no money.** Orders placed while the market is shut fill at the next open, and until they do the cash is still counted as available.

Why the open rather than straight after the sweep: the sweep runs at 21:30 UTC, which is 17:30 in New York, ninety minutes after the close. Webull rejects a market order outright at that hour, so an agent chained to the sweep would look healthy and never fill anything.

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
