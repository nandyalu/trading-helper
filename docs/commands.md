# Command reference

All commands are Discord slash commands. Blocking work (analyses, price
fetches) runs off the main loop, so the bot stays responsive.

## Watchlist & analysis

| Command | What it does |
|---|---|
| `/track ticker:NVDA` | Add a ticker to the watchlist (covered by the daily sweep, watchdog, and earnings triggers). |
| `/untrack ticker:NVDA` | Stop tracking a ticker. |
| `/watchlist` | List tracked tickers. |
| `/analyze ticker:NVDA` | Run the full TradingAgents analysis right now (takes a few minutes on the local model). The result is recorded as a signal like any scheduled run. |
| `/ask ticker:NVDA question:…` | Ask a question about the ticker's **latest** analysis — answered by the local LLM from the stored analyst reports ("what did the bear case say?", "why hold instead of sell?"). |
| `/signals ticker:NVDA` | Recent signals and their outcomes (`ticker` optional). Resolved rows show the absolute grade and the vs-SPY grade. |
| `/scorecard ticker:NVDA` | The track record: absolute and vs-SPY win rates, average alpha, price-target hit rate, broken down by decision type and ticker (`ticker` optional). |

## Real positions

| Command | What it does |
|---|---|
| `/buy ticker price quantity` | Record a real buy. Also auto-tracks the ticker. |
| `/sell ticker price quantity` | Record a real sell (validates you hold enough; reports realized P&L). |
| `/positions` | Open positions with cost basis, current price, unrealized and realized P&L. |
| `/portfolio` | The full dashboard: per-position weights, concentration warnings (≥30% of the book), totals, and open-book performance vs putting the same dollars into SPY on the same dates. |
| `/webullsync` | Pull your real Webull holdings now: auto-watchlists every held equity and imports/reconciles positions (also runs automatically each weekday at 12:35 UTC). Bot-side positions missing at Webull are flagged, never auto-sold. |

## Paper trading

| Command | What it does |
|---|---|
| **✅ reaction** | Not a command — click the ✅ the bot seeds on any analysis embed to execute that signal as a paper trade at the *current* price. Buy/Overweight opens a lot; Sell/Underweight closes the whole position (no shorting); Hold does nothing. One execution per signal. |
| `/paper` | The paper portfolio: positions, P&L, and a Performance section (equity-curve sparkline, max drawdown, vs SPY). |
| `/paperclose ticker:NVDA` | Close an open paper position at the current price without waiting for a Sell signal. |
| `/papersize amount:1000` | Set the notional dollars each paper buy uses (default $1,000). |

## Risk & sizing

| Command | What it does |
|---|---|
| `/risk equity:25000 risk_pct:1` | Configure sizing suggestions. With equity set, every Buy embed shows a 2×ATR(14) stop **and** a share count that risks `risk_pct`% of equity between entry and stop (capped at 100% of equity). Without it, only the stop is shown. Run with no arguments to view current settings. |

## Alerts & automation

| Command | What it does |
|---|---|
| `/alertconfig move_pct:5 stop_pct:10 volume_mult:2 enabled:True` | View or tune the intraday watchdog. All arguments optional; no arguments shows current settings. |
| `/dailysweep enabled:False` | Turn the fixed 21:30 UTC whole-watchlist sweep off (or on). With it off, analyses run only on triggers — earnings, big moves, volume spikes — and `/analyze`. Signal grading still runs nightly either way. |
| `/regime` | The market regime snapshot on demand (also posts each weekday at 12:45 UTC). |
| `/digest` | The weekly digest on demand (also posts Fridays at 23:00 UTC). |
| `/setchannel` | Make the current channel the destination for all scheduled posts (requires Manage Server). |

## What posts automatically

| When (UTC, weekdays) | Post |
|---|---|
| 12:35 | Webull sync summary — only when something changed |
| 12:45 | 🟢/🟡/🔴 regime line |
| 13:00 | "📅 X reports earnings…" + a fresh analysis, for tickers reporting within 2 days |
| every 15 min, market hours | 📊 big moves, 📊 unusual volume, 🛑 stop breaches, 🎯 target touches — each at most once per day (targets once ever per signal), plus ⚡ triggered analyses |
| 21:30 | Graded signals ("PASS/FAIL … vs SPY … target hit"), then the watchlist sweep's new analyses |
| Fri 23:00 | 🗞️ weekly digest |
