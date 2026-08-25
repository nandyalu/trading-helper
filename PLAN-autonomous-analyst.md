# Plan — the autonomous analyst

A second, separate experiment. The current auto trader is measured on *decisions given a fixed watchlist*. This one is measured on **what to look at, what to buy, and when to exit, under a budget that research draws from** — which is most of what an analyst actually does, and a far more interesting thing to be right or wrong about.

Written down 2026-08-25, from a design conversation. Nothing here is built yet. The prerequisites at the end must be answered before implementation starts, because two of them can invalidate the design.

## The idea in one paragraph

Give the agent $10,000 and charge it a fixed $0.10 for every analysis it runs. It always analyses what it holds, and it chooses what else to look at from a curated candidate list. It decides what to buy, when to exit, and what is worth researching in the first place. It runs against a real Webull sandbox account and is never told that the account is simulated.

## What is settled

### The economics

- **Budget $10,000**, against the current agent's $1,000.
- **A fixed price per analysis**, regardless of which model ran it. A fixed price keeps the comparison stable while the model question is still open.
- **At 1 round** — see prerequisite 1, which settled the round count — an analysis really costs **$0.0488 on Flash-Lite and $0.0028 in local electricity**, a factor of 17. So a single fixed price is **a deliberate choice about scarcity, not a passthrough of cost**, and the plan should not pretend otherwise.
- **$0.05 is the chosen price** — roughly what the vendor path costs at 1 round. On $10,000 at 9 analyses a day that is $113 a year, a **1.13% hurdle**; at 15 a day, 1.9%. Both are gentle, which is the right place to start — the constraint can always be tightened once there is evidence about how the agent spends.
- $0.10 would be defensible as a deliberately sharper constraint — roughly double the vendor cost, a 2.27% hurdle at 9 a day — and is where to go if $0.05 turns out not to make the agent choose. What is not defensible is calling either figure "the cost".
- On the current $1,000 budget, $0.10 would be a 22.7% hurdle — not a constraint but a rigged game. The $10,000 budget is what makes a research charge meaningful at all.
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

Money does not model time, so **a hard cap on analyses per day is needed regardless of what the agent can afford.**

At 1 round the local model takes about 8 minutes an analysis, against the 155 minutes between the 11:00 sweep and the 13:35 decision. On four GPUs that is roughly 20 analyses inside the window with margin, and on eight, about 40. The cap is therefore a safety rail rather than a binding constraint — 15-20 is a sensible starting number, and it does not depend on the GPU expansion.

(Measured at 4 rounds, 18.1 minutes an analysis, even 20 tickers still fit on four GPUs in 90 minutes. Wall clock was never going to be what stopped this.)

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

**1. What 4 debate rounds actually costs, and whether it is better. — ANSWERED 2026-08-25. Stay at 1 round.**

`max_debate_rounds` and `max_risk_discuss_rounds` are both `1` and both settable by env var (`TRADINGAGENTS_MAX_DEBATE_ROUNDS`, `TRADINGAGENTS_MAX_RISK_ROUNDS`), so this was configuration, not code.

**Cost, on one GOOG run each:**

| Model | Rounds | Decision | Prompt | Completion | Minutes | Cost |
|---|---|---|---|---|---|---|
| Flash-Lite | 1/1 | Hold | 84,004 | 9,447 | 1.2 | $0.0488 |
| Flash-Lite | 4/4 | Hold | 282,326 | 19,997 | 2.9 | $0.1347 |
| gemma4-e2b-96k | 1/1 | Hold | 96,025 | 22,554 | 7.7 | $0.0028 |
| gemma4-e2b-96k | 4/4 | Overweight | 321,482 | 48,294 | 18.1 | $0.0066 |

Prompt tokens grew 3.3-3.4x for 4x the rounds against 2.1x for completion, on both models, because each debate turn re-sends the accumulated history. **Cost scales with the square of the conversation, not its length** — worth knowing if anyone later argues for eight rounds.

That single local run changed its decision, which looked like the first evidence that rounds do something. It was not.

**Then all nine tickers, both settings, back to back** (re-run rather than compared against the morning sweep, so price movement could not be mistaken for a rounds effect):

| | 1 round | 4 rounds |
|---|---|---|
| Decisions | Hold 7, Overweight 2 | Hold 7, Buy 1, Overweight 1 |
| **Hold share** | **78%** | **78%** |
| Tokens | 1,261,156 | 3,298,997 (2.6x) |
| GPU minutes | 82 | 189 (2.3x) |
| Signals keeping both levels | 6/9 | 6/9 |

Four of nine decisions changed — CRWV and NOK became *less* directional, FXAIX and INTC *more* — and they cancelled out. **The distribution is identical.** The hypothesis that a longer bull-versus-bear debate would cure this model's 78% Hold bias is refuted.

**And the changes do not reproduce.** GOOG at 4/4 returned Overweight in the first measurement and Hold in the sweep an hour later, on the same day and the same inputs. Two runs at the same setting disagreed with each other, so none of the four "changes" above can be attributed to the round count. They are consistent with ordinary run-to-run variance in a 2B model, and the single-sample result that started this was noise read as signal.

**Decision: proceed at 1 round.** Four rounds costs 2.3x the time and 2.6x the tokens for no measurable change in what comes out. The price loses its "roughly what 4 rounds costs" justification with it — at 1 round an analysis is **$0.0488 on Flash-Lite and $0.0028 in local electricity**.

Both sets are recorded under `gemma4-e2b-96k@1round` and `@4rounds`, so they grade separately on their own dates and the scorecard's by-model table will say in a fortnight whether the 4-round calls were *individually* better despite the identical distribution. Revisit only if those grades surprise. Total cost of answering this: about 7 cents of electricity.

**2. The GPU expansion.**

Four more RX 6600s from an idle mining rig, with their own PSU. The cards are **gfx1032**; they work because every pool container sets `HSA_OVERRIDE_GFX_VERSION=10.3.0`, which the four existing ones already do. New backends need `/dev/dri/card4`…`card7` with `renderD132`…`renderD135`, the same env, and `TRADINGAGENTS_MAX_CONCURRENT_ANALYSES` raised to 8 to match the backend count, or the extra cards idle.

Mining rigs usually use PCIe x1 risers. For inference that mostly costs model *load* time rather than inference speed, because the 4-minute keep-alive means each backend loads once and stays warm. Do not buy better risers in advance; measure first-load time and decide after.

This changes the electricity numbers. The measured 44 W average and the $0.26 marginal figure both stop being true, so re-meter afterwards.

**3. The current experiment must finish first.**

The Gemini comparison runs to about 1 September. A separate deployment does not disturb it, so building can start — but do not change the *existing* agent's inputs until the model comparison has produced graded results, or two variables move at once and neither answer is clean.

## Order of work

1. ~~Measure the round count (prerequisite 1).~~ **Done 2026-08-25 — staying at 1 round.**
2. Add the GPUs (prerequisite 2) — independent of everything else, and the wall-clock headroom for a bigger candidate menu depends on it.
3. Charge for research in the *existing* agent at a small price, and show it on the equity curve. Cheapest way to learn whether a research cost changes the picture at all, before building an economy on it.
4. The second deployment skeleton: `AGENT_ONLY` mode, the margin account, the $10,000 budget. **Started 2026-08-25.**
   - done: `WEBULL_ACCOUNT_CLASS` selects the account from the two equities classes, rejecting anything else loudly rather than matching nothing
   - done: long-only enforced in `sandbox_broker`, because a margin account will short where a cash account refuses
   - done: `AGENT_ONLY` hides the real and paper books and skips the jobs that maintain them. It decides nothing about safety, and a test asserts the module never mentions accounts, orders or shorting — a flag about what to display must not drift into being a flag about what is safe
   - done: `dockge/analyst-bot.compose.yaml`, a second stack from the same image
   - done: the margin account is capped at $10,000 in Webull's own UI as well as by the app's budget. The API offers no way to cap an account, so the app must not depend on that cap existing
   - done: research charging. `research_price_usd` is a setting defaulting to **0, meaning free**, so the live deployment is untouched while the model comparison runs beside it. The experiment sets $0.05. Charges are stored rather than derived from a price times a count, because the price is a setting and settings change — a charge is something that happened, and re-pricing history would rewrite a book already reported.
   - done: the charge lands in `propagate_ticker`, so an analysis that produced no signal is still billed. The work happened either way, and research you learned nothing from is the normal case rather than an accounting error. It is linked to the signal afterwards when there is one.
   - done: the mechanical baseline pays too. It reads the same analyses; charging the agent alone would handicap it against its own yardstick and break the comparison this app exists for. SPY reads nothing and pays nothing.
   - done: research comes out of cash and out of `realized_pnl`, and is carried separately on the book so a page can show how much of a loss was research rather than trading — different problems.
   - done: `AGENT_BUDGET` and `RESEARCH_PRICE_USD` start a fresh deployment at the right numbers, as defaults for unset settings only — the settings page still wins
   - **deployed 2026-08-25.** Three things bit on first start, all recorded here because none is obvious:
     - Dockge runs `compose pull` before `up`, and `trading-bot:local` has no registry prefix, so Docker resolves it to Docker Hub and fails with "pull access denied". `pull_policy: never` fixes it.
     - Dockge resolved the named volume to a bind mount under `/opt/stacks/`, which Docker creates **root-owned**. The container runs as `appuser` (uid 1000) and could not create the database — "unable to open database file". `sudo chown -R 1000:1000` on that directory fixes it. The live stack avoids this only because its named volume was initialised from the image, ownership included.
     - **Webull allows one live trade-event subscription per app key, not per account.** Two deployments sharing a key cannot both stream; the second is refused with `RESOURCE_EXHAUSTED` whichever account it asks for. The experiment runs with `TRADE_STREAM=0` and settles fills on the 15-minute poll, which was always the guarantee the stream sat on top of. A second app key would give it the stream back.
   - next: the candidate menu
5. The candidate menu and the agent's spend decision.
