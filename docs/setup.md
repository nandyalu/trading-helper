# Setup: getting your credentials

You paste everything below into `.env`.
For a deployed instance, paste it into the Dockge stack's own `.env` or environment block instead — see this repo's `CLAUDE.md` for that deployment's specifics, if you maintain it directly.
Only the Discord token is required to run the bot at all.
Webull and Reddit both degrade gracefully when you leave them unset.

## Discord bot token + channel ID

This is required for slash commands and scheduled posts.
If you skip this step, the app still runs as a pure web dashboard — `backend/app.py` starts Discord only when `DISCORD_BOT_TOKEN` is set.

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) and click **New Application**. Name it anything, for example "Trading Helper".
2. Open the **Bot** tab, click **Reset Token**, and copy the value. This is `DISCORD_BOT_TOKEN`. You do not need to enable any privileged intents (message content, presence, members) — the bot only uses slash commands and default intents.
3. Open **OAuth2 → URL Generator**. Under **Scopes**, check `bot` and `applications.commands`. Under **Bot Permissions**, check **Send Messages**, **Embed Links**, and **Add Reactions** — the ✅ paper-trading flow needs to react to its own messages.
4. Open the generated URL, pick your server, and authorize it.
5. In Discord, turn on Developer Mode (User Settings → Advanced). Right-click the channel where you want the bot to post, and click **Copy Channel ID**. This is `DISCORD_CHANNEL_ID`. Or skip this step and run `/setchannel` in that channel after the bot comes online — this saves the same value to the database.

```
DISCORD_BOT_TOKEN=...
DISCORD_CHANNEL_ID=...
```

## Webull API keys (optional)

This upgrades real-time quotes from yfinance's delayed feed to Webull's snapshot endpoint, and it enables `/webullsync` to pull in your real holdings.
Access is read-only — the bot never places orders through this.
If you leave this unset, everything falls back to yfinance automatically (`backend/services/quotes.py`).

1. Sign in at the [Webull OpenAPI developer portal](https://developer.webull.com/) with your regular Webull account.
2. Create an app to get an **App Key** and an **App Secret**. These map to `WEBULL_APP_KEY` and `WEBULL_APP_SECRET`.
3. The portal issues both sandbox and production credentials. Start with sandbox (`WEBULL_SANDBOX=1`) to confirm quotes are flowing. Then switch to production keys by unsetting `WEBULL_SANDBOX`. Sandbox and production use different endpoints, and you cannot use the two credential sets interchangeably.
4. `/webullsync` (and the daily automatic sync) needs read access to your account and positions. If the portal offers a narrower grant for quotes-only use, that works too.

```
WEBULL_APP_KEY=...
WEBULL_APP_SECRET=...
WEBULL_SANDBOX=1   # omit/unset once you've confirmed sandbox quotes work
```

## Reddit OAuth2 (optional)

The sentiment analyst always reads Reddit through a public RSS search feed, and this needs no credentials — it works out of the box.
If you set these two variables, the bot switches to Reddit's OAuth2 API instead (`TradingAgents/tradingagents/dataflows/reddit.py`).
This raises the rate limit from RSS's occasional 429 errors to 100 requests per minute, and it adds score and comment-count metadata to what the sentiment analyst sees.
This is purely an upgrade — nothing changes until you set both variables.

1. Sign in at [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) and click **create another app...** at the bottom.
2. Pick **script** as the app type, not "web app". Script apps use the client-credentials grant this integration expects, with no user login flow.
3. The name and description can be anything. The form requires a **redirect uri** field, but script apps do not use it — `http://localhost` works fine.
4. After you create the app, the client ID is the string under the app name (it looks like `Ab12Cd34Ef56Gh`). The **secret** field is `REDDIT_CLIENT_SECRET`.

```
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...
```

## LLM provider

`LLM_PROVIDER` defaults to a self-hosted Ollama pool.
This needs no credentials beyond running Ollama somewhere reachable — set `OLLAMA_BASE_URL` to point at it.
Google Gemini is available as a paid alternative: set `GOOGLE_API_KEY` and `LLM_PROVIDER=google`.
If you run this stack yourself, this repo's maintainer docs (`CLAUDE.md`, not part of this site) have provider-specific notes.
