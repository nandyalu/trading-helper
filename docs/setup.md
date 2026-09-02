# Setup: getting your credentials

You paste everything below into `.env`.
For a deployed instance, paste it into the Dockge stack's own `.env` or environment block instead — see this repo's `CLAUDE.md` for that deployment's specifics, if you maintain it directly.
Only the Discord token is required to run the bot at all.
Webull and Reddit both degrade gracefully when you leave them unset.

## Discord bot token + channel ID

This is required for the scheduled posts. There are no slash commands.
If you skip this step, the app still runs as a pure web dashboard — `backend/app.py` starts Discord only when `DISCORD_BOT_TOKEN` is set.

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) and click **New Application**. Name it anything, for example "The Allowance".
2. Open the **Bot** tab, click **Reset Token**, and copy the value. This is `DISCORD_BOT_TOKEN`. You do not need to enable any privileged intents (message content, presence, members) — the app only posts, using default intents.
3. Open **OAuth2 → URL Generator**. Under **Scopes**, check `bot`. Under **Bot Permissions**, check **Send Messages** and **Embed Links**. Nothing else is needed: the app posts and never reads.
4. Open the generated URL, pick your server, and authorize it.
5. In Discord, turn on Developer Mode (User Settings → Advanced). Right-click the channel where you want the bot to post, and click **Copy Channel ID**. This is `DISCORD_CHANNEL_ID`. Or skip this step and run `/setchannel` in that channel after the bot comes online — this saves the same value to the database.

```
DISCORD_BOT_TOKEN=...
DISCORD_CHANNEL_ID=...
```

## Webull API keys (optional)

**These are required, not optional.** The agent places its orders through Webull's sandbox, and it refuses to run without them. They also upgrade quotes from yfinance's delayed feed to Webull's snapshot endpoint.
Access is read-only — the bot never places orders through this.
If you leave this unset, everything falls back to yfinance automatically (`backend/services/quotes.py`).

1. Sign in at the [Webull OpenAPI developer portal](https://developer.webull.com/) with your regular Webull account.
2. Create an app to get an **App Key** and an **App Secret**. These map to `WEBULL_APP_KEY` and `WEBULL_APP_SECRET`.
3. The portal issues both sandbox and production credentials. Start with sandbox (`WEBULL_SANDBOX=1`) to confirm quotes are flowing. Then switch to production keys by unsetting `WEBULL_SANDBOX`. Sandbox and production use different endpoints, and you cannot use the two credential sets interchangeably.
4. The agent needs trading access on the **paper** account, plus read access to positions and order history. **Set `WEBULL_SANDBOX=1`.** The agent checks this itself and refuses every order without it.

```
WEBULL_APP_KEY=...
WEBULL_APP_SECRET=...
WEBULL_SANDBOX=1   # omit/unset once you've confirmed sandbox quotes work
```

## Reddit OAuth2 (optional — and no longer self-serve)

**Skip this.** Leave `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` unset and everything works.

The sentiment analyst reads Reddit through a public RSS search feed by default. That path needs no credentials and is what runs unless both variables are set (`TradingAgents/tradingagents/dataflows/reddit.py`).

### Why you probably cannot set these up

Reddit no longer lets you create an API app from [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps).
Under the [Responsible Builder Policy](https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy), every new application goes through an approval request first, and the process is aimed at products rather than personal tools.
If you try, you get a message pointing at that policy instead of a client ID.

Earlier versions of this page gave step-by-step instructions for creating a script app. Those steps no longer work.

### What you lose by skipping it

Very little:

| | RSS (default) | OAuth |
|---|---|---|
| Credentials | None | Approval required |
| Rate limit | About 1 request per minute per IP | 100 per minute |
| Post score and comment count | Not available | Included |

The rate limit is the only real difference, and the RSS path already handles it: a `429` backs off once, honors `Retry-After`, and then reports "no posts found" for that subreddit rather than failing the analysis. Occasional `429` warnings in the logs are expected, not a fault.

Reddit sentiment is also one input among four analysts, and the weakest of them for a 1-2 week trade. If Reddit and StockTwits both come back empty, the sentiment analyst falls back to a general web search.

### If you have credentials anyway

Set both variables and the OAuth path switches on by itself. Nothing else changes.

```
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...
```

## LLM provider

`LLM_PROVIDER` defaults to a self-hosted Ollama pool.
This needs no credentials beyond running Ollama somewhere reachable — set `OLLAMA_BASE_URL` to point at it.
Google Gemini is available as a paid alternative: set `GOOGLE_API_KEY` and `LLM_PROVIDER=google`.

`LLM_MODEL` sets which model the provider runs, but only as the starting value.
The settings page and `/model` change it afterwards without a redeploy, choosing from whatever the endpoint has pulled — see [the model section of the overview](overview.md#the-analysis-model) for what to watch when you switch.
If you run this stack yourself, this repo's maintainer docs (`CLAUDE.md`, not part of this site) have provider-specific notes.

## Logs

The app writes to `data/logs/trading-bot.log`, in the same volume as the database, and rotates at 5 MB across ten files — comfortably more than a month at the volume this produces.

It writes to standard output as well, so `docker logs trading-bot` still works. The file exists because that output does not survive the container: rebuild the image or recreate the stack and every line is gone.

That loss is not theoretical. Two positions were once found holding no exits, and the run that placed them had already been erased — so why the exits never rested had to be reconstructed from prices and ledger rows, instead of read from the line the code had already written.

To read it:

```bash
docker exec trading-bot tail -f /app/data/logs/trading-bot.log
docker exec trading-bot grep INTC /app/data/logs/trading-bot.log
```

Every logger is named `trading-bot.<module>`, so grepping for `trading-bot.agent` gives you the auto trader's decisions and nothing else.
