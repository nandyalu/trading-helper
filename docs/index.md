# Trading Helper

A self-hosted Discord bot that runs a multi-agent AI analysis
(TradingAgents on a local LLM) over the stocks you hold and watch, tracks
every call it makes, grades those calls against reality — and against just
buying SPY — and gives you the tools to act on the ones that earn trust.

The core idea: **an AI signal is worthless until you know its track record.**
Everything in this bot exists either to generate signals, to measure them,
or to help you act on them deliberately.

## What it does

Every weekday the bot analyzes your watchlist and holdings: four analysts
(market, news, sentiment, fundamentals) feed a bull-vs-bear debate, a trader
drafts a plan, and a risk team settles on **Buy / Overweight / Hold /
Underweight / Sell**. Each decision is recorded with its price and time
horizon, then automatically graded when the horizon arrives. You can follow
any signal with one ✅ reaction (paper trading), interrogate it with `/ask`,
size it with an ATR-based stop via `/risk`, and watch the aggregate win rate
build in `/scorecard`. Between analyses, a rule-based watchdog monitors
prices, volume, stops, and targets; your real Webull holdings sync in
automatically each morning.

## Where to go

<div class="grid cards" markdown>

- **[How it works](overview.md)** — architecture, the signal lifecycle, the
  daily schedule, and data sources.
- **[Command reference](commands.md)** — every slash command, the ✅
  reaction, and what posts automatically.
- **[The daily workflow](trading-workflow.md)** — a practical routine:
  morning context, intraday alerts, evening grades, weekly review.
- **[Finding your edge](finding-your-edge.md)** — the method: measure first,
  paper trade the strategy, size like every trade can fail.

</div>

## Ground rules

- The bot **never places real orders** — Webull access is read-only.
- Signals come from a small local model. They are a structured second
  opinion, not an oracle; the scorecard exists to tell you how much trust
  they've earned.
- Nothing here is financial advice.
