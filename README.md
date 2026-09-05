# The Allowance

**One question, asked in public: what does an autonomous AI agent do with $10,000?**

*The Allowance* — money given to someone to spend as they choose, inside rules they did not set. That is the setup exactly.

The Allowance is a self-hosted experiment. An agent gets a simulated brokerage account, a fixed budget, and a bill for every piece of research it orders. It decides what to study, what to buy, what to sell, and when to give up on a name. Nobody helps it. A web dashboard and a Discord channel report what it did.

The agent runs a multi-agent AI analysis ([TradingAgents](TradingAgents/README.md)) on the stocks it chooses to watch. The app records every call that analysis makes and grades each one against reality, against a SPY buy-and-hold, and against the analysis's own price target.

**No real money is involved and no order can reach a real account.** Webull access is the sandbox only.

## Nobody can nudge it, and that is the point

There is no button that adds a ticker, starts an analysis, or places a trade. There are no Discord commands. The app used to have twenty-three of them and they are all gone.

A control that lets a person nudge the book puts a second decision-maker in the record. Afterwards, nothing can tell which one produced a result — and a record with two authors is not evidence about either.

When something needs correcting, the route is deliberate: write down what changed and why in [JOURNEY.md](JOURNEY.md), then make the correction by hand. That costs a few minutes and leaves the record readable.

## What happens each day

| Time (UTC) | What runs |
|---|---|
| 11:00 | The morning sweep analyses every ticker on the watchlist and charges the agent for each one |
| 12:45 | The market regime line — VIX, SPY against its 200-day average, the yield curve |
| 13:00 | Earnings check, which analyses anything reporting soon |
| **whenever it asked** | **The agent sets every one of its own passes.** It names the next time, and that time becomes a real alarm. Minimum 5 minutes, maximum 4 days, any hour |
| 20:55 | A last pass before the close, if it has not just had one |
| every 15 min | The watchdog: big moves, volume spikes, breached stops, reached targets |
| 21:30 | Grading, then the journal is rewritten |

The sweep decides overnight and the agent acts at the next open. That is not an accident of scheduling: Webull rejects a market order in the evening outright, so an agent wired to trade straight after the sweep would look healthy and never fill an order.

## What the agent may do

It answers with a list of actions, and Python refuses what cannot be executed as stated. **It never resizes.** Shrinking an order would quietly turn the agent's decision into a different one, and the record would then describe a strategy nobody chose.

- **buy** and **sell** — whole shares, long only, never more cash than it holds. A buy goes out as a bracket: the entry with a stop and a take-profit attached, so the shares are never held with nothing under them.
- **adjust** — move the stop or target on something it already holds.
- **research** — pay $0.05 to have a candidate analysed. The answer usually comes with the next morning's sweep, which is the honest shape: an analyst does not hand over a report the moment you ask. A stock that moves sharply while the market is open is analysed on the spot instead, so that one can come back the same day.
- **untrack** — stop watching a name, and stop paying for it. It cannot untrack something it holds.
- **next_wakeup** — say when to be asked again. **This is the only thing that schedules the agent.** It may name any hour, including before the open, so it can have the morning's analyses ready. Waking costs nothing, so the agent is shown what its recent wakeups produced rather than charged for them.

## Documentation

| Page | What's in it |
|---|---|
| [Running it yourself](docs/deploying.md) | **Start here to deploy it.** Prerequisites, every environment variable, and what goes wrong |
| [Credentials](docs/setup.md) | How to get each one, and what happens if you skip it |
| [How it works](docs/overview.md) | Architecture, the signal lifecycle, the daily schedule, data sources |
| [The site](docs/dashboard.md) | What each page shows, and how to publish it |
| [What Discord posts](docs/discord.md) | The scheduled posts and the alerts |
| [The daily workflow](docs/trading-workflow.md) | How to read the experiment |
| [Finding your edge](docs/finding-your-edge.md) | How to read the scorecard without fooling yourself |
| [The journey](JOURNEY.md) | Every change to the agent, when, and why |
| [Model training](docs/model-training.md) | What it would take to make a small model reliable here |

## Quick start

1. Copy these into `.env`: `WEBULL_APP_KEY`, `WEBULL_APP_SECRET`, **`WEBULL_SANDBOX=1`**, and your model settings. Optionally `DISCORD_WEBHOOK_URL` for notifications. The agent refuses to trade without the sandbox flag. See [Credentials](docs/setup.md).
2. Build the image. In VSCode, press **Ctrl+Shift+B**. Or run `docker build -t trading-experiment:local .`
3. Deploy it with a Docker Compose file. `dockge/trading-experiment.compose.yaml` is the working template, with every setting commented. The container applies its own database migrations at startup.
4. Open the dashboard and switch the agent on in Settings. It starts with an empty watchlist and buys its first research at the next decision pass.

**[Running it yourself](docs/deploying.md) has the full version**, including how to run without a GPU pool and how to publish the site read-only.

## Honesty notes

- **The app never places a real order.** Every order goes to Webull's sandbox, and the agent refuses to run at all when the app holds production credentials.
- Signals come from a small local model. Treat each one as a structured second opinion, not as a fact — the scorecard exists to show how much to trust it.
- **A single analysis is one sample.** The model runs at temperature 1, so the same ticker on the same day has returned opposite decisions. The scorecard's by-model breakdown is the only honest way to compare two models.
- Nothing here is financial advice.
