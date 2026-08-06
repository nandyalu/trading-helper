# Setup: getting your credentials

Everything below is pasted into `.env` (or, for a deployed instance, the
Dockge stack's own `.env`/environment block — see this repo's `CLAUDE.md` for
that deployment's specifics if you're maintaining it directly). Only the
Discord token is required to run the bot at all; Webull and Reddit both
degrade gracefully when unset.

## Discord bot token + channel ID

Required for slash commands and scheduled posts. If you skip this, the app
still runs as a pure web dashboard (`bot/app.py` starts Discord only when
`DISCORD_BOT_TOKEN` is set).

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
   and click **New Application**. Name it anything (e.g. "Trading Helper").
2. Open the **Bot** tab → **Reset Token** → copy the value. This is
   `DISCORD_BOT_TOKEN`. No privileged intents (message content, presence,
   members) need to be enabled — the bot only uses slash commands and
   default intents.
3. Open **OAuth2 → URL Generator**. Under **Scopes**, check `bot` and
   `applications.commands`. Under **Bot Permissions**, check **Send
   Messages**, **Embed Links**, and **Add Reactions** (the ✅ paper-trading
   flow needs to react to its own messages).
4. Open the generated URL, pick your server, and authorize it.
5. In Discord, enable Developer Mode (User Settings → Advanced), right-click
   the channel you want the bot posting in, **Copy Channel ID**. This is
   `DISCORD_CHANNEL_ID` — or skip it and run `/setchannel` in that channel
   after the bot is online, which persists the same thing to the database.

```
DISCORD_BOT_TOKEN=...
DISCORD_CHANNEL_ID=...
```

## Webull API keys (optional)

Upgrades real-time quotes from yfinance's delayed feed to Webull's snapshot
endpoint, and enables `/webullsync` to pull in your real holdings. Read-only
— the bot never places orders through this. Unset, everything falls back to
yfinance automatically (`bot/quotes.py`).

1. Sign in at the [Webull OpenAPI developer portal](https://developer.webull.com/)
   with your regular Webull account.
2. Create an app to get an **App Key** and **App Secret** — these map to
   `WEBULL_APP_KEY` / `WEBULL_APP_SECRET`.
3. The portal issues both sandbox and production credentials. Start with
   sandbox (`WEBULL_SANDBOX=1`) to confirm quotes are flowing before
   switching to production keys with `WEBULL_SANDBOX` unset — sandbox and
   production use different endpoints and the two credential sets aren't
   interchangeable.
4. `/webullsync` (and the daily automatic sync) needs read access to your
   account/positions; quotes-only usage works with a narrower grant if the
   portal offers one.

```
WEBULL_APP_KEY=...
WEBULL_APP_SECRET=...
WEBULL_SANDBOX=1   # omit/unset once you've confirmed sandbox quotes work
```

## Reddit OAuth2 (optional)

The sentiment analyst always reads Reddit via a public RSS search feed with
no credentials needed — this works out of the box. Setting these two vars
switches it to Reddit's OAuth2 API instead
(`TradingAgents/tradingagents/dataflows/reddit.py`), which raises the rate
limit from RSS's occasional 429s to 100 requests/minute and adds
score/comment-count metadata to what the sentiment analyst sees. Purely an
upgrade — there's no behavior change until both vars are set.

1. Sign in at [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) and
   click **create another app...** at the bottom.
2. Pick **script** as the app type (not "web app" — script apps use the
   client-credentials grant this integration expects, no user login flow).
3. Name and description can be anything; the **redirect uri** field is
   required by the form but unused for script apps — `http://localhost` is
   fine.
4. After creating it, the client ID is the string under the app name (looks
   like `Ab12Cd34Ef56Gh`); the **secret** field is `REDDIT_CLIENT_SECRET`.

```
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...
```

## LLM provider

`LLM_PROVIDER` defaults to a self-hosted Ollama pool (no credentials needed
beyond running Ollama somewhere reachable — `OLLAMA_BASE_URL` points at it),
with Google Gemini available as a paid alternative via `GOOGLE_API_KEY` and
`LLM_PROVIDER=google`. This repo's maintainer docs (`CLAUDE.md`, not part of
this site) have provider-specific notes if you're running this stack
yourself.
