# The dashboard

The web dashboard is where you look at what happened. Discord is where you hear that something happened. See [How it works](overview.md) for why they are separate.

Open it at the root of whatever host and port the container serves, for example `http://localhost:8080/`.

## Overview

The landing page answers one question: is there anything I should do?

**Needs a decision** is the only block on the page that is a call to action, so it is the only one with a colored border. It lists two things:

- A ticker you hold whose newest analysis says get out.
- A stop that was reached, a target that was touched, or a position that fell below your cost — within the last three days.

A big move or a volume spike is information, not a prompt, so those stay off this list and on the Alerts page. When there is nothing to decide, the page says so plainly rather than showing an empty box.

Below that: your real and paper book values, the signal win rate, and how many signals are still maturing. The win rate shows a raw count instead of a percentage until about 20 signals have resolved, because three wins in four reads as 75% and means nothing.

**New opportunities** lists Buy signals from the last week on tickers you do not already hold, with the model's confidence and the expected value of the bet. **Never analyzed** lists watchlisted tickers with no signal yet.

## Ticker detail

This is the page the rest of the app exists to fill in.

At the top, the numbers that decide what to do next: your position, the stop, the target, and the model's confidence. The stop and target show how far away they are — and say "breached" or "reached" once price has crossed them, rather than reporting a distance that no longer means anything.

### The chart

The price chart carries the analysis on it, because a price chart on its own answers almost nothing. You can see that a stock fell; you cannot see whether the bot called it, whether you were holding, or whether an alert fired.

| Mark | Meaning |
|---|---|
| Green arrow below the bar | A Buy or Overweight signal |
| Red arrow above the bar | A Sell or Underweight signal |
| Yellow circle | A Hold signal |
| Blue square | A trade you recorded. A 📄 prefix means the paper book |
| Purple dot | A watchdog alert |
| Red dashed line | The stop level from the signal in force |
| Green dashed line | Its price target |

Entries sit below the bar and exits above it, so a Buy and the trade that followed it do not overlap. The stop and target lines come from the **newest** signal only — an older signal's levels were superseded, not merely graded, and drawing them would put a stale line on the chart.

The chart opens on 30 days, which is the window a swing signal is actually judged over. Use the range buttons for more context; the chart always fits the full range you asked for.

### What happened

Signals, alerts, and your trades in one list, newest first. They live in three different tables and carry different fields; putting them in three lists would leave you to interleave them by eye.

Each signal row shows the entry price, the stop, the target, and the confidence, plus a pass or fail badge once it has been graded. Click through for the full rationale and every analyst report.

### Positions and lots

Three books can hold the same stock: your real account, the paper book, and the auto trader.
All three now appear at the top of the page, so a position is never invisible on the page about the stock it is in.

The auto trader's tile is the one that carries **resting stop** and **resting target** beside it.
Those are different numbers from the stop and target above them, and the distinction matters: the signal's levels are what the analysis proposed, while the resting ones are orders sitting at the broker that will execute whether or not this app is running.
They disagree often — a level the app discarded, an ATR-derived fallback, or a bracket the broker refused.

When the auto trader holds a stock with **nothing** resting under it, the page says so in a warning rather than leaving you to notice two empty cells.

**Positions taken** lists every lot bought in this ticker, in any book: entry price and date, quantity, exit price and date, days held, and the profit or loss.
An open lot shows no exit and no profit, because its result is not decided yet, but the days held keep counting.
Selling part of a position splits it — the shares sold get their own result and the rest stays open — and the matching is the same FIFO walk the position tiles use, so the two can never disagree about the same shares.

### Ask, and record a trade

**Ask** puts a question to the model about the stored analysis for this ticker. It answers only from the saved reports, and says so when they do not cover your question.

**Record a trade** logs what you did in your broker. The bot never places orders. Logging keeps your position, the stop alerts, and the scorecard tied to what actually happened. Webull holdings sync in on their own; this is for anything else.

## Alerts

Every watchdog alert, filterable by type. The two stop alerts read differently on purpose — "Thesis broken" means price reached the level the analysis named, "Below your cost" means price fell a set percentage under what you paid. Either can happen without the other.

## The rest

| Page | What it is for |
|---|---|
| Tickers | Add and remove watchlist entries, run an analysis across all of them, and follow screened candidates |
| Signals | Every signal, filterable by pending or resolved |
| Paper | The paper book, its equity curve against SPY, and per-position closes |
| Auto trader | The simulated account the model trades on its own: budget, cash, its equity curve, holdings with the stop and target actually resting at the broker, every position taken with its entry, exit and profit, and every order with the reason it gave |
| Portfolio | The real book, weights, and concentration warnings |
| Scorecard | Win rates overall, by decision, by model, and by ticker, plus whether the model's stated confidence matches how often it is right |
| Digest | The weekly wrap-up |
| Regime | VIX, SPY against its 200-day average, and the yield curve |
| Settings | Trade horizon, analysis model, sizing limits, alert thresholds, the daily sweep, and the auto trader |
