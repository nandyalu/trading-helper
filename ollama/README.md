# Ollama Modelfiles

Custom context builds for the models the analysis runs on, plus `build.sh` to install one on every backend in the pool.

```sh
./build.sh kotakneo-128k.Modelfile
```

A build has to exist on all four backends. The proxy spreads analyses across them, so a model present on only one turns three of every four runs into a failure.

Once built, the model appears in the settings page's model dropdown and in `/model` on its own — both read the endpoint's live list.

## Why these builds exist

A stock model loads at whatever context its Modelfile asks for, and the pool's backends default to 8192 (`OLLAMA_CONTEXT_LENGTH`). An analysis carries the whole tool-call history, so at 8k the history gets truncated out from under the reasoning loop: the loop stops terminating and the run either dies with a `GraphRecursionError` or, worse, invents the tool output it can no longer see. Both 3B trading models did the latter — they answered the market analyst by writing Python that looked like the data-fetching tool instead of calling it.

## What actually limits the context (measured 2026-08-11)

The cards are 8 GiB (RX 6600, gfx1030), of which ollama will use about 7.5 GiB.

The KV cache is not the constraint. It is already quantized (`OLLAMA_KV_CACHE_TYPE=q4_0` with flash attention on) and costs only 2.6 GiB at 96k. **The compute graph is the constraint, and it scales with `num_batch`:**

| Context | `num_batch` | Total | Placement |
|---|---|---|---|
| 128k | 512 (default) | 13 GB | 40% CPU / 60% GPU |
| 96k | 512 (default) | 10 GB | 23% CPU / 77% GPU |
| 128k | 128 | 8.0 GB | 4% CPU / 96% GPU |
| 96k | 256 | 7.4 GB | 100% GPU |
| 112k | 128 | 6.8 GB | 100% GPU |
| **128k** | **64** | **6.6 GB** | **100% GPU** |

Any CPU split is a failure, not a compromise. A single layer on the CPU costs far more than the batch size ever will.

**`num_batch` is not always the answer.** That table is a llama-3.2-3B, where the compute graph dominates. `phi4-mini` (3.8B, phi3) behaves differently: at 128k it needs 8.9 GiB and spills 12% to the CPU, and halving `num_batch` from 64 to 32 changes nothing at all, because there the KV cache is what does not fit. Its ceiling is 96k at 7.3 GiB — the same context gemma4-e2b-96k runs at, which makes the two directly comparable.

| Model | Largest that fits fully on an 8 GiB card | What limits it |
|---|---|---|
| llama-3.2-3B builds | 128k, `num_batch 64` | compute graph |
| `phi4-mini` | 96k, `num_batch 64` | KV cache |
| `gemma4-e2b-96k` | 96k, default batch | sliding-window attention keeps both small |

So the first thing a new build needs is a fit probe, not an assumption about which knob matters.

The small batch is cheap. Prefill on a 35,000-token prompt:

| Config | Prefill |
|---|---|
| 96k / batch 256 | 490 tok/s |
| 112k / batch 128 | 458 tok/s |
| 128k / batch 64 | 411 tok/s |

Full context costs 16% of prefill speed and *saves* 0.8 GB of VRAM against the 96k build, so both files here use 128k with `num_batch 64`.

## Checking a build

`ollama ps` after a load is the whole test:

```sh
docker exec ollama-pool-a sh -c "ollama run kotakneo-128k hi >/dev/null 2>&1; ollama ps"
```

`PROCESSOR` must read `100% GPU`. `build.sh` prints this for you.

## Benchmarking a build

Do not measure through the proxy. It balances per request, so one analysis's calls scatter across backends and a model can land on a card that still holds another and run mostly on CPU — which is exactly what happened on the first attempt to time these, and made gemma4 look like it ran 69% on the CPU.

Pin the run to one card instead. The pool containers are reachable from the host by their docker-bridge IPs:

```sh
ip=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' ollama-pool-c)
OLLAMA_BASE_URL="http://$ip:11434/v1" ...
```

Three models can then be measured at once, one per card, leaving the fourth free for the running bot.

## Not covered here

`gemma4-e2b-96k`, the current default, was built by hand before this directory existed and is only described in `CLAUDE.md`. It runs at 96k with the default batch because Gemma's sliding-window attention makes its compute graph far smaller than a Llama of the same size. Rebuilding it from a file here would need its exact base blob, which is why it is left alone.
