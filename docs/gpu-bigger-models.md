# Running a bigger model on the GPU pool

Started 2026-08-29, continuing the day's GPU work in [gpu-speedup-plan.md](gpu-pool.md). Goal: find out whether a 9B-class model can run on this hardware, on one card or split across two, and get to the bottom of why splitting a model across two cards "wasn't working" — the question this whole day of GPU investigation started from.

## Bottom line

**A 9B model runs correctly on one 8 GiB card, no splitting needed.** Tested Gemma 2 9B (Q4_K_M quantization): loads fully on the GPU, uses about 81% of one card's 8 GiB, and answers correctly at roughly 70 tokens/second reading a prompt and 24-26 tokens/second writing a reply.

**Splitting a model across two cards does work — but only with the right pair of cards, and this pool has exactly one such pair: hellhound and `ollama-pool-e`.** Every other card sits behind a PCIe switch chip on a riser board (see [gpu-speedup-plan.md](gpu-pool.md) for the wiring diagram). Pairing any two switch-connected cards together corrupts the output — not a crash, not an error, just wrong answers, confirmed on **both** raw llama.cpp and ollama itself, on both switch chips, every time it was tried. This is very likely the exact reason multi-GPU splitting looked broken before: it silently produces garbage instead of failing loudly.

**A model that needs more than one card's 8 GiB works well split across hellhound + `ollama-pool-e`.** A 14B model (9 GiB of weights, too big for any single card here) ran correctly at its full native 32,768-token context, using only 65-68% of each card's memory — real headroom to spare. A 24B model (14.3 GiB) was tried too and did not fit — it crashed once VRAM filled past what the KV cache and compute buffers needed on top of the weights.

**Practical recommendation:** if this pool ever wants to run something bigger than 9B, hellhound + `ollama-pool-e` is a real, working option, tested with both plain llama.cpp and ollama itself — and 24B is confirmed too large. Anything else — do not pair two riser-connected cards together for a split model.

## What was tested and how

All tests used the patched llama.cpp build from [gpu-speedup-plan.md](gpu-pool.md) (`/home/kr/tools/llama.cpp`) and, for the final confirmation, a separately downloaded, unmodified `ollama` v0.33.2 binary run as a standalone process (`/home/kr/tools/ollama-portable`) — not the pool's own containers, so none of this touched production. Models used, all downloaded fresh from Hugging Face (except where noted) and kept at `/home/kr/tools/models/`:

- **Gemma 2 9B**, `bartowski/gemma-2-9b-it-GGUF:Q4_K_M`, 5.76 GB. Chosen because it is a mature, text-only, long-stable architecture — the newer `gemma4` family already in this pool's own model set turned out to be incompatible with current llama.cpp (see below), and `qwen3.5:9b`, also already present, hit a similar wall.
- **Qwen2.5-14B-Instruct**, `bartowski/Qwen2.5-14B-Instruct-GGUF:Q4_K_M`, 8.99 GB.
- **Mistral-Small-24B-Instruct-2501**, `bartowski/Mistral-Small-24B-Instruct-2501-GGUF:Q4_K_M`, 14.3 GB — used purely to find the ceiling.

Every generation was checked for a **correct** answer (a real factual question with a known right answer), not just for absence of a crash — this is what caught the silent corruption, which produced no error of any kind.

## Two models already in this pool are not usable with current llama.cpp

Before downloading anything, the plan was to test with a model already on disk. Two attempts failed, both for reasons unrelated to hardware:

- **`qwen3.5:9b`** (already in the pool's model store) — its GGUF file uses a metadata layout (`qwen35.rope.dimension_sections`) that current llama.cpp's parser rejects (expects 4 values, the file has 3). Likely a version-skew issue: this is a very new architecture, and ollama's export and llama.cpp's parser have each moved since this particular GGUF was built.
- **`gemma4:12b`** — shares the same multimodal `gemma4` architecture already found incompatible with mainline llama.cpp earlier the same day (see [gpu-speedup-plan.md](gpu-pool.md)); not retested, since the failure mode (file bundles vision/audio tensors llama.cpp's loader won't skip) applies to the whole family, not just the one variant already tried.

Neither of these is a hardware limitation — both are model-format compatibility gaps in this specific, freshly-built copy of llama.cpp. A model with a more mature, stable architecture (like the Gemma 2 and Qwen2.5 used below) does not hit this.

## Finding 1: a 9B model needs no splitting at all

Loaded on hellhound alone, `-ngl 999` (every layer on the GPU), native 8,192-token context:

- 81% of the card's 8 GiB used.
- 69.8 tokens/second reading the prompt, 24.4 tokens/second writing the reply.
- Correct answers confirmed on two separate questions.

This alone answers half the original question: **an 8 GiB card comfortably holds a 9B model** — no second card required.

## Finding 2: two-card splitting works, but only on one specific pair of cards

llama.cpp's `-sm layer` (split by layer across GPUs) was tested on every practical pairing, using the 14B model (which needs both cards' memory to fit at all, so a working load is proof the split is real, not just tolerated):

| Pairing | Result |
|---|---|
| hellhound + `ollama-pool-e` (both direct to the motherboard, no switch) | **Correct**, every time (tested 3 times with different prompts) |
| hellhound (direct) + `ollama-pool-a` (riser) | **Correct** |
| `ollama-pool-a` + `ollama-pool-c` (both riser, same switch chip) | **Garbled** — nonsense output, twice |
| `ollama-pool-f` + `ollama-pool-g` (both riser, the *other* switch chip) | **Garbled** — same pattern, confirming it is not particular to one switch |
| hellhound + `ollama-pool-e` + `ollama-pool-a` (three-way, two direct + one riser) | **Correct** |
| hellhound + `ollama-pool-a` + `ollama-pool-c` (three-way, one direct + two riser) | **Crashed** (`terminate called without an active exception`) — adding a third, "safe" card does not rescue a pair of riser cards sitting together in the same split |

**The rule that fits every result: a split is reliable as long as at most one of the cards involved is behind a PCIe switch.** Two switch-connected cards in the same split, with or without other cards also present, is unsafe — sometimes it silently corrupts the output, sometimes it crashes outright, but it is never correct.

Each VRAM allocation was checked directly (`rocm-smi --showmemuse`) to confirm the model genuinely split across both cards' memory rather than one card doing all the work — for the working pairs, both cards showed real, roughly proportional usage every time.

## Finding 3: this is confirmed in ollama itself, not just in llama.cpp

The riser-card corruption was first found using the raw, patched llama.cpp build from earlier in the day — worth double-checking it wasn't specific to that build. A separate, unmodified `ollama` v0.33.2 was downloaded and run standalone (not touching the pool's own containers) to check.

The first two attempts at this were misleading: this ollama version can also use a **Vulkan** backend, and Vulkan has its own device-visibility setting, separate from the `HIP_VISIBLE_DEVICES` variable used to restrict which cards ollama's ROCm backend can see. Both attempts silently fell back to Vulkan and spread the model across **all seven cards** regardless of which two were requested — a different, uncontrolled test that happened to produce correct output for an unrelated reason. Setting `OLLAMA_VULKAN=false` forced the same ROCm backend the pool's own containers use, and confirmed the load logs showed exactly the two intended cards each time:

| Pairing (ROCm backend, confirmed via load logs) | Result |
|---|---|
| hellhound + `ollama-pool-e` | **Correct** ("The capital of Germany is Berlin.") |
| `ollama-pool-a` + `ollama-pool-c` (riser) | **Garbled** — "十条【十条结果自然厄行自然行结果" |

Same pairing, same corruption, same nonsense-token pattern as the raw llama.cpp test. **This confirms the original problem was never specific to ollama** — both engines sit on the same ROCm/HIP layer underneath, and the corruption lives there, not in either engine's own code. The two stray Vulkan-backend runs are also worth a note of their own: Vulkan spread a model across all seven cards, mixing riser and direct cards freely, and produced correct output both times — a different code path for moving data between GPUs that this test didn't see fail. Not confirmed as reliably safe on its own (it was never tested as a clean, isolated two-riser-card case the way ROCm was), but a lead worth keeping in mind if ROCm's restriction to one safe card per split ever becomes too limiting.

## Finding 4: the ceiling for two cards is between 14B and 24B

- **14B (9 GiB weights)** on hellhound + `ollama-pool-e`: correct output at the model's full native 32,768-token context, using 65-68% of each card's 8 GiB. Real headroom left over.
- **24B (14.3 GiB weights)** on the same pair: loaded to 84%/83% VRAM on each card, then crashed — almost certainly out of room once the KV cache and compute buffers were added on top of the already-tight weight footprint.

So the honest range for this hardware, split across the two safe cards, is **comfortably up to ~14B, unreliable somewhere before 24B.** Nothing in between was tested; a ~16-18B model is the natural next data point if a specific model in that range is ever a candidate.

## Finding 5: single-card resource use, and what happens with four cards running at once

Ran the same 9B model (Gemma 2 9B) through an actual production `ollama-pool-*` container this time, not a standalone build, and measured CPU and RAM throughout with `docker stats`, sampled twice a second — first on one riser card alone, then on four riser cards at once, each running its own independent copy of the model (not split — this tests concurrent load, not multi-GPU splitting).

### One card (`ollama-pool-a`), one request

| Phase | Time | Speed | CPU | Container RAM |
|---|---|---|---|---|
| Idle | — | — | 0% | 33 MB |
| Loading the model | ~6.4s | — | climbing to 96% | 54 MB → 5.5 GB |
| Reading the prompt (6,708 tokens) | ~12.6s | **531.0 tokens/second** | 176-226% | steady ~5.5 GB |
| Writing the reply (67 tokens) | ~3.4s | **19.9 tokens/second** | 325-352% | dropped to ~2.8 GB |

Confirms what the earlier riser-card test already showed — correct output, and the CPU stays busy the whole time even though the model runs entirely on the GPU, because every generated token still needs the CPU for sampling, detokenizing, and the network response.

### Four cards (`ollama-pool-a`, `-c`, `-d`, `-f`), four requests at the same time

All four came back correct. But they did not finish anywhere near the same time, and the reason is specific:

| Container | Total time | Model-load time | Reading the prompt | Prefill speed | Writing the reply | Decode speed |
|---|---|---|---|---|---|---|
| `ollama-pool-a` | 4.9s | ~0s (already warm from the earlier single-card test) | 0.17s\* | 40,101 tokens/second\* | 4.67s | 18.6 tokens/second |
| `ollama-pool-f` | 32.2s | 15.6s | 13.1s | 511.2 tokens/second | 3.38s | 18.1 tokens/second |
| `ollama-pool-c` | 45.2s | 27.9s | 13.4s | 500.5 tokens/second | 3.82s | 17.8 tokens/second |
| `ollama-pool-d` | 46.3s | 27.9s | 14.0s | 480.7 tokens/second | 4.44s | 17.8 tokens/second |

\* `ollama-pool-a`'s prompt-reading time and speed are not a real measurement — its model and this exact prompt were already sitting warm from the single-card test minutes earlier, so ollama served the prefill entirely from its own prompt cache instead of recomputing it. The 40,101 tokens/second figure is what a cache hit looks like, not what the GPU did; only its reply-writing time is a fair number to compare against the other three.

**The bottleneck was almost entirely in loading the model, not in running it.** Reading the prompt took a consistent 481-511 tokens/second on every genuinely cold card — close to, even a little under, the 531 tokens/second measured on one card alone, so barely any slowdown from three cards reading their prompts at once. Writing the reply held steady around 18 tokens/second on every card, again close to the single-card figure of 19.9. But going from a cold start to a loaded model took **28 seconds** for two of the four containers, worse than four times the ~6-second single-card load time. All four containers were reading the same 5.4 GB model file from the same shared disk mount at once, and that read contention — not GPU time, not host RAM bandwidth during actual generation — is what stretched three of the four requests out past 30 seconds.

Resource peaks recorded across the whole four-card run:

- **CPU:** each container individually peaked between 245% and 333% (2.5-3.3 of the host's 8 CPU threads). Added together, combined CPU load peaked at **613%** — over three-quarters of the entire machine's CPU capacity, from four requests that are each supposed to run on the GPU.
- **GPU:** the three cold-starting cards (`ollama-pool-c`, `-d`, `-f`) each reached 99% busy at their peak, holding 75% of their 8 GiB of VRAM once loaded — matches the single-card VRAM figure (69%) closely enough to call it the same footprint.
- **Host RAM:** climbed from a 6.3 GB baseline to a 7.8 GB peak — with only **161 MB** genuinely free at the tightest point (the rest, over 8 GB, was reclaimable cache, so this was tight but not a hard wall).
- **Swap:** not captured live during this specific run — worth logging directly if this test is repeated, since the host was already carrying real swap usage earlier the same day.

**This is a different bottleneck than the one already documented for the live analyst model (`gemma4-e2b-96k`).** That model's own architecture keeps some data in host RAM during every generation step, so its slowdown shows up as reduced tokens/second throughout the whole run, worse the busier the pool gets. Here, with a standard architecture and no such per-layer host-RAM dependency, tokens/second stayed almost the same on every card once loaded — the whole cost showed up as a one-time pile-up reading the model file off disk. **Practical takeaway: for a model like this, keeping models warm (not reloading them cold) matters more for concurrent throughput than the compute contention documented for the analyst's model** — a cold four-way start is expensive, a warm one barely costs anything, as `ollama-pool-a`'s 4.9-second run showed.

## Finding 6: retested after the RAM upgrade (16 GB → 32 GB, DDR4-3200)

The host's RAM was physically upgraded from one stick per channel (16 GB) to two sticks per channel (32 GB), still at the full 3,200 MT/s — the motherboard held the rated speed with all four slots populated, so this did not hit the speed-derating risk flagged when the upgrade was first discussed. Both tests from Finding 5 were rerun immediately after, with the identical prompt, the identical model, and the identical containers, for a clean before/after comparison.

### Single card (`ollama-pool-a`): no change

| | Before (16 GB) | After (32 GB) |
|---|---|---|
| Prefill speed | 531.0 tokens/second | 533.9 tokens/second |
| Decode speed | 19.9 tokens/second | 19.9 tokens/second |
| Model-load time | ~6.4s | ~5.1s |

Essentially identical — expected, since a single card was never short on RAM to begin with. **One real difference showed up anyway: container memory stayed high (5.7 GB) instead of dropping back to ~2.8 GB after decode, the way it did before.** With more total RAM, the system has no pressure pushing it to reclaim the model's cached pages once they're no longer immediately needed, so it just leaves them sitting there. Not a performance change, just a different, harmless resting footprint.

### Four cards at once: the real story — model-load time roughly halved

| Container | Load time before | Load time after | Prefill speed before | Prefill speed after | Decode speed before | Decode speed after |
|---|---|---|---|---|---|---|
| `ollama-pool-f` | 15.6s | 15.4s | 511.2 tok/s | 487.7 tok/s | 18.1 tok/s | 18.3 tok/s |
| `ollama-pool-c` | 27.9s | 15.1s | 500.5 tok/s | 504.8 tok/s | 17.8 tok/s | 18.5 tok/s |
| `ollama-pool-d` | 27.9s | 8.7s | 480.7 tok/s | 521.5 tok/s | 17.8 tok/s | 18.8 tok/s |
| **Total time for all four to finish** | **46.3s** | **33.0s** | | | | |

**Token generation speed did not move — the whole gain is in how fast the model gets off disk and into VRAM the first time.** This confirms the read-contention theory from Finding 5 directly: with only 16 GB, four containers all cold-loading the same 5.4 GB file at once had almost no spare memory to cache any of it, so most of that reading genuinely hit disk four times over. With 32 GB, there's enough spare capacity for the operating system to hold much more of that file in memory across all four attempts, so later readers increasingly get served from RAM instead of disk — and the two slowest containers felt it most (28s → 15s and 28s → 9s), while the one that was already fastest barely moved (15.6s → 15.4s, since it had the least contention to begin with).

Resource peaks tell the same story:

| | Before (16 GB) | After (32 GB) |
|---|---|---|
| Peak combined CPU (all 4 containers) | 613% | 622% — unchanged |
| Peak GPU busy per card | 99% | 99% — unchanged |
| Peak VRAM per card | 75% | 75% — unchanged |
| Host RAM free at the tightest point | 161 MB | **13.8 GB** |
| Swap used during the test | not captured | **0 — never touched** |

CPU, GPU, and VRAM are all exactly where they were — none of those were ever the bottleneck. Free host RAM at the peak moment is the one number that changed by an order of magnitude, from a hair's breadth of running out to over 13 GB still spare, and swap never engaged at all this time.

**Bottom line: the RAM upgrade paid off, but specifically for the cost of starting several models cold at the same time — not for how fast any model runs once loaded.** For a workload that mostly runs already-warm models (the normal case for the live pool, where `OLLAMA_KEEP_ALIVE` keeps things loaded), this upgrade matters less. It matters most in exactly the situation tested here: several cards all reaching for a model file at once from a cold start.

## Finding 7: the safe-pairing rule was more conservative than it needed to be — corrected after a hardware change

On 2026-08-29, a third card was physically moved from a riser onto the motherboard (going from 2 direct + 5 riser to 3 direct + 4 riser, still 7 cards total). Two things came out of sorting through that move.

### A container going missing after a reboot is not a GPU problem

After the move, the pool's health check showed only 6 of 7 backends. All 7 cards were fine at every hardware layer checked — `lspci` listed all 7, all 7 `/dev/dri/cardN` device nodes existed, and ROCm's own tools saw all 7. The seventh container (`ollama-pool-g`) simply had not restarted: it had exited with code 128 about an hour before the reboot that brought the other six back, and its restart policy (`unless-stopped`) treats that as "someone meant this to stay off," so it didn't rejoin automatically the way its six siblings did. `docker start ollama-pool-g` brought it back immediately, correctly attached to its GPU. Worth knowing for next time: after any host reboot, check `docker ps` for all 7 pool containers, not just the health endpoint — a container that silently didn't come back looks identical to a genuinely unhealthy one from the outside.

### Moving one card reshuffled which container sits on which physical slot — and revealed the real rule

Docker's device mapping (`ollama-pool-a` → `/dev/dri/card0`, `-b` → `card1`, and so on) is fixed and did not change. But **which physical GPU answers to `/dev/dri/card0` did change**, because Linux numbers these devices in ascending PCI bus order, and moving one card renumbers the bus for everything downstream of the slot it moved into or out of. The practical result: `ollama-pool-e`, one of the two cards the original safe-pairing rule was built around, is now **behind a switch** — and `ollama-pool-d` and `ollama-pool-g`, previously riser cards, are now **direct**. A rule written down as "always include `ollama-pool-b` or `ollama-pool-e`" would have quietly become wrong the moment this card moved, without any error to announce it.

Re-running the same correctness tests as Finding 2, with the mapping verified fresh against `rocm-smi --showbus` rather than trusted from before the move, turned up something the original testing never actually checked: **every riser-pair test done originally happened to use two cards behind the *same* switch chip.** Cross-switch riser pairing was never tried. It was tried this time:

| Pairing | Same switch? | Result |
|---|---|---|
| `ollama-pool-b` (direct) + `ollama-pool-e` (now riser) | — | **Correct** |
| `ollama-pool-a` + `ollama-pool-c` (both riser, switch A) | Yes | **Garbled** |
| `ollama-pool-e` + `ollama-pool-f` (both riser, switch B) | Yes | **Garbled** |
| `ollama-pool-a` (riser, switch A) + `ollama-pool-e` (riser, switch B) | No | **Correct** — confirmed twice, once by accident (a HIP-index mix-up on my part) and once deliberately |
| `ollama-pool-d` + `ollama-pool-g` (both now direct) | — | **Correct** |

**The real rule is narrower than Finding 2 concluded: two cards corrupt a split only when they sit behind the exact same switch chip. Any other pairing — two direct cards, one direct and one riser, or two riser cards on *different* switches — is safe.** "Avoid pairing any two riser cards" was an overly cautious reading of data that, by chance, never tested a cross-switch riser pair. This matters because it roughly doubles the number of usable pairings: of the 21 possible pairs across 7 cards, only 2 are actually unsafe (the two cards sharing switch A, and the two sharing switch B) — not the 10 originally assumed.

### Hardware map after the 2026-08-29 move (superseded — see the 2026-08-30 rebuild below)

| Container | HIP device index | Direct or riser |
|---|---|---|
| `ollama-pool-b` (hellhound) | 0 | Direct (CPU's own slot, unchanged since the very first mapping) |
| `ollama-pool-a` | 1 | Riser — switch A |
| `ollama-pool-c` | 2 | Riser — switch A |
| `ollama-pool-d` | 3 | Direct (new) |
| `ollama-pool-e` | 4 | Riser — switch B (changed — used to be direct) |
| `ollama-pool-f` | 5 | Riser — switch B |
| `ollama-pool-g` | 6 | Direct (new) |

Only two pairings were unsafe at this point: `ollama-pool-a` + `ollama-pool-c`, and `ollama-pool-e` + `ollama-pool-f`.

### 2026-08-30 — full rebuild onto risers, for airflow, and the direct-vs-splitter bandwidth gap that motivated it

The user moved every card off the motherboard's direct slots and onto risers, freeing them to sit in a mining-style open case with real airflow instead of crowding the board directly — including hellhound, which now reaches its same CPU-direct slot through a riser cable rather than sitting in it. Before doing this, we measured *why* the two riser types aren't interchangeable, using this host's own numbers rather than general PCIe specs:

| Connection type | Measured link | Approximate bandwidth |
|---|---|---|
| True direct slot, or a plain (non-splitting) riser | 16.0 GT/s, 16 lanes (PCIe 4.0 x16) | ~31.5 GB/s |
| A splitter riser's own uplink back to the motherboard | 5.0 GT/s, 1 lane (PCIe 2.0 x1) | ~0.5 GB/s |

That's roughly a 63x gap. **The plain riser cable itself costs nothing** — every card on one of those negotiates the identical full x16 link a direct slot gets, confirmed on this exact hardware both before and after this move. **The splitter board is what costs bandwidth** — it presents a full x16 face to each GPU plugged into it, but funnels all of them through that single narrow x1 link back to the chipset, shared between every card on that splitter. In practice this mostly costs time loading a model into VRAM, not steady-state token generation, since inference on an already-loaded model barely touches this link at all.

Rebuilt the topology map fresh afterward — physical changes reshuffle bus numbering even for cards that were not touched, so re-verifying rather than assuming was the same discipline as the last move:

| Container | HIP device index | Connection |
|---|---|---|
| `ollama-pool-a` | 0 | Direct riser |
| `ollama-pool-b` (hellhound) | 1 | Direct (CPU's own slot, now via riser) |
| `ollama-pool-c` | 2 | Direct riser |
| `ollama-pool-d` | 3 | Splitter |
| `ollama-pool-e` | 4 | Splitter |
| `ollama-pool-f` | 5 | Splitter |
| `ollama-pool-g` | 6 | Direct riser |

Two other things changed along with the physical layout:

- **The `ollama-pool-a`/`ollama-pool-b` card-node vs. render-node mismatch from earlier is gone.** Checked the same way as when it was first found (`/sys/class/drm/cardN/device` against `/sys/class/drm/renderD1XX/device`) — every container's two device files now agree on the same physical card. Whatever caused the earlier split-numbering, this fresh rebuild resolved it; container-based tests can be trusted again without the manual bus cross-check that was needed before.
- **All three splitter cards now sit behind one single switch chip, not two.** Previously the splitter/riser cards were spread across two separate switches, which left more safe combinations among them. Now, applying the same rule found in Finding 7 above (two cards sharing a switch corrupt a split between them), **no two of `ollama-pool-d`, `ollama-pool-e`, `ollama-pool-f` can ever be safely paired with each other, in any combination.** Every split needs at least one of `ollama-pool-a`, `ollama-pool-b`, `ollama-pool-c`, or `ollama-pool-g` in the group. That's a real reduction from before — fewer safe pairings than the previous two-switch layout offered — traded for meaningfully better cooling.

**This table is the current source of truth; the 2026-08-29 table above it is kept only as history.** Treat any hardware map in this file as stale the moment a card physically moves, and re-verify the same way each time: `lspci -tv` for the real tree, `rocm-smi --showbus` for HIP indices, and `/sys/class/drm/*/device` cross-checked on both card and render nodes for every container before trusting a docker-based test again.

**Confirmed separately: running a model on just one splitter card, with no cross-GPU work at all, is not affected by the same-switch corruption above.** That bug was specific to two cards on one switch trying to work together on a split model — a single card on the same switch, doing its own independent work, is a different situation. Tested `gemma4-e4b-128k` (the full bundled build, not the text-only conversion) on each of the three splitter cards individually: `ollama-pool-d`, `ollama-pool-e`, and `ollama-pool-f` all answered "The capital of Japan is" correctly with "Tokyo," and a longer, 5,015-token prompt on `ollama-pool-d` produced an accurate, coherent summary rather than anything garbled. The narrow x1 uplink measured above shows up as slower model-loading time (12-21 seconds here, versus a direct card's much faster load) — real, but a speed cost, not a correctness one.

## Practical notes for reuse

- Downloaded model files live at `/home/kr/tools/models/` (28 GB) and the ollama-imported copy at `/home/kr/tools/ollama-portable/models/` (17 GB) — 45 GB total, on a disk with 473 GB free, so no urgency to remove them, but worth knowing they're there if disk space ever gets tight.
- The standalone `ollama` binary at `/home/kr/tools/ollama-portable/` is untouched from its official release — useful for any future test that needs to isolate ollama's own behavior from the pool's deployed containers.
- HIP device indices used throughout: hellhound (`ollama-pool-b`) = index 0, `ollama-pool-a` = 1, `ollama-pool-c` = 2, `ollama-pool-d` = 3, `ollama-pool-e` = 4, `ollama-pool-f` = 5, `ollama-pool-g` = 6. These numbers happened to stay the same across the card move described in Finding 7, but which of them are direct vs. riser did not — see that section's table for the current, correct classification. [gpu-speedup-plan.md](gpu-pool.md)'s wiring notes predate the move and are now out of date on this point.
- The production pool (all 7 `ollama-pool-*` containers) was checked healthy before and after every test in this investigation and was not modified.
