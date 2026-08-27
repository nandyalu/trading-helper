# The analyst's journey — what we changed, and why

The app writes its own chronicle: what was bought, what it cost, what the agent said about it, day by day. Every sentence there is derived from a trade, a charge or a decision pass, so it cannot drift from the book.

Read it at `/api/agent/journey`, or as files: one per month, under a folder per year, in the data volume beside the database and the logs.

```
data/journey/2026/08-August.md
data/journey/2026/09-September.md
```

They are rewritten after grading each evening, and `python -m backend.scripts.write_journey` regenerates them on demand. Each opens with the month in four numbers — positions opened and closed, research spent, where the book started and finished — so a file can be read on its own rather than only as part of a series. That is what makes them publishable later: a month is a post.

**They are generated, and rewriting them is how they stay true.** Do not edit them; the next write discards it. Commentary goes here.

**This file is the other half, and it is the half the app cannot write.** It knows the agent changed its mind. It does not know that we changed the prompt the week before, or introduced a research charge, or settled the debate-round count by running an experiment. Without that, a month of chronicle is a sequence of events with no causes — and the causes are the only part anyone can learn from.

Two rules, both learned the hard way elsewhere in this project:

- **Write it when it happens, not afterwards.** A reason reconstructed a fortnight later is a story about what we would like to have been thinking.
- **Record what was wrong, not only what worked.** The entries below that say "this turned out to be noise" are worth more than the ones that say "this worked", because they are the ones that stop the same idea being re-proposed in three weeks.

---

## 2026-08-26 — The analyst starts

A second deployment, on the sandbox's margin account, with $10,000 and a $0.05 charge for every analysis it runs. Separate database, separate Discord channel, separate book from the live agent, which continues untouched on its $1,000 cash account.

**Why a second deployment rather than changing the first.** The live agent is measured on decisions given a fixed watchlist. This one is measured on what to look at, what to buy and when to exit, under a budget research draws from — which is most of what an analyst actually does. Those are different experiments, and running them in one book would answer neither.

**Why research costs money.** Analysis is free to the live agent, so "what is worth looking at" is not a decision it makes and not one anyone can grade. A price makes it one. It also makes the question the app exists to answer honest: whether the model earns its keep should include the cost of running the model. The mechanical baseline is charged too, because it reads the same analyses; SPY is not, because it reads nothing.

**Why $0.05.** Roughly what an analysis costs on a paid vendor at one debate round. On $10,000 at nine analyses a day that is a 1.13% annual hurdle — a real constraint that does not rig the game. It is deliberately *not* a passthrough of cost: local electricity for the same analysis is $0.003, seventeen times less, so any single price is a choice about scarcity rather than an accounting fact.

**What we got wrong first.** The plan was built on four debate rounds costing about $0.10 and producing better decisions. Measuring it killed both halves. Four rounds cost 2.3x the wall clock and 2.6x the tokens, and across nine tickers the decision distribution was identical — 78% Hold either way. Four decisions changed and cancelled out, two becoming more directional and two less. Then the same ticker at the same setting returned different answers an hour apart, which meant none of the changes could be attributed to rounds at all. A single earlier sample had looked like evidence; it was noise, and it had already been written into the plan as a finding before the nine-ticker run corrected it.

Three things bit on the first deploy, none of them obvious, all now recorded in `PLAN-autonomous-analyst.md`: Dockge pulls a local-only image and fails; it turns a named volume into a root-owned bind mount that a container running as `appuser` cannot write; and Webull allows one live trade stream per *app key*, not per account, so two deployments sharing a key cannot both have one.

**What it cannot do yet.** Choose its own tickers. The candidate menu is the next thing to build, and until it exists the watchlist is empty and the agent has nothing to decide about. That is the whole experiment, so nothing here means much until it lands.

## 2026-08-27 — The model was the problem, and the watchlist was a ratchet

**The candidate menu shipped yesterday and the agent would not use it.** The entry above ends by calling the menu "the next thing to build"; it landed hours later, which is what writing things down as they happen looks like. Then for three real mornings the agent answered "no research" — the whole experiment sitting idle behind a feature that worked.

The obvious suspicion was the prompt, and it was wrong. Replaying the deployed prompt directly against the model, `gemma4-e2b-96k` chose research in 2 runs of 4. Against `gemma4:e4b-it-qat`, the same prompt, unchanged: **4 of 4**, picking four or five names out of fifteen with a stated reason for each. It was never a wording problem. A 2B model could follow the instruction sometimes and not reliably, and no amount of rewriting fixes that.

**Which cost a day of being wrong about something else first.** When the agent researched on only half of identical passes, the tempting reading was that Gemma's recommended temperature of 1 was too loose for a decision, so the production model was rebuilt at 0.15. That treated a symptom of the model's capability as a sampling problem, and it moved the live deployment off Google's documented configuration in the middle of an experiment. e4b at stock sampling being consistent 4 of 4 is what exposed it. Reverted, and the reasoning is written into the Modelfile so it does not get re-derived.

**So the analyst runs a model that is twice as slow, on purpose.** Four gemma4 variants were measured on the 8 GiB cards. `gemma4:12b` never fits — two to five of its 49 layers always land on the CPU, and the quantization-aware build does not rescue it. `gemma4:26b`, despite only 4B active parameters, is far worse, because all 18 GB of experts still have to live somewhere. `gemma4:e4b-it-qat` runs all 43 layers on the GPU at the full 131,072-token context in 3.7 GiB, reads 30% faster than the default `e4b` tag, and downloads 6.1 GB instead of 9.6.

An analysis goes from 7 minutes to 17.4. That is the price of the agent making the decision the experiment exists to measure, and it is the right trade — but it is a real cost, and it broke something quietly.

**The watchlist only ever grew.** Commissioning research added a ticker and nothing in the agent removed one; `/untrack` was a manual command and was the only route out. At 7 minutes an analysis nobody would have noticed for months. At 17.4 the sweep window — 11:00 UTC until the earnings check claims the same cards at 13:00 — fits about twenty tickers, and at four to six names a run that ceiling arrives in about four days. The daily research limit does not help, because the limit is cumulative rather than per-day, the way a daily spending limit does not stop a subscription.

**So dropping a ticker is now the agent's decision too.** It chooses what to watch, what to research, what to buy and sell, where to move its exits, and what to stop watching. Untracking frees a slot the same way selling frees cash, and in the same order — list the untrack first and the research after it — which is wording that had to be spelled out for sells before the model worked out it could reorder, so it was spelled out here rather than assumed. One thing it may never do: untrack something it holds. A position nobody is analysing is a position with nothing looking for its exit, and that is enforced in Python rather than requested in the prompt, like every limit that has to hold.

**Building it is not the same as it being used**, which is the lesson the menu just taught. So it was probed before being called done. With a full watchlist and two tempting candidates, the model untracked and then researched in the right order in three runs of four, choosing the penny stock to drop both times. The fourth asked for two researches without untracking anything and was refused — and the refusal exposed that the retry's only advice was about cash, which is useless for a full watchlist. With advice matched to the refusal, the retry recovered in three of four.

**A crash was found by accident, and it was waiting for the first trade.** Rendering the new watchlist section raised a formatting error: the holdings loop used a local variable named `price`, which quietly rebound the research-price parameter to a string, and the menu section then formatted that string as a number. It needs a holding and a menu in the same prompt. The analyst holds nothing yet, so it had never fired — it would have crashed the agent's first decision pass after its first buy, which is exactly the pass nobody would want to lose.

**Two things this project had written down were also wrong.** The proxy was believed to hold a card for a whole analysis, making a ten-minute timeout dangerous against a seventeen-minute run; it releases after a single call, and ten concurrent requests against seven backends all completed, the slowest in 38 seconds. And the sweep was believed to have an hour before the open when it has two. Both had been repeated confidently, including earlier the same day.

**Seven cards now split four to the live book and three here.** That is temporary. Once the Gemini Flash-Lite comparison reports, the analyst should take five and the live book two, because this is the long-running experiment and the live book runs a model less than half as slow. It waits for the comparison because that experiment is only readable if the live deployment keeps analysing at the speed its graded signals were produced at — and the watchlist ceiling of twelve has to be measured again at five rather than scaled, since concurrent analyses on these cards contend for host memory bandwidth and do not simply divide.

**Still zero decision passes and zero trades.** Everything above is preparation. Tomorrow morning is the first time any of it is tested by the thing it was built for.
