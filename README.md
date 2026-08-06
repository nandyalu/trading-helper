# Trading Helper

Trading Helper is a self-hosted Discord bot and web dashboard.
It runs a multi-agent AI analysis ([TradingAgents](TradingAgents/README.md)) on the stocks you hold and watch.
It tracks every call the analysis makes, and it grades each call against reality and against a simple SPY buy-and-hold.
It also gives you tools to act on the calls with intent: paper trading, risk-based position sizing, intraday alerts, and a synced view of your real Webull account.

**Core idea: an AI signal has no value until you know its track record.**
Every part of this bot does one of three jobs: it generates signals, it measures signals, or it helps you act on signals that have earned your trust.

## What it does, in one paragraph

Every weekday, the bot analyzes your watchlist and holdings with a local LLM pipeline: market, news, sentiment, and fundamentals analysts debate the bull case against the bear case, then a trader and a risk team pick one decision — Buy, Overweight, Hold, Underweight, or Sell.
The bot records each decision with the price at signal time and a parsed time horizon, then grades the decision automatically once that time horizon arrives, in three ways: against reality, against SPY, and against its own price target.
You can follow any signal with one ✅ reaction to start paper trading, ask a question about it with `/ask`, and watch your win rate build in `/scorecard`.
Between analyses, a rule-based watchdog checks prices, volume, stops, and targets, and each morning the bot syncs your real Webull holdings in automatically.

## Documentation

| Page | What's in it |
|---|---|
| [Setup](docs/setup.md) | How to get a Discord bot token, Webull API keys, and Reddit OAuth2 credentials |
| [How it works](docs/overview.md) | Architecture, the signal lifecycle, the daily schedule, data sources |
| [Command reference](docs/commands.md) | Every Discord command, the ✅ reaction, and the scheduled posts |
| [The daily workflow](docs/trading-workflow.md) | A practical routine to work with the bot every day |
| [Finding your edge](docs/finding-your-edge.md) | How to use the scorecard, paper book, and sizing to make better trades |

## Quick start

1. Copy these values into `.env`: `DISCORD_BOT_TOKEN`, `DISCORD_CHANNEL_ID`, your Ollama settings, and (optional) `WEBULL_APP_KEY` and `WEBULL_APP_SECRET`. Set `WEBULL_SANDBOX=1` to use test keys. If you do not have these values yet, see [Setup](docs/setup.md) — it explains how to get each one, including the Reddit OAuth2 credentials.
2. Build the image. In VSCode, press **Ctrl+Shift+B**. Or run `docker build -t trading-bot:local .`
3. Deploy the image with a Docker Compose file, for example through [Dockge](https://github.com/louislam/dockge). Point `image:` at `trading-bot:local`, pass in the `.env` values from step 1, and mount a persistent volume at `/app/data`. The container applies database migrations by itself when it starts.
4. In Discord, run `/setchannel` in the channel where you want posts. Then run `/track` to add a ticker, or run `/webullsync` to pull in your real holdings.

## Honesty notes

- The bot never places real orders. Webull access is read-only.
- Signals come from a small local model (the default is qwen3 8B). Treat each signal as a structured second opinion, not as a fact — the scorecard exists to show you how much to trust it.
- Nothing here is financial advice. It is your account, and the decision is yours.
