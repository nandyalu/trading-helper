# Command reference

All commands are Discord slash commands.
The bot runs blocking work, like analyses and price fetches, off the main loop.
This keeps the bot responsive.

## Watchlist & analysis

| Command | What it does |
|---|---|
| `/track ticker:NVDA` | Add a ticker to the watchlist. The daily sweep, the watchdog, and the earnings check all cover it. |
| `/untrack ticker:NVDA` | Remove a ticker from the watchlist. |
| `/watchlist` | List tracked tickers. |
| `/analyze ticker:NVDA` | Run the full TradingAgents analysis right now. This takes a few minutes on the local model. The bot records the result as a signal, the same as any scheduled run. |
| `/ask ticker:NVDA question:…` | Ask a question about the ticker's **latest** analysis. The local LLM answers from the stored analyst reports — for example, "What did the bear case say?" or "Why hold instead of sell?" |
| `/signals ticker:NVDA` | Show recent signals and their outcomes (the `ticker` argument is optional). Resolved rows show the absolute grade and the vs-SPY grade. |
| `/scorecard ticker:NVDA` | Show the track record: absolute and vs-SPY win rates, average alpha, and the price-target hit rate, broken down by decision type and ticker (the `ticker` argument is optional). |

## Real positions

| Command | What it does |
|---|---|
| `/buy ticker price quantity` | Record a real buy. This also adds the ticker to the watchlist automatically. |
| `/sell ticker price quantity` | Record a real sell. The bot checks that you hold enough shares, and it reports the realized P&L. |
| `/positions` | Show your open positions: cost basis, current price, and unrealized and realized P&L. |
| `/portfolio` | Show the full dashboard: per-position weights, concentration warnings (at 30% of the book or more), totals, and open-book performance against putting the same dollars into SPY on the same dates. |
| `/webullsync` | Pull in your real Webull holdings now. The bot adds every held equity to the watchlist, and it imports and reconciles positions. This also runs automatically each weekday at 12:35 UTC. If a bot-side position is missing at Webull, the bot flags it — it never sells the position for you. |

## Paper trading

| Command | What it does |
|---|---|
| **✅ reaction** | This is not a command. Click the ✅ that the bot adds to any analysis embed to execute that signal as a paper trade, at the *current* price. A Buy or Overweight opens a lot. A Sell or Underweight closes the whole position (no shorting). A Hold does nothing. Each signal executes only once. |
| `/paper` | Show the paper portfolio: positions, P&L, and a Performance section with an equity-curve sparkline, the max drawdown, and the result against SPY. |
| `/paperclose ticker:NVDA` | Close an open paper position at the current price, without waiting for a Sell signal. |
| `/papersize amount:1000` | Set the dollar amount each paper buy uses (the default is $1,000). |

## Risk & sizing

| Command | What it does |
|---|---|
| `/risk equity:25000 risk_pct:1` | Set up sizing suggestions. If you set `equity`, every Buy embed shows a 2×ATR(14) stop and a share count. The share count risks `risk_pct`% of your equity between entry and stop, capped at 100% of equity. If you do not set `equity`, the embed shows only the stop. Run the command with no arguments to view your current settings. |

## Alerts & automation

| Command | What it does |
|---|---|
| `/alertconfig move_pct:5 stop_pct:10 volume_mult:2 enabled:True` | View or tune the intraday watchdog. All arguments are optional. Run with no arguments to view your current settings. |
| `/dailysweep enabled:False` | Turn the fixed 21:30 UTC watchlist sweep off, or back on. If it is off, analyses run only from triggers: earnings, big moves, volume spikes, and `/analyze`. Signal grading still runs every night, either way. |
| `/regime` | Show the market regime snapshot now. It also posts automatically each weekday at 12:45 UTC. |
| `/digest` | Show the weekly digest now. It also posts automatically on Fridays at 23:00 UTC. |
| `/setchannel` | Set the current channel as the destination for all scheduled posts. This needs the Manage Server permission. |

## What posts automatically

| When (UTC, weekdays) | Post |
|---|---|
| 12:35 | Webull sync summary, posted only when something changed |
| 12:45 | 🟢/🟡/🔴 regime line |
| 13:00 | "📅 X reports earnings soon" plus a fresh analysis, for tickers that report within 2 days |
| every 15 min, market hours | 📊 big moves, 📊 unusual volume, 🛑 stop breaches, and 🎯 target touches. Each alert posts at most once a day (a target alert posts once ever, per signal). Plus ⚡ triggered analyses |
| 21:30 | Graded signals ("PASS/FAIL, vs SPY, target hit"), then new analyses from the watchlist sweep |
| Fri 23:00 | 🗞️ weekly digest |
