# Trading Helper

Trading Helper is a self-hosted Discord bot.
It runs a multi-agent AI analysis (TradingAgents, on a local LLM) on the stocks you hold and watch.
It tracks every call it makes, and it grades each call against reality and against a simple SPY buy-and-hold.
It gives you tools to act on the calls with intent.

**Core idea: an AI signal has no value until you know its track record.**
Every part of this bot does one of three jobs: it generates signals, it measures signals, or it helps you act on signals that have earned your trust.

## What it does

Every weekday, the bot analyzes your watchlist and holdings.
Four analysts — market, news, sentiment, and fundamentals — feed a bull-vs-bear debate.
A trader drafts a plan, and a risk team picks one decision: **Buy, Overweight, Hold, Underweight, or Sell**.
The bot records each decision with its price and time horizon, then grades the decision automatically once the time horizon arrives.
You can follow any signal with one ✅ reaction to start paper trading, ask a question about it with `/ask`, size it with an ATR-based stop through `/risk`, and watch your win rate build in `/scorecard`.
Between analyses, a rule-based watchdog checks prices, volume, stops, and targets, and each morning the bot syncs your real Webull holdings in automatically.

## Where to go

<div class="grid cards" markdown>

- **[How it works](overview.md)** — architecture, the signal lifecycle, the daily schedule, and data sources.
- **[The dashboard](dashboard.md)** — the web app: the overview, the chart with the analysis drawn on it, and the ticker timeline.
- **[Command reference](commands.md)** — every slash command, the ✅ reaction, and what posts automatically.
- **[The daily workflow](trading-workflow.md)** — a practical routine: morning context, intraday alerts, evening grades, weekly review.
- **[Finding your edge](finding-your-edge.md)** — the method: measure first, paper trade the strategy, and size each trade so it can fail.

</div>

## Ground rules

- The bot **never places real orders** — Webull access is read-only.
- Signals come from a small local model. Treat each signal as a structured second opinion, not as a fact. The scorecard exists to show you how much trust it has earned.
- Nothing here is financial advice.
