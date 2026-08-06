# Trading Helper

A self-hosted Discord bot that runs a multi-agent AI analysis
([TradingAgents](TradingAgents/README.md)) over the stocks you hold and watch,
tracks every call it makes, grades those calls against reality (and against
just buying SPY), and gives you the tools to act on them deliberately: paper
trading, risk-based position sizing, intraday alerts, and a synced view of
your real Webull account.

The core idea: **an AI signal is worthless until you know its track record.**
Everything in this bot exists either to generate signals, to measure them, or
to help you act on the ones that have earned trust.

## What it does, in one paragraph

Every weekday the bot analyzes your watchlist and holdings with a local LLM
pipeline (market, news, sentiment, and fundamentals analysts debating bull vs
bear, then a trader and risk team deciding: Buy / Overweight / Hold /
Underweight / Sell). Each decision is recorded with the price at signal time
and a parsed time horizon, then automatically graded when that horizon
arrives — absolutely, against SPY, and against its own price target. You can
follow any signal with one ✅ reaction (paper trading), interrogate it with
`/ask`, and watch your aggregate win rate build in `/scorecard`. Between
analyses, a rule-based watchdog watches prices, volume, stops, and targets;
your real Webull holdings sync in automatically each morning.

## Documentation

| Page | What's in it |
|---|---|
| [Setup](docs/setup.md) | Getting a Discord bot token, Webull API keys, and Reddit OAuth2 credentials |
| [How it works](docs/overview.md) | Architecture, the signal lifecycle, the daily schedule, data sources |
| [Command reference](docs/commands.md) | Every Discord command, the ✅ reaction, and the scheduled posts |
| [The daily workflow](docs/trading-workflow.md) | A practical routine for working with the bot day to day |
| [Finding your edge](docs/finding-your-edge.md) | Using the scorecard, paper book, and sizing to make better trades |

## Quick start

1. Copy `.env` values: `DISCORD_BOT_TOKEN`, `DISCORD_CHANNEL_ID`, Ollama
   settings, and optionally `WEBULL_APP_KEY` / `WEBULL_APP_SECRET`
   (`WEBULL_SANDBOX=1` for test keys). Don't have these yet? See
   [Setup](docs/setup.md) for how to obtain each one, including the newer
   Reddit OAuth2 credentials.
2. Build the image — VSCode: **Ctrl+Shift+B**, or
   `docker build -t trading-bot:local .`
3. Deploy with a Docker Compose file (e.g. via [Dockge](https://github.com/louislam/dockge))
   pointing `image:` at `trading-bot:local` and passing the `.env` values above
   plus a persistent volume mounted at `/app/data`. Database migrations apply
   themselves at container start.
4. In Discord: `/setchannel` in the channel you want posts, then `/track` a
   ticker or `/webullsync` to pull in your real holdings.

## Honesty notes

- The bot never places real orders. Webull access is read-only.
- Signals come from a small local model (default qwen3 8B). Treat them as a
  structured second opinion, not an oracle — that's what the scorecard is for.
- Nothing here is financial advice; it's your account and your judgment.
