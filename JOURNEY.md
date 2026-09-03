# The agent's journey — what we changed, and why

The app writes its own record: what it bought, what that cost, and what the agent said about it, day by day. Every sentence in it comes from a trade, a charge, or a decision pass, so it cannot drift from the book.

Read it at `/api/agent/journey`, or as files: one per month, under a folder per year, in the data volume beside the database and the logs.

```
data/journey/2026/08-August.md
data/journey/2026/09-September.md
```

The app rewrites them after grading each evening. `python -m backend.scripts.write_journey` regenerates them on demand.

Each file opens with the month in four numbers: positions opened, positions closed, research spent, and where the book started and finished. That way a file reads on its own, not only as part of a series. That is what makes them publishable later: a month is a post.

**The app generates them, and rewriting them is how they stay true.** Do not edit them. The next write discards the edit. Put commentary here instead.

**This file is the other half, and it is the half the app cannot write.** It knows the agent changed its mind. It does not know that we changed the prompt the week before, or added a research charge, or settled the debate-round count by running an experiment.

Without those causes, a month of record is a list of events nobody can learn from.

Two rules, both learned the hard way elsewhere in this project:

- **Write it when it happens, not afterwards.** A reason you reconstruct two weeks later is a story about what you would like to have been thinking.
- **Record what was wrong, not only what worked.** The entries that say "this turned out to be noise" are worth more than the ones that say "this worked". They are what stops someone proposing the same idea again in three weeks.


---

## The changelog: every change to the agent, and why

The entries below record what changed in the agent's behaviour and the reason for it. They moved here from `CLAUDE.md` on 2026-09-01, which had been keeping a second copy of the same thing.

**Entries before 2026-09-01 cover two deployments.** A live bot and an analyst experiment ran side by side, sharing every line of the agent's code and differing only in their settings. Both ended on 2026-09-01 and one deployment runs now, but the entries still describe the same agent, so a change made for either applies to what runs today.

`CLAUDE.md` now describes what the rules are. This describes how they got that way. Add an entry here **before** changing a rule, not after.

Newest first.

**2026-09-03 — times are shown on the reader's clock, and one of them was wrong.** The site printed UTC in several places. UTC is not a fact worth reading: "13:35 UTC" makes a reader do arithmetic before they know whether they missed anything.

The pages now show each time on the reader's own clock with the zone named — "9:35 AM EDT", "7:05 PM IST" — which is unambiguous on its own. `market-time.ts` already did this for the timeline; the sweep line, the decision-pass line, the settings line and the glossary were still hardcoded.

**Fixing the label exposed a real bug underneath.** The decision-pass timestamp was not merely labelled UTC, it was *wrong* for everyone outside UTC, and the label is what hid it.

SQLite has no timezone type. Every writer here calls `datetime.now(timezone.utc)`, but the value comes back naive and serialized as `2026-09-03T11:35:39` with no offset. **A browser parses that as local time.** The instant was therefore off by the reader's own offset — five and a half hours in India, eight on the US west coast.

It stayed invisible because two errors cancelled. The page parsed as local and then formatted as local, so the number printed was the original UTC clock reading, and the fixed "UTC" label made it read as true. Correct on a UTC machine, and wrong everywhere else in a way no one on a UTC machine could see.

So `Schema._stamp_utc` now marks every naive datetime as UTC at the API boundary. Plain `date` fields are deliberately left alone — a calendar date has no zone, and attaching one moves it across midnight for every reader west of UTC.

**Two "time ago" displays were wrong for the same reason and are fixed by the same change**: the price age on a ticker page and the "3 days ago" label on the experiment page both subtract a parsed timestamp from the current time, so a mis-parsed instant went straight into the number.

**The journal had the opposite failure.** Its date is a calendar date, and a date-only string parses as UTC midnight. Rendered on a local clock it showed the *previous* day for every reader west of UTC. It is formatted in UTC now, which is what a calendar date needs.

Guarded in both halves: `backend/tests/test_timestamps_carry_their_timezone.py` checks the offset goes out, that an aware value is not converted twice, that a calendar date keeps no zone, and that no response model bypasses the base class — which is exactly how the decisions page missed it. The frontend spec asserts the time and its zone label agree rather than asserting a fixed string, so it is meaningful in any zone; the suite passes under UTC, Asia/Kolkata and America/Los_Angeles.

**2026-09-03 — the simulated-account check was too narrow, and it stopped the agent.** After the Webull paper reset, the new cash account came back as `DEL546C9`. The guard required a `DEM` prefix, refused it, and the agent had no account to trade.

**The guard was right to stop.** Its own comment says an account without the marker means "something is wrong enough to stop rather than trade", and refusing to trade is the correct failure for a check it cannot satisfy. What was wrong was the marker.

Reading the whole account list settled it. This sandbox host issues **both** prefixes, and always has:

| Account | Class |
|---|---|
| `DEM272Y8` | FUTURES |
| `DEL84669` | EVENTS_CASH |
| `DEL546C9` | INDIVIDUAL_CASH |
| `DEM67245` | INDIVIDUAL_MARGIN |
| `DEL744J6` | CRYPTO |

`DEM` was never the rule. It was what the two equity accounts happened to use when the check was written, and nobody looked at the other three. The reset reshuffled which prefix the cash account got and exposed the assumption.

The check now requires `DE`, which is what the evidence supports.

**This does not weaken the real protection.** The guard that matters is `_assert_sandbox()`: without `WEBULL_SANDBOX=1` the app never reaches a trading endpoint at all. The prefix is a second, weaker check on top — and a check derived from five accounts is worth more than one derived from two.

**The lesson is about the sample, not the check.** A marker observed on part of a set and then required of all of it will hold until the day the set changes, and it will fail at the worst moment — here, on the first morning of a fresh experiment.

**2026-09-03 — Discord becomes a webhook, and the bot is deleted.** No change to what gets posted. A large change to what a person has to do to receive it.

**The app only ever posts.** It reads nothing, responds to nothing, and has had no commands since 2026-09-01. A bot was how it started and the reason went with the commands.

What a bot cost, for a thing that only sends:

- An application, a token, OAuth scopes, and an invite URL — five steps before the first message.
- A live gateway connection held open for the life of the process, reconnecting on its own, and warning on every start that a privileged intent was missing.
- The `discord.py` dependency, and its `asyncio` lifecycle threaded through the app's startup and shutdown.

A webhook is a URL copied from a channel's settings, and one HTTP POST. **Embeds still work** — the webhook API takes the same shape — so the decision pass, the digest and the scorecard read exactly as before.

`DISCORD_BOT_TOKEN` and `DISCORD_CHANNEL_ID` are replaced by `DISCORD_WEBHOOK_URL`. Leaving it unset still disables notifications entirely, as before.

**The one thing genuinely lost is the reaction.** A webhook cannot add one. Nothing has used reactions since the ✅ that opened a hand-followed paper trade was removed on 2026-09-01, so nothing regressed — but a future feature wanting a reaction would need the bot back, and that is worth knowing before someone proposes one.

**2026-09-03 — the analyst framework is rebased onto upstream v0.4.1, before a single analysis has run.** The vendored TradingAgents had been pinned since 18 July. Upstream shipped two releases in that time, and three of the fixes are data-correctness bugs in the prices the agent would reason over.

**The timing is the point.** No analysis had run and no signal existed, so this changes nothing already in the record. A month from now the same rebase would have split the experiment in two, with no way to tell a change in the framework from a change in the market.

The fixes worth naming:

| Fix | Why it matters here |
|---|---|
| **The latest OHLCV bar was silently dropped** | A NaN close on the newest bar made the *previous* trading day look like the latest, so indicators ran on stale prices. This is the one that decided it. |
| The FRED vintage is pinned to the as-of date | Wrong today only in backtests, but it makes any future replay honest |
| A decision is not settled before its holding window trades | The memory log was resolving lessons early, teaching the agent from outcomes that had not happened |
| The Trader is grounded in the technical market report | Overlaps with our own price-anchoring, and the two now stack |

**Two of our nine cherry-picks were merged upstream and were dropped.** The REVIEW rating fix and the debate-opening fix both landed there, in more complete form than ours — upstream's opening fix covers the risk debaters too, which ours never did. Carrying our copies would have meant maintaining a worse duplicate forever.

**Three things the rebase broke, which no merge could have resolved:**

The trade horizon stopped reaching the checkpoint signature. Upstream moved that construction into two new methods, neither of which took a horizon, so both computed one for the default. **A swing run would have resumed a position run's checkpoint** — the exact thing the signature exists to prevent — and one of the methods referenced a name it did not take, which was a `NameError` waiting for the first checkpointed run.

The trader raised on a state with no `market_report`. Upstream reads it with a subscript, and the key is absent rather than empty when the market analyst is not selected, which is the case its own comment describes.

`yfinance_news` called a helper upstream had renamed.

**Nothing of ours was lost.** The tool-call recovery, the candidate screener, the verified market snapshot in the trader, the `TraderProposal` with no price fields, and tool errors going to the model rather than the logs are all still there and still tested.

**Where it leaves us:** 17 commits ahead of upstream, 0 behind, +1,839 / −176 lines of application code. 718 upstream tests pass, up from 663. All 600 of ours pass.

**2026-09-02 — the experiment starts.** The container is deployed, the Webull paper account is reset, and the agent is switched on.

**This is day one.** Not 2026-09-01, which is when the code was written: nothing was running that day — no container, no account, no book. The experiment starts when the agent can act.

The state it begins from:

| | |
|---|---|
| Budget | $10,000, all of it cash |
| Holdings | none |
| Watchlist | empty |
| Signals | none |
| Model | `gemma4-e4b-qat-128k` |
| Concurrency | 7 |
| Research charge | $0.05 an analysis |
| Watchlist cap | 30 |

**The watchlist starts empty on purpose.** The first morning sweep therefore analyses nothing, and the first real event is the 13:35 decision pass, where the agent sees the candidate menu and chooses what to pay to research. Whether it commissions anything at all on day one is the first observation, and it is the specific behaviour `gemma4-e4b-qat` was chosen for — the 2B model it replaced answered "no research" three mornings running.

The site is not public yet.

**2026-09-02 — the watchlist cap goes from 12 to 30, on a measurement.** The old number was derived rather than guessed, and the derivation rested on two figures that no longer hold.

It assumed **three concurrent analyses** and **17.4 minutes each** — the numbers for a pool shared with a second deployment that ended on 2026-09-01. Twelve was four waves of three inside the two-hour window between the 11:00 sweep and `earnings_check` at 13:00.

**Measured on 2026-09-02.** Fourteen tickers at seven concurrent, run twice:

| | Result |
|---|---|
| Wall clock for 14 | 42.5 and 43.4 minutes |
| Throughput | **about 3.05 minutes per analysis** |
| Succeeded | 28 of 28 |
| Tokens per analysis | 129,000, prompt share healthy at 16% |

At 3.05 minutes the 120-minute window fits about **39 analyses**. Thirty leaves a quarter of the window for a slow run, a retry, or a morning when something is wrong.

**Seven concurrent, not fourteen, and that is the more useful half.** Fourteen at once takes the same wall clock — 42.8 minutes — and doubles the latency of each analysis, from 18.6 minutes to 34.0. The CPU saturates before the GPUs do, because gemma4's E-series keeps its per-layer embeddings in host RAM; the cards sit around 63% busy either way. **Stacking a second analysis onto each card buys nothing.**

**What this does not fix.** The watchlist still only grows. Nothing ages out a name the agent has stopped holding and stopped asking about, so at the cap it has to trade one name's coverage for another — a decision it can make and is never prompted to revisit. A higher cap postpones that; it does not remove it.

**2026-09-02 — the agent can say what it needs, and it is told what went wrong.** Three changes, all about the same gap: the agent acts blind to its own failures and has no way to say so.

**1. A `note` action.** The agent may include `{"side": "note", "reason": "..."}` in its answer. It buys nothing, sells nothing, costs nothing and is refused for nothing. It is the agent addressing whoever maintains it — asking for a tool it lacks, data it cannot see, or a rule it finds contradictory.

The reason to add it is that this experiment exists to be read. "I could not decide well because I cannot see X" is primary evidence about the prompt and the tool set, and until now the only way to learn it was to infer it from twenty prompts. A note says it in one line.

It stays inside the rule the whole app is built on: **it acts on nothing.** The agent talking is not a second decision-maker; the agent trading would be. Nothing automatic reads a note and changes anything — if we build what it asks for, that is a change like any other and gets its own entry here first.

**A note never replaces a decision**, and the prompt says so. Without that, "I need better data" becomes a way to avoid answering, and a pass that should have said "hold everything" says nothing instead.

**2. Yesterday's failures appear in today's prompt.** The prompt showed the agent its closed trades and its track record, but never its *failed* orders. An order the broker refused yesterday was invisible this morning, so the agent would propose the same thing again and be refused again, with nothing in the record explaining the loop.

This is deliberately a prompt section and not a mid-pass retry. It costs no extra LLM call, adds no risk of looping on a persistent error, and leaves a decision pass as one comparable unit — which matters, because the pass is what we compare across days.

**3. A failed tool call goes back to the model instead of ending the analysis.** This one comes from a measurement rather than a guess. The 14-way concurrency run on 2026-09-02 lost two complete 40-minute analyses to this:

```
RuntimeError: No available vendor for 'get_indicators'
```

The model had asked for an indicator called `macd_histogram`. There is no such name; the one it wanted is `macdh`. Across the run it invented five — `macd_histogram`, `macd_hist`, `boll_upper`, `boll_lower` — and the vendor rejected each with a message that **lists every valid name**. Three recovered. Two escaped and discarded the whole analysis.

The correct answer was inside the exception the entire time. So a tool error is now handed back to the model once, with its message, and the model is asked again. It costs one call and saves an analysis.

**Once, not until it works.** An unbounded retry turns an analysis into a loop of unknown length against a slow local model, and a genuinely broken vendor would spin forever. One retry converts a typo into a recovery; a second would be trying to argue a broken tool into working.

**Only errors the model can act on.** A wrong indicator name is actionable — the valid list is right there. A network timeout is not: the model cannot fix it, and asking invites it to invent a workaround, which is the exact failure that disqualified four models in August. The retry is limited to errors whose message tells the caller what to do differently.

**The thing to watch.** Feeding errors back teaches a model to satisfy the checker. There is a version of this where the agent learns to phrase tool calls that pass rather than tool calls that ask for what it wanted. Watch for indicator choices getting narrower over time rather than more apt.

**2026-09-01 — everything except the agent is removed.** The largest change in this file, and the only one that ends an experiment rather than adjusting one. Both previous deployments stop today, their data kept as a record.

**This entry is the preparation. The experiment itself starts on 2026-09-02** — see the entry above, where the new container is deployed with an empty database and a freshly reset account. Nothing was running on the 1st.

The question the app now asks is one question. **What does an autonomous agent do with $10,000?**

Everything that was not part of that question is gone.

**The real book is removed.** No sync of a real brokerage account, no transaction log, no Portfolio page, no vs-SPY comparison over hand-entered lots. The app read a live Webull account to mirror holdings into a watchlist; it reads nothing but the sandbox now.

**The hand-followed paper book is removed.** It was a book a person followed by hand, seeded by a ✅ reaction on a Discord embed. Two books measured two different things and only one of them was the experiment.

**Every manual control is removed**, in Discord and on the dashboard. All twenty-three slash commands, the Track and Analyze buttons, Record a trade, Ask, Follow as paper trade, Sync now, and Decide now. **This is the change that matters most and it is worth being exact about why.** A control that lets a person nudge the book puts a second decision-maker in the record, and no reading of the book afterwards can tell which one produced a result. An experiment with an untracked second cause is not an experiment.

The exceptions are two, and both decide nothing. `POST /api/agent/exits/{ticker}` rests the stop and target the agent already chose under shares it already owns, for the case where the broker refused the bracket at purchase. And the settings page still changes the model, the horizon and the alert thresholds — those are the experiment's parameters, and changing one is a documented act, not a trade.

**When something needs correcting, the route is now deliberate: write down what changed and why here, then do it by hand.** That costs a few minutes and leaves the record readable. A button costs nothing and leaves it unreadable.

**The comparison machinery is removed. One model from here.** It ran a second model over the same tickers so two models could be compared on the same day's prices. `Signal.model` stays, because which model produced a row is a fact about the row, and the scorecard still splits by it when the configured model changes.

**Discord reports and no longer takes orders.** It carries what the agent did — its decision passes, a stop that filled, an exit that was armed, a watchdog alert. It no longer posts the analyses themselves: each runs to thousands of words, several arrive a morning, and they are read on the Signals and Events pages where they can be scrolled and compared.

**New defaults: a $10,000 budget and $0.05 an analysis.** Research was free by default so the live deployment would not start charging when this code reached it. There is one deployment now, and free research is just a longer watchlist — an agent that pays nothing for being wrong about what was worth studying learns nothing from being wrong.

**What was deliberately kept.** The watchlist page, showing what the agent chose and what it may commission. The Signals pages, with every analysis in full. The Scorecard, the digest, the regime line, the alerts. The Events page and the Journey page, which are the record. And `AGENT_BUDGET` / `RESEARCH_PRICE_USD` as environment overrides, so a container comes up on the right numbers rather than being corrected by hand on its first run.

**What this costs.** Two things get harder and both were traded away knowingly. Nobody can now start an analysis to see what the model says about a ticker today — the answer arrives tomorrow, at the agent's expense, or not at all. And a mistake in the book has to be repaired by hand against the database rather than through a button. Both are the price of a record with one author.

The repo is tagged `v1-two-book-experiment` at the commit before this. Nothing here is lost; it is only no longer in the way.

**2026-09-01 — the agent's prompt and answer are recorded, and there is a page for them.** `AgentRun` gains `prompt`, `response` and `orders`, and the dashboard gains an Events page that shows them.

The counts and the one-line reasoning describe a decision. The prompt and the answer *are* the decision, and until now neither was kept anywhere: the agent's `_ask` uses a client the trace recorder never attaches to, so the analysis traces missed it. Behaviour here is mostly prompt, so a month of runs across three prompt revisions could not be told apart afterwards.

**Every pass before today carries no prompt, and none can be backfilled** — the prompt is assembled from a book, a watchlist and a signal list that have all moved since. Those passes still appear on the page, saying so, rather than leaving a hole in the record.

`orders` is stored separately from `agenttrade` because a buy or a sell lands there and an untrack, a research and an adjust do not. Without it the page would show a pass that untracked two tickers as having done nothing.

A Journey page shows the last ten days of the generated journal, built from the same `journey.build()` the monthly markdown files come from, so the page and the files cannot disagree.

**2026-09-01 — a negative balance no longer offers negative shares.** Every signal line said "With your $-8.00 cash you can afford -1 share(s)."

`int(-8.00 // 36.51)` is -1 rather than 0, because floor division rounds toward negative infinity, and -1 is truthy — so the "you can afford" branch was taken and rendered the nonsense. The count is clamped at zero now, and the branch tests for a positive number rather than a non-zero one, since those two differ only when the answer is meaningless.

The line itself stays, because it exists for a reason: a model proposed $1,944 of buys against $1,000 of cash when it was left to do the arithmetic. Fixing the negative case must not lose the count in the normal one.

**2026-09-01 — an empty or negative balance says so, instead of quoting itself as a spending limit.** The rules block opened with "The buys you place must cost $-8.00 or less in total", which is not an instruction anybody can follow.

The agent reached minus $8.00 on 2026-08-28, from a fill three cents above the price its order was screened at. That arithmetic is fixed. The state is still reachable, because **the daily research charge lands whether or not there is money for it**: `propagate_ticker` bills every ticker the sweep touches, so a book at zero keeps drifting down $0.05 a ticker a day with nothing to stop it.

The prompt now states the condition, what it prevents, and what changes it. Below the research price the agent can buy nothing and commission nothing — `screen` already refuses both — but the charge on what it already tracks continues. Selling is the only thing that raises cash. Untracking raises none, and stops part of the drain.

**Two things this deliberately does not do.** It does not stop the charge at zero: billing only when affordable would make the cost vanish exactly when it starts to bite, and the experiment is about deciding under a budget. And it does not size or forbid anything new — Python's refusals are unchanged, and the agent may still answer with nothing.

**2026-09-01 — the watchlist section states what it costs, in dollars.** One line, and the reason is five days of the agent never once mentioning the watchlist.

It had the parts. The menu section says an analysis costs $0.05, the watchlist section said "You are paying to have 3 tickers analysed every morning", and the rules say untracking "saves the analyses you would have paid for tomorrow and after". What no line gave was the product: **$0.15 a day**, and $0.10 of that on two names it holds none of.

Making the model multiply is the thing this app already decided not to do. The signal section computes how many whole shares the cash can buy in Python, because the model proposed $1,944 of buys against $1,000 of cash when left to do it. A recurring cost is the same kind of arithmetic and gets the same treatment.

**What the agent's own reasoning shows.** Across five passes it never mentioned the watchlist, and on 2026-09-01 it wrote "Given the small cash amount available for new shares, I will maintain the current position." It understands it has no money. It has not connected that to a charge it can stop, while its cash drifts down $0.05 a day against a book with none.

**This does not add a rule.** The agent may already untrack, and Python already refuses what it must. The prompt only stops making it work out its own running cost. Whether that changes anything is the measurement: if it still never untracks, the next question is about the model rather than the wording, and this entry is what makes that readable.

**2026-08-29 — two defects the first real trade exposed.** Neither changes what the agent may decide. Both fix a number Python got wrong on its behalf, and both were invisible because both produced figures that look entirely reasonable.

**Exits now come from the newest signal for a ticker, not the oldest.** `stops`, `targets` and `signal_by_ticker` were dict comprehensions over the signal list, and a dict comprehension keeps the *last* value it sees. `get_recent_signals` returns newest-first, so the oldest signal won every time a ticker had been analysed twice. On 2026-08-28 the agent bought 260 SMCI and rested the 27th's levels — a 34.16 stop and a 45.21 target — when that morning's analysis had said 34.04 and 49.51. The target was $4.30 out. Nothing reported it, because a stale level is still a real level from a real signal. `_newest_signal_per_ticker` now sorts by `(signal_date, id)` rather than trusting the caller's order, since a "keep the first one seen" fix would invert silently the day that ordering changed.

**A buy is screened at its entry limit, not at the quote.** The order leaves as a marketable limit `ENTRY_LIMIT_BUFFER_PCT` through the offer, so checking the raw quote approves an order the account cannot pay for. The same SMCI buy passed at 260 x $38.46 = $9,999.60 against $9,999.70 of cash, filled at $38.49 for $10,007.40, and left the book at **minus $7.70**. `agent_book.entry_limit_price` is what the check now uses. It **refuses rather than resizes**, like every other check there: shrinking would quietly turn the model's decision into a different one, and the record would then describe a strategy nobody chose.

**Neither addresses the concentration.** That buy was 100% of the book in one name, and the agent asked to do the same with NVDA the day before. There is no position-size cap, and adding one would be a change to what the agent may decide rather than a correction to arithmetic — so it belongs in its own entry, with its own reasoning, if it is ever added.

**2026-08-27 — the agent chooses what to stop watching, and the watchlist is capped.** A `side: "untrack"` action, a watchlist section in the prompt, and a ceiling of 12 tracked tickers.

Before this the watchlist only ever grew. `_commission_research` called `db.add_to_watchlist` and nothing in the agent could remove one — `/untrack` was manual and was the only route. That was survivable at `gemma4-e2b-96k`'s 7 minutes an analysis and stops being survivable at `gemma4:e4b-it-qat`'s 17.4: the sweep runs 11:00 UTC and `earnings_check` puts its own analyses on the same pool at 13:00, so three concurrent analyses fit about 20 tickers in the window. At the 4-6 names a run commissions, the ceiling arrives in about four days. **`_MAX_RESEARCH_PER_DAY` does not help, because the limit is cumulative rather than per-day** — the same reason a daily spending limit does not stop a subscription.

**The cap is 12, not 20.** Twenty is what the window fits with nothing going wrong. Twelve is four waves and leaves the second hour as margin for a slow run, a retry, or a morning when the live sweep is contending for the same cards.

**A held ticker can never be untracked**, and that is enforced in Python rather than asked for in the prompt. An agent that could stop watching a position it still owns would lose the analysis that finds its exit, and the daily analysis of a holding is exactly what the "you own the cost of finding your own exit" charge pays for. The same reasoning as refusing a sell of shares that are not held: the model decides what it wants, Python refuses what must not happen.

**Untrack is free and is ordered, like a sell that funds a buy.** Listing an untrack before a research frees a slot for it in the same pass, so a full watchlist is never a dead end — the agent trades one name's coverage for another's rather than waiting a day. The prompt says so explicitly, because the identical wording had to be added for sells before the model worked out it could do the same thing with cash.

**The watchlist is now in the prompt**, with its size and its cap, split into what is held and what is only being watched. Required by the action, and for the same reason holdings had to start showing their resting exits on 2026-08-25: the agent cannot sensibly drop something it cannot see, and a cap it is not shown is a rule it can only discover by being refused.

**2026-08-26 — the agent chooses what to research.** A `side: "research"` action, and a menu of screened candidates in the prompt with what an analysis costs. This is the point of the analyst experiment: the live agent is measured on decisions given a fixed watchlist, and this one decides what is worth looking at at all. Commissioning a ticker adds it to the watchlist — which *is* the commission, since the morning sweep reads the watchlist. **The charge lands when the analysis runs, not when it is commissioned.** Billing at both ends charged a commissioned ticker twice, once for asking and once for the work; `propagate_ticker` already bills every ticker the sweep touches, including the held ones nobody commissioned, so that is the single place. The cost of this is that the agent can commission slightly more than its cash on a day the sweep has not happened yet — bounded by the daily cap to cents against a four-figure budget, and a far smaller problem than double-billing.

The menu is never free-form. A model naming its own tickers invents symbols, reaches illiquid things with no price data, and picks the day's pump; `candidates.py` already screens for liquidity and excludes anything up more than 30%, which matters because a raw screen once returned a stock up 927% and a price floor does not catch that — the pump is what lifted the price over the floor.

The answer arrives **tomorrow**, not in the same pass. That is the honest shape: an analyst does not hand over a report the instant you ask, and same-breath research would let the agent act with no cost to being wrong about what was worth studying. A daily cap of 15 applies regardless of cash, because money does not model time and the sweep has to finish before the open.

The whole section only appears when research is actually charged for. A menu the agent can take from for free is just a longer watchlist somebody else chose.

**2026-08-25 — the agent may move its own exits.** A `side: "adjust"` action,
with a new stop, target or both, on something already held. Before this, exits
were fixed when a position opened and untouched until it closed, so re-reading
a holding every morning taught the agent nothing it could act on short of
selling: GOOG spent a week with a $377.09 take-profit while each day's analysis
put the end of the move at $345.00. Python still refuses a level that would
execute on placement, and a level already where it was asked for is skipped
rather than re-sent.

**2026-08-25 — holdings now show what is resting under them.** The prompt lists
each position's live stop and target, and says `NOTHING is resting to close it`
when there is none. Added with the adjust action, and required by it: the agent
cannot sensibly move an exit it cannot see.

**2026-08-25 — signals are filtered to the configured model.** Running a second
model for comparison puts two signals per ticker in the table, sometimes
disagreeing. Without the filter the agent traded on the mixture, folding an
experiment into the live book.

**2026-08-25 — a conviction floor, switched off.** Minimum chance of working
and minimum risk/reward, both defaulting to zero. Off deliberately: the chance
of working is the model's own claim, and until the Scorecard's calibration says
it is honest *and* that it sorts outcomes, a threshold on it is arbitrary
discipline. A signal stating no number fails the floor rather than passing it,
or the floor could be dodged by not answering.

**2026-08-13 — buys go out as brackets.** Previously the exits were armed after
the buy returned, which meant they were validated while the account still held
nothing and read as a new short. Two positions were bought that day and neither
got its exits.

**2026-08-13 — an ATR stop is derived when the stated one is unusable.** Both
of that day's unprotected positions were bought days after their signal, by
which time the price had fallen through the stated stop and the level was
correctly discarded — leaving nothing. `record_signal` already substituted an
ATR stop, but only for Buy and Overweight, and the agent buys on Holds too.

**2026-08-13 — an unguarded position is announced.** It used to be silent: no
alert, no ledger row, and the only way to find out was to look at the broker.

---

## 2026-08-26 — The analyst starts

A second deployment, on the sandbox's margin account, with $10,000 and a $0.05 charge for every analysis it runs. Separate database, separate Discord channel, separate book from the live agent, which continues untouched on its $1,000 cash account.

**Why a second deployment rather than changing the first.** We measure the live agent on decisions it makes from a fixed watchlist. We measure this one on what to look at, what to buy, and when to exit, under a budget that research draws from. That is most of what an analyst actually does, and they are different experiments. Running both in one book would answer neither.

**Why research costs money.** Analysis is free to the live agent, so "what is worth looking at" is not a decision it makes, and not one anyone can grade. A price makes it one. It also makes the app's central question honest: whether the model pays for itself has to include the cost of running the model.

We charge the mechanical baseline too, because it reads the same analyses. We do not charge SPY, because it reads nothing.

**Why $0.05.** Roughly what an analysis costs on a paid vendor at one debate round. On $10,000 at nine analyses a day that is a 1.13% annual hurdle — a real constraint that still leaves the test fair.

It is deliberately *not* a passthrough of cost. Local electricity for the same analysis is $0.003, seventeen times less, so any single price is a choice about scarcity rather than an accounting fact.

**What we got wrong first.** We built the plan on four debate rounds, which we believed cost about $0.10 and produced better decisions. Measuring it disproved both halves:

- **Four rounds cost 2.3x the wall clock and 2.6x the tokens.**
- **The decisions came out identical in distribution** across nine tickers — 78% Hold either way.
- **Four decisions changed and cancelled out**, two becoming more directional and two less.
- **The same ticker at the same setting returned different answers an hour apart**, which meant we could not attribute any of the changes to rounds at all.

A single earlier sample had looked like evidence. It was noise, and we had already written it into the plan as a finding before the nine-ticker run corrected it.

Three problems appeared on the first deploy. None was obvious, and all three are now recorded in `PLAN-autonomous-analyst.md`:

- **Dockge pulls a local-only image** and fails.
- **Dockge turns a named volume into a root-owned bind mount** that a container running as `appuser` cannot write.
- **Webull allows one live trade stream per *app key***, not per account, so two deployments sharing a key cannot both have one.

**What it cannot do yet.** Choose its own tickers. The candidate menu is the next thing to build. Until it exists the watchlist is empty and the agent has nothing to decide about. That is the whole experiment, so nothing here means much until it lands.

## 2026-08-27 — The model was the problem, and the watchlist only grew

**The candidate menu shipped yesterday and the agent would not use it.** The entry above calls the menu the next thing to build. It shipped hours later, which is what writing things down as they happen looks like.

Then the agent answered "no research" on three real mornings. The feature worked. The experiment sat idle behind it.

We suspected the prompt, and we were wrong. We replayed the deployed prompt against each model directly, unchanged:

| Model | Chose research | What it picked |
|---|---|---|
| `gemma4-e2b-96k` | 2 of 4 runs | 3 names of 15, twice; nothing, twice |
| `gemma4:e4b-it-qat` | **4 of 4 runs** | 4-5 names of 15, with a reason for each |

The wording was never the problem. A 2B model follows the instruction sometimes and not reliably, and no rewrite fixes that.

**We lost a day to the wrong explanation first.** When the agent researched on only half of identical passes, we read it as a sampling problem. Gemma's recommended temperature is 1, which looked too loose for a trading decision, so we rebuilt the production model at 0.15.

That treated the model's capability as a sampling problem, and it moved the live deployment off Google's documented settings in the middle of an experiment. e4b at stock sampling then chose research 4 times of 4, which exposed the error. We reverted it, and the reasoning now sits in the Modelfile so nobody derives it again.

**So the analyst runs a model that is twice as slow, on purpose.** We measured four gemma4 variants on the 8 GiB cards:

| Model | Fits the card? | The detail that decides it |
|---|---|---|
| `gemma4:e4b-it-qat` | **Yes** — 43 of 43 layers on the GPU, 3.7 GiB at the full 131,072-token context | Reads its prompt 30% faster than the `e4b` tag, and downloads 6.1 GB instead of 9.6 |
| `gemma4:e4b` | Yes, same placement | Slower to read, and a larger download for no gain |
| `gemma4:12b` | No | Two to five of its 49 layers always run on the CPU, and the quantization-aware build does not change that |
| `gemma4:26b` | No, and far worse | All 18 GB of experts still have to be stored somewhere, despite only 4B active parameters |

An analysis goes from 7 minutes to 17.4. That buys the decision this experiment exists to measure, so it is worth paying. It also exposed a problem nobody had noticed.

**The watchlist only ever grew.** Commissioning research added a ticker. Nothing in the agent removed one. `/untrack` was manual, and it was the only way out.

At 7 minutes an analysis, nobody would have noticed for months. At 17.4 the sweep window holds about twenty tickers, and that window runs from 11:00 UTC only until the earnings check takes the same cards at 13:00. The agent picks four to six names a run, so it reaches the ceiling in about four days.

The daily research limit does not help. The limit is cumulative rather than per-day — a daily spending limit does not stop a subscription.

**So dropping a ticker is now the agent's decision too.** It now decides all five:

- what to watch
- what to research
- what to buy and sell
- where to move its exits
- what to stop watching

Untracking frees a slot the way selling frees cash, and the order matters the same way: list the untrack first and the research after it. The prompt says so plainly. The identical wording had to be added for sells before the model worked out it could reorder, so we did not assume it would generalize this time.

One thing the agent may never do is untrack something it holds. A position nobody analyses has nothing looking for its exit. Python enforces that rule rather than the prompt requesting it, as with every limit that has to hold.

**Building a feature is not the same as the model using it.** The menu had just taught us that, so we probed this one before calling it done. We gave the model a full watchlist and two tempting candidates.

It untracked and then researched, in the right order, in three runs of four, and it chose the penny stock to drop both times. The fourth run asked for two researches without untracking anything, and Python refused both. That refusal exposed a second problem: the retry's only advice was about cash, which does not help a full watchlist. We matched the advice to the refusal, and the retry then recovered in three runs of four.

**We found a crash by accident, and it was waiting for the first trade.** Rendering the new watchlist section raised a formatting error. The holdings loop used a local variable named `price`, which replaced the research-price parameter with a string, and the menu section then formatted that string as a number.

The bug needs a holding and a menu in the same prompt. The analyst holds nothing yet, so it had never fired. It would have crashed the agent's first decision pass after its first buy.

**Two things this project had written down were also wrong.** We had repeated both confidently, including earlier the same day:

- **The proxy does not hold a card for a whole analysis.** We believed it did, which would make its ten-minute timeout dangerous against a seventeen-minute run. It releases the card after a single call: ten concurrent requests against seven cards all completed, the slowest in 38 seconds.
- **The sweep has two hours before the open, not one.**

**Seven cards now split four to the live book and three here.** That is temporary. Once the Gemini Flash-Lite comparison reports, the analyst should take five and the live book two, because this is the long-running experiment and the live book runs a model less than half as slow.

The change waits for that comparison, which only reads correctly if the live deployment keeps analysing at the speed its graded signals were produced at. The watchlist ceiling of twelve then has to be measured again at five concurrent rather than scaled, because analyses on these cards compete for host memory bandwidth and the time does not divide evenly.

**Still zero decision passes and zero trades.** Everything above is preparation. Tomorrow morning is the first time the agent tests any of it.

## 2026-08-27, later — The agent bought its first research, and we stopped asking the model for prices

**The entry above ends by saying tomorrow morning is the first test. It was this morning.** The sweep ran at 11:00 UTC and the agent commissioned three analyses — NVDA, CRM and SMCI — for $0.15. That is the candidate menu working for the first time, after three mornings of "no research", and it is the reason we accepted a model twice as slow.

Everything below happened in the hours around that, so this entry is the same day as the one before it.

### A model that looked perfect and was not

`lfm2.5:8b` arrived claiming tool calling as a strength. It is the fastest model that has ever fit these cards: 2,138 tok/s reading against `gemma4-e4b-qat-128k`'s 1,126, all 25 layers on the GPU at the full 128k, every weight on the card. On speed alone it was the obvious upgrade.

Then it invented every price in two runs out of two. AAPL closed at $313.45; it cited $188-196 in one run and $144-150 in the other — roughly the stock in 2024, then in 2023. A stale cache would be wrong the same way twice, so that is recall from training.

Three things came out of rejecting it, and the third is the one worth keeping:

- **The tell we had been relying on did not fire.** The four models rejected before this were caught by a collapse in prompt tokens, because a model that never fetched has far less to read. This one read 77-96k and invented anyway. What caught it was the **completion share** — 34-35% against the working family's 14-17%. It read enough and then talked over what it read.
- **A vendor's tool-calling claim is a reason to test, not evidence.** A benchmark asks whether a model picks the right function from a list. This pipeline asks whether it carries the returned number into a field twenty calls later.
- **The speed was real and bought nothing**, which is the fifth time that has been true here.

### So we stopped asking models for prices at all

Rejecting a fifth model made the pattern impossible to ignore. Every one of them failed the same way, and we had been treating it as a knowledge problem — the models quote prices from two years ago, so they must need newer data or a retrieval step.

**They already had today's price.** `lfm2.5:8b` read 96,000 prompt tokens and cited nothing near the real close. Back on 2026-08-06, gemma4-e2b's market report carried the right prices in the same run where its trader wrote $2,000 for a stock at $356.62. The model does not need to know the price. It needs to copy the price it was given.

That reframing made the fix cheap rather than expensive, and two of them landed today.

**The server now constrains the answer.** Structured output on a local model asks for `json_schema` instead of function calling, so ollama constrains the sampler and a malformed answer stops being possible rather than becoming less likely. `lfm2.5:8b` went from 4 structured-output failures per run to 0 in each of two; the analyst's own model went from 1 per run to 0, and has logged 0 across every run since.

**The trader has no price field.** `TraderProposal` no longer carries entry, stop or target. The model states two distances — how far the stop sits in ATRs, and how much the trade aims to make as a multiple of what it risks — and Python computes the levels from the verified close and ATR. A field that does not exist cannot be filled from memory, which is stronger than any instruction not to.

SMCI is the first signal recorded that way, and the arithmetic is checkable from the row itself. The model asked for 1.5 ATRs and 2.0R. The stored risk is $37.85 − $34.16 = $3.69, and $3.69 ÷ 1.5 = $2.46, which is SMCI's actual ATR. The reward is $7.36, exactly twice the risk.

Compare the two analysed before the rebuild. NVDA came back with no entry at all, so its stop fell to the ATR fallback. CRM's levels were the model's own — plausible, and *checked* afterwards rather than correct by construction. SMCI's cannot be wrong in that way.

### The market report that was not a market report

Two runs came back with a market report of 532 and 0 characters, against about 5,000 before. It looked exactly like the change we had just made.

**It was not.** The traces of every run that day showed the market analyst failing intermittently in two ways, including once before any of this existed. Reading the record is what settled it, and the trace capture built earlier the same day is the only reason there was a record to read.

The cause is one line. An analyst decides it is finished when the model returns no tool calls:

```python
if len(result.tool_calls) == 0:
    report = result.content
```

That reads two things as one. "I am finished, here is the report" and "I tried to call a tool and typed it as prose" both arrive as an empty list, so a model narrating its intent gets the narration filed as the finished report. Our own analyst had a 532-character market report reading "I will call `get_stock_data` first", and nothing logged a problem.

We built three fixes and measured them one at a time. Two survived.

| Fix | What it does | Measured | Kept |
|---|---|---|---|
| Detect | Retry when the answer is ungrounded | 4 of 4, from 0 of 3 | Yes |
| Prompt | Tell the model to call, not describe | 13 of 17 either way | **No** |
| Salvage | Execute a written-out call | Recovered the one real case in every trace | As a fallback |

**The prompt fix was the cheap idea and it did nothing.** "Call the tools. Do not describe the call you are about to make" measured 13 of 17 with it and 13 of 17 without. It is reverted, and the number to beat is written where anyone would look before proposing it again. Had we not measured it separately it would have shipped and been credited with the detection fix's result.

**Detection needed two checks, and the obvious one was weaker.** Reading the text catches a fenced JSON block naming a tool. It does not catch a model that writes "### Phase 1: Detailed Swing Trade Planning" — prose naming no tool, and indistinguishable from a report by content alone.

What gives that one away is the conversation rather than the words: if nothing ever returned a tool result and the model is not asking for one, the answer was composed from no data. With only the text check the live test recovered 3 of 6 and the detector never fired once, so those three were luck. With the structural check it is 4 of 4.

**Two things we learned about the stack.** Ollama ignores `tool_choice` — sending `required` behaves exactly like `auto` and like sending nothing — so the standard lever for forcing a call is not available here. And the model is not incapable: asked directly for AAPL's price data it called correctly every time, and asked to think aloud about its plan first it narrated every time. The prompt decides it, which is why the prompt fix looked so promising.

### What the app now keeps

Every LLM call of every analysis is written to disk, about 0.4 MB a run. **A dataset of past runs cannot be collected afterwards**, and five rejected models make a fine-tune worth leaving the door open to, so the capture exists before anyone has decided to attempt one. `Signal.trace_id` joins a trace to the signal it produced, and that signal gets graded weeks later — which means a future training set can keep only the runs the market agreed with.

It has already paid for itself twice today, as the only way to tell an intermittent market-analyst failure from a regression we had just caused.

### Where this leaves the experiment

Three tickers tracked, $0.15 spent, and no trades yet. The agent sees these three signals for the first time at 13:35 UTC tomorrow, and that is the first pass with the whole loop closed: choose what to research, read the answer, decide what to do about it.
