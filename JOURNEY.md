# The analyst's journey — what we changed, and why

The app writes its own chronicle: what was bought, what it cost, what the agent said about it, day by day. Read it at `/api/agent/journey`, or on the Auto trader page. Every sentence there is derived from a trade, a charge or a decision pass, so it cannot drift from the book.

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
