# Running it yourself

**This is a working experiment, not a product.** It has been run on exactly one machine, and the parts most likely to break are the ones specific to that machine. This page is honest about which those are.

## What you need before you start

| | Why | Can you skip it? |
|---|---|---|
| **Docker** | The app ships as one image | No |
| **Webull sandbox credentials** | The agent's account, and real-time quotes | **No.** The agent refuses to run without them |
| **A model** | Either a local GPU pool or a hosted API key | No, but either works |
| A Discord webhook URL | Notifications | Yes — the site is identical without it |
| A FRED API key | Macro series | Yes, but the news analyst then infers rates from headlines and says so in its own report |

**The hardest requirement is the model**, and the honest options are:

- **A local GPU pool.** What this runs on. Seven 8 GiB cards, and one analysis takes about 19 minutes. Free to run beyond electricity, and slow.
- **A hosted API.** Gemini Flash-Lite does the same analysis in 1.2 to 1.6 minutes. At the measured token counts that is about **$0.056 an analysis** — roughly **$10 a month** for a 9-ticker daily sweep. Fast, and it costs real money.

Nothing else in the design cares which you pick.

## The shortest path

```sh
git clone --recurse-submodules https://github.com/nandyalu/the-allowance
cd the-allowance
docker build -t trading-experiment:local .
```

Then run it with a compose file. `dockge/trading-experiment.compose.yaml` in the repo is the working template, with every setting commented.

The container applies its own database migrations at startup. There is nothing to run by hand.

## Every environment variable

### Required

| Variable | What it does |
|---|---|
| `WEBULL_SANDBOX=1` | **Points at the sandbox.** The agent checks this itself and refuses every order without it |
| `WEBULL_APP_KEY` | From Webull's developer portal |
| `WEBULL_APP_SECRET` | Likewise |
| `WEBULL_OPENAPI_TOKEN_DIR` | Where the exchanged token is cached. Put it on the data volume so a redeploy reuses it |

### The experiment's own numbers

| Variable | Default | What it does |
|---|---|---|
| `AGENT_BUDGET` | `10000` | What the agent starts with |
| `RESEARCH_PRICE_USD` | `0.05` | What one analysis costs it. `0` makes research free |

Both are only defaults for an unset setting — the settings page wins once anyone changes them. They matter because a fresh database has neither, and a container coming up on the wrong budget would have to be corrected by hand on its first run.

### The model

| Variable | Default | What it does |
|---|---|---|
| `TRADINGAGENTS_LLM_PROVIDER` | `ollama` | `ollama`, `google`, `openai`, `anthropic` and others |
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | Where the local pool is |
| `GOOGLE_API_KEY` | — | Only for `google` |
| `TRADINGAGENTS_DEEP_THINK_LLM` | — | The model name. Both stages share one value |
| `TRADINGAGENTS_QUICK_THINK_LLM` | — | Set it to the same thing |
| `TRADINGAGENTS_MAX_CONCURRENT_ANALYSES` | `1` | **Set this to your GPU count.** See below |
| `TRADINGAGENTS_MAX_DEBATE_ROUNDS` | `1` | One. Four costs 2.3x the wall clock and changed nothing measurable |
| `TRADINGAGENTS_MAX_RISK_ROUNDS` | `1` | Likewise |

### Optional

| Variable | What it does |
|---|---|
| `DISCORD_WEBHOOK_URL` | Notifications. A webhook, not a bot — the app only posts. Leave unset for a Discord-free deployment |
| `FRED_API_KEY` | Free from fred.stlouisfed.org. Without it the news analyst infers rates and the yield curve from headlines |
| `LLM_TRACE_DIR` | Writes every LLM call to disk, about 0.4 MB an analysis. A dataset of past runs cannot be collected afterwards, which is why it is on before anyone has decided to train anything |
| `PUBLIC_MODE` | See "Publishing it" below |
| `TRADINGAGENTS_MEMORY_LOG_PATH` | **Put this on the data volume.** It defaults inside the container, where a redeploy deletes it — and it holds every past decision plus the reflection written once the outcome was known |

## Running without a GPU pool

Point it at Gemini instead:

```
TRADINGAGENTS_LLM_PROVIDER=google
GOOGLE_API_KEY=...
TRADINGAGENTS_DEEP_THINK_LLM=gemini-3.5-flash-lite
TRADINGAGENTS_QUICK_THINK_LLM=gemini-3.5-flash-lite
TRADINGAGENTS_MAX_CONCURRENT_ANALYSES=4
```

Two things measured here that are worth knowing:

**Price input and output separately. Never use a blended rate.** List is $0.30 per 1M input and $2.50 per 1M output — an 8x gap — so a blended figure is a function of the completion share rather than a property of the model. Blending once produced a cost estimate 39% too low.

**`gemini-2.5-flash-lite` is retired** and returns `404 NOT_FOUND` on a current key. Use `3.5-flash-lite` or `3.1-flash-lite`.

## Choosing a model, if you are running locally

The rule this project learned the expensive way: **speed rules a model out; behaviour rules it in.**

Five small models were rejected here, all for the same failure. They do not error — they answer fluently, having invented the data. The tell is the token count: a model that never fetched anything spends 42–45k prompt tokens where a working one spends over 100k.

One of them read plenty and still made up every price, from different years in different runs. Its model card claimed tool calling as a strength. Both things were true, and neither predicted anything.

**Test any candidate on a real analysis before trusting it**, and check that the prices in its market report match the actual close.

## Concurrency

**Set `TRADINGAGENTS_MAX_CONCURRENT_ANALYSES` to your number of GPUs, and not more.**

One analysis is internally sequential — the analysts run in turn, then the debate, then the trader — so it never has more than one request in flight and occupies exactly one card. N concurrent analyses is what fills N cards.

Measured on this hardware: fourteen at once and seven at once take **the same total wall clock**, and fourteen doubles the latency of each. The CPU saturates before the GPUs do, because this model family keeps its per-layer embeddings in host RAM. More concurrency past your card count buys nothing.

## Publishing it

The site is meant to be read by anyone. The small write surface is not.

**Run two containers over one volume.** The private one, as configured above. A second with `PUBLIC_MODE=1`, and point your tunnel at that one.

`PUBLIC_MODE` does two things, and the second matters more:

1. **Every write is refused.** Middleware, not a per-route check, so it also covers whatever route gets added later.
2. **No scheduler, no Discord, no trade stream.** Without this, two containers over one database would each sweep — paying twice for the same research — and each decide at 13:35, putting two sets of orders at the broker against one ledger. **None of that arrives as an HTTP request**, so refusing writes alone would not have stopped any of it.

Mount the volume read-write for the public copy. SQLite writes its `-wal` and `-shm` sidecars even to read, and `:ro` fails to open the database at all. The guarantee is `PUBLIC_MODE`, not the mount flag.

## When something goes wrong

**"pull access denied for trading-experiment"** — the image tag has no registry prefix, so Docker resolves it to Docker Hub. Set `pull_policy: never`.

**Every analysis fails with "No available vendor"** — the model asked for an indicator that does not exist, three times, and tripped the vendor circuit breaker. Fixed in this repo: bad arguments no longer count as vendor ill-health. If you see it on an older checkout, that is the cause.

**Reddit `429 Too Many Requests`** — expected. The sentiment analyst scrapes a public RSS feed with no key, and degrades to "no posts found". At high concurrency it happens a lot, and the sentiment analyst is then working with materially less data than it would at low concurrency.

**The agent never trades** — check `WEBULL_SANDBOX=1`, and check the agent is switched on in Settings. It refuses to run in either case, and says so.

**Orders fill but have no stop** — Webull refuses a bracket while cash is unsettled, which happens whenever the agent sells to fund a buy. The app falls back to a plain order plus separately-armed exits, and that second step can fail. The site flags the position and offers a button that rests the missing exits.

**A model reports prices from the wrong year** — it never fetched anything. See "Choosing a model" above. This is not a prompt problem and no amount of instruction fixes it.
