# Plan — the autonomous analyst

A second, separate experiment. The current auto trader is measured on *decisions given a fixed watchlist*. This one is measured on **what to look at, what to buy, and when to exit, under a budget that research draws from** — which is most of what an analyst actually does, and a far more interesting thing to be right or wrong about.

Written down 2026-08-25, from a design conversation. Nothing here is built yet. The prerequisites at the end must be answered before implementation starts, because two of them can invalidate the design.

## The idea in one paragraph

Give the agent $10,000 and charge it a fixed $0.10 for every analysis it runs. It always analyses what it holds, and it chooses what else to look at from a curated candidate list. It decides what to buy, when to exit, and what is worth researching in the first place. It runs against a real Webull sandbox account and is never told that the account is simulated.

## What is settled

### The economics

- **Budget $10,000**, against the current agent's $1,000.
- **A fixed price per analysis**, regardless of which model ran it. A fixed price keeps the comparison stable while the model question is still open. Measured at 4 rounds it is **$0.1347 on Flash-Lite and $0.0066 in local electricity** — 20x apart — so the fixed price is a deliberate choice about scarcity rather than a passthrough of cost. $0.13-0.15 charges roughly what the vendor path costs; $0.10 is a round number slightly under it. Either is defensible; pretending it is "the cost" is not.
- At 9 analyses a day that is $226.80 a year, a **2.27% hurdle** on $10,000. At 15 a day it is 3.8%. Both leave room; on the current $1,000 budget the same price would be a 22.7% hurdle, which is not a constraint but a rigged game.
- **The baselines pay too.** The mechanical signal-follower consumes the same analyses, so it is charged for them. SPY buy-and-hold consumes none and pays nothing. Charging the agent alone would handicap it against its own yardstick and quietly break the one measurement the app exists for.

### What is charged

- **Held tickers are analysed every day, and charged.** The model chose to buy them, so it owns the cost of finding the exit. This makes fixed costs scale with position count, so breadth has to justify itself — a realistic and healthy pressure on a small book.
- Watch for, but do not design around, the mild sell bias this creates: exiting a position stops its daily charge.

### Ticker selection

- **A curated menu, never free-form.** A model naming its own tickers invents symbols, picks illiquid junk, and reaches things with no price data.
- The menu comes from `candidates.py`, which already exists: Webull's screener filtered to liquid names over $5 with a million shares traded, plus a pump filter excluding anything up more than 30% on the day. **That filter is not optional** — a raw screen once returned a stock up 927%, and the price floor alone does not catch it, because the pump is what lifted the price over the floor.
- Watchdog movers are a reasonable second source.
- Each morning the agent sees: its holdings, its cash, the price of an analysis, and a menu of roughly 15-20 screened candidates with price, volume and day change. It picks. Python enforces the spend, exactly as it enforces the trading budget today.

### The wall-clock limit

Money does not model time. Twenty analyses is hours of GPU, and the agent decides at 13:35 UTC while the sweep has to finish before the open. **A hard cap on analyses per day is needed regardless of what the agent can afford** — 12-15 is the starting guess, and it depends on the GPU expansion.

### Deployment

**A second deployment of the same codebase, not a fork.** The shared machinery is large — bar cache, listings, quotes, sandbox_broker, agent_book, ticker_book, llm_cost, calibration, scorecard, the TradingAgents integration, the scheduler, every migration — and a fork means fixing each of them twice, forever. Branches diverge and stop merging.

What separates is the *deployment*, which is what isolation actually requires:

- its own container, volume, database and Discord channel
- the idle `INDIVIDUAL_MARGIN` account `DEM67245`, funded with $1,000,000 and currently untouched — the live agent uses `INDIVIDUAL_CASH` `DEM8XW69`
- an `AGENT_ONLY` mode that hides the real-book and paper-book pages

Fork later if the experiment develops a reason to diverge. Fork because it diverged, not in anticipation.

The margin account has two consequences. It has **no T+1 settlement restriction**, so `CANT_USE_UNSETTLE_FUNDS_FOR_COMBO_ORDER` — which forces the market-order fallback today — simply goes away, and brackets should always work. It also **permits shorting**, so long-only must stay enforced in code rather than inherited from the account type. `sandbox_broker._TRADEABLE_ACCOUNT_CLASS` is currently hardcoded to `INDIVIDUAL_CASH` and needs to become configurable.

### The agent is not told it is paper

The prompt currently opens "You manage a small paper-trading account", and several rules and docs echo it. Those strings go.

**The prompt may lie to the model. The code must never lie to itself.** `_assert_sandbox()`, the `DEM` account-number prefix check and the account-class check all stay exactly as they are. The day someone relaxes one of them *because the agent thinks it is real anyway* is the day this becomes dangerous.

## What was rejected, and why

- **"It must earn to stay alive."** A model told it must earn to survive has a direct incentive to take more risk, which is the opposite of what a long-only book at a 1-2 week horizon wants — and this model's known weakness is already over-confidence, not timidity. There is also no good answer to what happens when it dies: refund the budget and the constraint was never real; leave it dead and the experiment ends having taught you that a rigged hurdle bankrupts an agent. The mechanism — research costs money, spend it wisely — delivers everything valuable without the risk-seeking or the dead end.
- **A separate repository.** See above.
- **Free-form ticker selection.** See above.

## Prerequisites, to check before building

**1. What 4 debate rounds actually costs, and whether it is better.**

`max_debate_rounds` and `max_risk_discuss_rounds` are both `1` today and both settable by env var (`TRADINGAGENTS_MAX_DEBATE_ROUNDS`, `TRADINGAGENTS_MAX_RISK_ROUNDS`), so this is configuration, not code.

The whole price model rests on $0.10 being roughly the real cost at 4 rounds. Measure it. And nobody has checked that more rounds *improve* the output — that assumption is doing a lot of work here and is cheap to test. Measure tokens, wall clock, and cost on the same ticker at 1 round and at 4, on both the local model and Flash-Lite.

If 4 rounds costs far less than $0.10, the internal price is arbitrary and should be re-set to something defensible. If it costs far more, the wall-clock cap matters more than the money cap.

**Measured 2026-08-25, GOOG on `gemini-3.5-flash-lite`:**

| Rounds | Decision | Prompt | Completion | Calls | Minutes | Cost | Plan length |
|---|---|---|---|---|---|---|---|
| 1/1 | Hold | 84,004 | 9,447 | 19 | 1.2 | $0.0488 | 1,569 chars |
| 4/4 | Hold | 282,326 | 19,997 | 36 | 2.9 | **$0.1347** | 1,275 chars |

Three things follow.

**$0.10 is close but slightly low.** Four rounds costs $0.135 on a paid vendor, so the internal price should be $0.13-0.15 rather than $0.10 if the intent is to charge roughly what it costs. At $0.135 and 9 analyses a day the hurdle on $10,000 is 3.1% a year, still comfortable.

**Prompt tokens grow faster than the round count** — 3.4x for 4x the rounds, against 2.1x for completion — because each debate turn re-sends the accumulated history. Cost scales with the square of the conversation, not with its length, which matters if anyone later argues for 8 rounds.

**Nothing suggests it is better.** Same decision, and the trade plan came out *shorter* — 1,275 characters against 1,569. That is one ticker on one day and settles nothing, but it is the opposite of the expected direction, and the assumption that more deliberation produces a better call is now the weakest load-bearing part of this plan. Before committing, run several tickers at both settings and compare the graded outcomes, not the prose.

**Measured 2026-08-25, the same GOOG on `gemma4-e2b-96k`:**

| Rounds | Decision | Prompt | Completion | Calls | Minutes | Cost |
|---|---|---|---|---|---|---|
| 1/1 | Hold | 96,025 | 22,554 | 16 | 7.7 | $0.0028 |
| 4/4 | **Overweight** | 321,482 | 48,294 | 32 | **18.1** | $0.0066 |

**The local model changed its mind, and Flash-Lite did not.** Hold at one round, Overweight at four, on identical inputs. That is the first evidence that rounds do anything at all — and there is a plausible mechanism: `gemma4-e2b-96k` answers Hold in 79% of all the signals it has ever produced, and a longer bull-versus-bear debate forces it to engage with the bull case instead of defaulting to no action. If more rounds mostly cure a Hold bias, that is worth having.

It is still one ticker on one day, and a changed decision is not a better one. But it moves the question from "does this do anything" to "does this do the right thing", which is a question graded outcomes can answer.

The token growth matches Flash-Lite almost exactly — prompt 3.3x, completion 2.1x — so the superlinear prompt growth is a property of the pipeline rather than of either model.

**Wall clock is not the binding constraint after all.** At 18.1 minutes an analysis, against the 155 minutes between the 11:00 sweep and the 13:35 decision:

| Tickers | 4 GPUs | 8 GPUs |
|---|---|---|
| 9 | 54 min | 36 min |
| 15 | 72 min | 36 min |
| 20 | 90 min | 54 min |

Every one of those fits. The GPU expansion still buys headroom, and it halves the sweep at 15+ tickers, but **4 rounds does not require it** — which means prerequisite 2 is an optimization rather than a blocker.

**One consequence for the price.** At 4 rounds an analysis really costs $0.1347 on Flash-Lite and $0.0066 in local electricity — a factor of 20. A single fixed price is therefore **a deliberate choice about scarcity, not a passthrough of cost**, and the plan should say so rather than implying $0.10 is what the work costs. It is roughly the vendor cost, and roughly 20x the local one.

**2. The GPU expansion.**

Four more RX 6600s from an idle mining rig, with their own PSU. The cards are **gfx1032**; they work because every pool container sets `HSA_OVERRIDE_GFX_VERSION=10.3.0`, which the four existing ones already do. New backends need `/dev/dri/card4`…`card7` with `renderD132`…`renderD135`, the same env, and `TRADINGAGENTS_MAX_CONCURRENT_ANALYSES` raised to 8 to match the backend count, or the extra cards idle.

Mining rigs usually use PCIe x1 risers. For inference that mostly costs model *load* time rather than inference speed, because the 4-minute keep-alive means each backend loads once and stays warm. Do not buy better risers in advance; measure first-load time and decide after.

This changes the electricity numbers. The measured 44 W average and the $0.26 marginal figure both stop being true, so re-meter afterwards.

**3. The current experiment must finish first.**

The Gemini comparison runs to about 1 September. A separate deployment does not disturb it, so building can start — but do not change the *existing* agent's inputs until the model comparison has produced graded results, or two variables move at once and neither answer is clean.

## Order of work

1. Measure the round count (prerequisite 1). **Starting here.**
2. Add the GPUs (prerequisite 2) — independent of everything else, and the wall-clock headroom for a bigger candidate menu depends on it.
3. Charge for research in the *existing* agent at a small price, and show it on the equity curve. Cheapest way to learn whether a research cost changes the picture at all, before building an economy on it.
4. The second deployment skeleton: `AGENT_ONLY` mode, the margin account, the $10,000 budget.
5. The candidate menu and the agent's spend decision.
