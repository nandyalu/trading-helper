# The Allowance

**One question, asked in public: what does an autonomous AI agent do with $10,000?**

*The Allowance* — money given to someone to spend as they choose, inside rules they did not set. That is the setup exactly.

The Allowance is a self-hosted experiment. An agent gets a simulated brokerage account, a fixed budget, and a bill for every piece of research it orders. It decides what to study, what to buy, what to sell, and when to give up on a name. Nobody helps it.

A web dashboard and a Discord channel report what it did.

**No real money is involved and no order can reach a real account.** Webull access is the sandbox only.

## What runs each weekday

The morning sweep analyses every ticker on the watchlist and charges the agent for each one. Four analysts — market, news, sentiment, and fundamentals — feed a bull-versus-bear debate. A trader drafts a plan, and a risk team picks one decision: **Buy, Overweight, Hold, Underweight, or Sell**.

Five minutes after the US open the agent reads its book, its signals, its own track record and the bill it is running up, and answers with orders.

The app records each decision with its price and time horizon, then grades it automatically once that horizon arrives — against reality, against SPY, and against the analysis's own price target.

## Nobody can nudge it

There is no button that adds a ticker, starts an analysis, or places a trade. There are no Discord commands.

A control that lets a person nudge the book puts a second decision-maker in the record. Afterwards, nothing can tell which one produced a result — and a record with two authors is not evidence about either.

Changes go in the journal first, with a date and a reason, and then get made by hand.

## Where to go

<div class="grid cards" markdown>

- **[How it works](overview.md)** — architecture, the signal lifecycle, the daily schedule, and data sources.
- **[The dashboard](dashboard.md)** — the web app: the overview, the chart with the analysis drawn on it, and the record of every decision pass.
- **[What Discord posts](discord.md)** — the scheduled posts, the alerts, and the one alert that asks for a person.
- **[The daily workflow](trading-workflow.md)** — how to read the experiment: the decision pass, the grades, the weekly review.
- **[Finding your edge](finding-your-edge.md)** — how to read the scorecard without fooling yourself.

</div>

## Ground rules

- **The app never places a real order.** Every order goes to Webull's sandbox, and the agent refuses to run at all when the app holds production credentials.
- Signals come from a small local model. Treat each one as a structured second opinion, not as a fact.
- **A single analysis is one sample.** The model runs at temperature 1, so the same ticker on the same day has returned opposite decisions.
- Nothing here is financial advice.
