# GPU speedup plan

Started 2026-08-29. Goal: get faster token generation, and maybe headroom for a slightly bigger model, from the existing 7-card RX 6600 pool — without buying new hardware.

## Background

The pool runs 7 AMD RX 6600 cards (8 GiB each), one per `ollama-pool-*` docker container, behind `ollama-proxy`. See the repository's [CLAUDE.md](https://github.com/nandyalu/the-allowance/blob/main/CLAUDE.md) "Ollama pool topology" section for the full layout.

The cards report as `gfx1030` because every pool container sets `HSA_OVERRIDE_GFX_VERSION=10.3.0`. Their real chip is `gfx1032` (RDNA2). ROCm does not officially support gfx1032, so this override is required for the cards to work at all.

Two things ruled out first:

- **A different llama.cpp fork** (`stew675/llama-cpp-rdna-boosts`) does not help. It targets RDNA3/3.5/RDNA4 only, and it speeds up a single GPU, not multi-GPU work.
- **Splitting one model across two cards** is not the goal here. The user wants faster tokens/second and possibly a bigger model on **one** card, not model parallelism.

## Bottom line (as of 2026-08-29, end of the extended investigation)

**Building raw llama.cpp from source is not worth doing for this pool.** It is real and measurable at small prompts — roughly 2x ollama's speed at 512 tokens — but that advantage shrinks steadily as the prompt grows and is **completely gone by around 65,000 tokens**, where the two engines measured within 0.3% of each other, confirmed three separate ways (prefill-only, decode-only, and a chained prefill+decode run). The pool's actual workloads run at 96k–131k tokens, past the point where any advantage remains. Switching would mean taking on a manually-built, unpackaged binary with none of ollama's model management, for no real speed gain at the context lengths that matter here.

**The apparent "hang" above ~17k–18k tokens, chased at length below, was never a hang.** It was a real slowdown that just took longer than the timeouts used to detect it — up to several minutes at the largest sizes tested. A one-line upstream community patch (see the 2026-08-29 entries below) removes most of that slowdown and makes the large-context case reliably finish in a normal, consistent amount of time. It does not change the bottom line above — even patched and fully working, large-context throughput still converges to match ollama, it just does so smoothly instead of appearing to hang.

**If this ever needs revisiting:** the one thing not tested here is whether a different `num_batch` now behaves differently with the patch applied — worth a quick check before writing this off permanently, though `num_batch` is chosen for VRAM fit on this hardware (see `ollama/README.md`) and that constraint applies identically to any engine on this card, patched or not.

The full chronological investigation — every dead end, every ruled-out cause, and the two build fixes that came out of it — is kept below, because it documents real, reusable findings (the ollama version lag, the RDNA2 occupancy bug and its fix) even though the overall answer for this pool turned out to be "no."

## What we found

Sources checked 2026-08-29 (web search + GitHub):

1. **Ollama bundles an old llama.cpp.** Ollama's vendored copy was snapshotted in December 2025. AMD-specific speed fixes have landed in upstream llama.cpp since then and are not yet in ollama. One measured case (different AMD chip) showed a 56% token/second gap between ollama's bundled build and a fresh llama.cpp build — 34 tok/s vs 52+ tok/s. ([ollama/ollama#15601](https://github.com/ollama/ollama/issues/15601))
2. **A known RDNA2 flash-attention bug quietly costs speed.** On gfx1030/gfx1031 (gfx1032's close cousins), a ROCm function flash attention depends on (`cudaOccupancyMaxActiveBlocksPerMultiprocessor`) returns a wrong value. This either crashes the run or forces a slow fallback path. A patched build on a dual-RDNA2 setup (RX 6800 + RX 6700 XT) went from under 30 tok/s to over 50 tok/s, with prefill jumping from ~203 to ~1,314 tok/s. Ollama's binaries take the slow fallback quietly instead of crashing, so they never get the speedup either. ([ggml-org/llama.cpp discussion #23310](https://github.com/ggml-org/llama.cpp/discussions/23310))
3. **rocWMMA (a flash-attention accelerator) supports gfx1030/gfx1032.** It is not limited to RDNA3+, as we first guessed. It turns on with one build flag: `-DGGML_HIP_ROCWMMA_FATTN=ON`.
4. **Vulkan (via Mesa's RADV driver) is a separate lane worth testing later.** One report found Vulkan beating ROCm on token generation for small-to-mid models on consumer AMD cards — exactly the size range these 8 GiB cards run. Not started yet; ROCm is the first thing to measure since it is what the pool already uses.

None of items 1–3 are confirmed on an RX 6600 specifically yet. The RDNA2 data points found are RX 6800/6700 XT (same generation, different card).

## Host environment (checked 2026-08-29)

- ROCm 7.2.1 is already installed on the host at `/opt/rocm` — no ROCm install needed.
- `rocminfo` confirms all 7 cards are visible from the host directly, each reporting as `gfx1030` / "AMD Radeon RX 6600".
- `cmake` is missing from the host and needs installing (`sudo apt install cmake`).
- `hipcc`, `git`, and a C++ compiler (`g++`) are already present.
- The user `kr` is already in the `render` and `video` groups, so no permission changes are needed to reach `/dev/dri` and `/dev/kfd`.
- Docker is available and can already see the running pool containers (`ollama-pool-a` … `-g`, `ollama-proxy`), because the Docker socket is shared with this session.

## Plan

### Step 1 — build llama.cpp from source

1. Install `cmake` on the host.
2. Clone `ggml-org/llama.cpp` (upstream master, not the RDNA-boosts fork — it does not target this card's generation).
3. Configure the build with the HIP backend, targeting `gfx1030`, and turn on rocWMMA flash attention:
   `-DGGML_HIP=ON -DAMDGPU_TARGETS=gfx1030 -DGGML_HIP_ROCWMMA_FATTN=ON`
4. Build `llama-bench` and `llama-server` (or `llama-cli`).

### Step 2 — benchmark against ollama, apples-to-apples

1. Pick one model and quantization that ollama already serves in the pool, so the comparison is fair.
2. Run `llama-bench` with the new build, pinned to a single card the same way the pool containers are pinned (one `HIP_VISIBLE_DEVICES` / one `/dev/dri/cardN` + `renderD1xx` pair).
3. Compare its prefill and token-generation numbers against ollama serving the same model/quant/context on the same card.
4. Record the numbers here, with the exact command and card used, so the result can be checked again later.

### Constraints while testing

- **All 7 cards are already assigned.** They went 4 to the live deployment and 3 to a second analyst experiment when this was written; that second deployment ended on 2026-09-01, and the one that remains gets all seven — see the pool topology notes in [CLAUDE.md](https://github.com/nandyalu/the-allowance/blob/main/CLAUDE.md). Either way there is no idle spare card, so a benchmark competes with whatever is running at that moment.
- Per the same notes, that contention **costs latency, not failures** — the proxy queues rather than errors. Keep each benchmark run short to keep that cost small.
- Do not change the running pool containers, `dockge/ollama-pool.compose.yaml`, or any deployed config as part of this benchmarking work. This plan is measurement only until the numbers are in.

### Not started yet

- Testing the Vulkan/RADV backend as a second lane.
- Deciding whether — and how — to roll a confirmed win into the actual pool (a new container image, a newer ollama build, or replacing ollama with a raw `llama-server` on one backend as a trial).
- Testing whether a 9B-class model fits on one 8 GiB card at a workable context, once token generation itself is faster.

## Status log

- **2026-08-29** — Plan written. Confirmed host already has ROCm 7.2.1 and GPU group permissions; only `cmake` is missing. Starting step 1.
- **2026-08-29** — Installed `cmake` with `pip3 install --user cmake` (no `sudo` needed — this session has no root password). Cloned upstream `ggml-org/llama.cpp` into `/home/kr/tools/llama.cpp`. Configured the build with `-DGGML_HIP=ON -DAMDGPU_TARGETS=gfx1030 -DGGML_HIP_ROCWMMA_FATTN=ON`; cmake found the HIP compiler and hipBLAS cleanly. Compiling now in the background (`cmake --build build -j 8`).
- **2026-08-29** — Found the exact model file to benchmark against, for a fair comparison. Ollama's model blobs live at `/opt/stacks/ollama-gpus/ollama/models/blobs/`, are world-readable, and are plain GGUF files under a hash name. The live `gemma4-e2b-96k` model is `sha256-4e30e2665218745ef463f722c0bf86be0cab6ee676320f1cfadf91e989107448` (7.16 GB), running at `num_ctx=98304`, default batch size. `llama-bench` can point straight at this file — no re-download needed, and no risk of comparing against a different build of the model.
- **2026-08-29** — Build finished cleanly (`llama-bench`, `llama-cli`, `llama-server` all built). Mapped the PCI wiring with `lspci -tv`: five of the seven cards (`ollama-pool-a`, `-c`, `-d`, `-f`, `-g`) sit behind one of two PCIe switch chips that fan one motherboard slot out to three or four cards each — the riser setup. Two cards have no switch chip in front of them: `ollama-pool-b` (bus `03:00.0`) is wired straight into the CPU's own dedicated PCIe slot, and `ollama-pool-e` (bus `15:00.0`) sits on a chipset-fed slot with no switch but still routed through the chipset. The user confirmed **`ollama-pool-b` / host device `card1` / `HIP_VISIBLE_DEVICES=0` is "hellhound"** — the card to benchmark on, since it is the one true direct-to-motherboard connection with the least PCIe-topology noise.

  **Superseded 2026-08-29 (same day, later): a physical card was moved from a riser to the motherboard, changing which cards sit behind a switch.** `ollama-pool-e` is no longer direct — it moved behind a switch as a side effect of the reshuffle, even though it wasn't the card that physically moved. `ollama-pool-b` (hellhound) is unaffected and still direct. See [bigger-model-plan.md](gpu-bigger-models.md), Finding 7, for the current wiring map and the corrected rule for which card pairs are safe to run a model split across — the rule here turned out to be more conservative than the real hardware constraint.
- **2026-08-29** — Measured ollama's real baseline on hellhound directly (bypassing the proxy, hitting `ollama-pool-b`'s docker-bridge IP), using a 32,515-token cache-busting prompt against the live `gemma4-e2b-96k` model at its production settings (`num_ctx=98304`, flash attention on, `q4_0` KV cache): **968.8 tok/s prefill, 37.4 tok/s decode** (256 tokens generated).

- **2026-08-29 — `gemma4-e2b-96k` cannot be loaded by plain llama.cpp at all.** `llama-cli` refused the exact GGUF file ollama runs, with `error loading model: done_getting_tensors: wrong number of tensors; expected 2012, got 601`. The file itself is intact (7.16 GB on disk, matches the manifest exactly) and its own header declares 2012 tensors. `gemma4` is a multimodal architecture — the same file carries text, vision, and audio tower tensors together, confirmed by scanning its metadata (`gemma4.vision.*`, `gemma4.audio.*` keys present). This app only uses the text tower. Freshly-built llama.cpp's loader for this very new architecture requires every tensor in the file to be wired into the graph it builds; it only wired up the 601 text tensors and refused to load the other 1,411 rather than skip them. **This is a real compatibility gap in current llama.cpp for this specific, very new model family — not a speed problem, and not something a build flag fixes.** A true side-by-side test of the live model isn't possible today. Switched to `llama32-3b-128k` (plain `llama` architecture, already in the pool, well-documented in this file's own notes) to still get real numbers on the two speed mechanisms found in the write-up above.

- **2026-08-30 — Tried loosening the loader to accept the extra tensors, since the app only needs the text tower anyway. The load succeeded, but the model itself turned out to be broken, independent of the missing-tensor question.** `llama-model-loader.cpp` has a `partial` setting on the exact check that rejected this file — when set, it logs a note that some tensors in the file "belong to a sibling model" and continues instead of refusing to load. It's real, designed-in behavior (the log message describes precisely this multimodal-file scenario), but nothing in the current codebase actually turns it on. Flipped it on for the main model load (`llama-model.cpp:1666`, one line) and rebuilt.

  The file loaded cleanly with no error this time. But asked "The capital of Japan is," it answered `Japan is Japan is Japan is Japan is` — not a chat-template mismatch (this was raw completion, no template involved), and not a fluke: a second, unrelated prompt (`Two plus two equals`) produced the same kind of repetitive nonsense. The load log separately flagged an unrelated tokenizer irregularity too (`control-looking token: 212 '</s>' was not control-type; this is probably a bug in the model`) — llama.cpp's own words, not a guess.

  **This closes the door on both routes to a working text-only gemma4, not just this one.** The 601 text-tower tensors this loosened check uses are the *same* 601 tensors a properly stripped, smaller GGUF file would contain — stripping the file for real would change nothing about which weights get used or how the graph runs, so it would hit the identical broken output. The real problem was never the extra vision/audio tensors sitting in the file; it's that llama.cpp's support for this very new architecture doesn't yet produce correct output for it at all, tensor-count mismatch or not. Making gemma4 work here would mean waiting on llama.cpp's own gemma4 support to mature, or filing a real upstream bug report — not something fixable from this side by trimming the model file.

- **2026-08-30 — That conclusion was wrong. Converting properly from the original checkpoint, instead of patching around ollama's file, produces a genuinely correct model.** The logic above assumed the 601 tensors used either way would behave identically regardless of how the file was built. That assumption turned out to be the flaw: it's not just *which* tensors are used, but *how they were packaged and quantized* that mattered, and ollama's own export of this very new architecture carried some difference from what llama.cpp's own conversion path produces — enough to break inference even though the loosened loader check let it load.

  llama.cpp's conversion tooling turned out to have full, non-stub support for gemma4, including a proper text/vision-audio split via a `--mmproj` flag (`conversion/gemma.py`: `Gemma4Model` for text, `Gemma4VisionAudioModel` for the rest) — the standard way llama.cpp handles multimodal models, just not the path ollama took when it built the bundled file tested above. Downloaded the original checkpoint directly from Hugging Face (`google/gemma-4-E2B-it`, Apache 2.0, 10.3 GB — explicitly listed as a supported example in the conversion code, all but confirming it's the exact source ollama itself built from), converted with `convert_hf_to_gguf.py` (no `--mmproj`, so only the text tower), and quantized the result with `llama-quantize`.

  Needed one dependency fix along the way, unrelated to llama.cpp itself: the pinned `transformers==4.57.6` couldn't parse this model's tokenizer config (`extra_special_tokens` is a plain list in this file; that `transformers` version's own code expects a dict there and throws `AttributeError: 'list' object has no attribute 'keys'`) — a version-skew bug in the dependency, not in llama.cpp's conversion code. Upgrading to the latest `transformers` (5.16.1) fixed it immediately.

  **The result: a real, working, correct model.** The conversion produced exactly 601 tensors — the same number the loader was always trying to satisfy — confirming this really is the clean text tower. Quantized to Q4_K_M it's **3.43 GB, less than half of ollama's 7.16 GB bundle**, since the vision and audio weights are gone entirely rather than just quantized down. Tested with the exact two prompts that produced garbled output on ollama's file (`gpu-speedup-plan.md`'s earlier entry): `"The capital of Japan is"` → `"Tokyo."`, `"Two plus two equals"` → `"four. This is a true mathematical statement."` Both correct. A longer prompt showed the model correctly using its documented "thinking" mode, reasoning through the answer step by step before stating it. VRAM use at a small context: 32% of one 8 GiB card, room to spare.

  **Where this leaves things:** a genuinely correct, smaller, faster-loading text-only gemma4 is possible — but only by converting from the original Hugging Face checkpoint through llama.cpp's own tooling, not by editing ollama's existing file. The file lives at `/home/kr/tools/models/gemma-4-E2B-it-text-Q4_K_M.gguf`. Not yet tested: production-scale context length (128K native, per the model card) and whether ollama itself could import and serve this converted file the way it already does for other locally-supplied GGUFs.

- **2026-08-30 — Confirmed correct at production-scale context, both in raw llama.cpp and in ollama itself, and turned up a real, live misconfiguration along the way.**

  **Raw llama.cpp, hellhound, production settings (98,304 context, `q4_0` KV cache, flash attention on):** loaded and answered correctly at 86,400 tokens of prompt — "The provided text consists entirely of repeated filler sentences, numbered from 0 to 999..." (an accurate description of the test input). **656.5 tok/s prefill, 31.7 tok/s decode.** Resource use: 148% CPU (about 1.5 cores), 2.7 GB process RAM, GPU averaging 82% busy — and only **27% of the card's 8 GiB VRAM**, even at 86,400 tokens, versus how tight the original bundled file ran in earlier tests. The smaller file isn't just faster to load; it leaves real headroom.

  **Imported into an actual `ollama-pool-*` container** (copied the converted GGUF in with `docker cp`, built it with `ollama create` and `num_ctx 98304`, matching production) and re-tested the same way. First attempt looked broken — an empty `response` field — until checking ollama's separate `thinking` field showed why: the model was spending its entire token budget on its documented step-by-step reasoning mode before ever reaching the final answer, not failing. With `think: true` and more tokens, the reasoning was complete and correct: *"...designed to construct a production-scale cache-busting prompt... intended for testing the converted text-only Gemma4 model."* A fresh, uncached prompt gave real timing: **649.9 tok/s prefill, 29.4 tok/s decode** at 73,915 tokens — closely matching the raw llama.cpp numbers, as expected since both run the same engine underneath.

  **The real find: `ollama-pool-b`'s container has very likely been running on the wrong physical GPU since the card move, and so has `ollama-pool-a`.** Checked because the GPU that lit up for the "hellhound" test didn't match the card historically used for hellhound benchmarks all day. Docker passes each container two device files together — a `/dev/dri/cardN` node and a `/dev/dri/renderD1XX` node — and ROCm's actual compute path uses the render node, not the card node. Checked every container's pair against the current bus mapping (`/sys/class/drm/*/device`, cross-referenced with `rocm-smi --showbus`):

  | Container | Card node → bus | Render node → bus | Match? |
  |---|---|---|---|
  | `ollama-pool-a` | `card0` → `09` | `renderD128` → `03` | **No — swapped with pool-b** |
  | `ollama-pool-b` | `card1` → `03` | `renderD129` → `09` | **No — swapped with pool-a** |
  | `ollama-pool-c` through `-g` | — | — | All match, card and render node agree |

  Confirmed with a live test, not just by reading device files: loaded the converted model into `ollama-pool-b`, ran a real request, and watched `rocm-smi` — VRAM and 99% GPU activity showed up on bus `09` (a riser card, behind switch A), while bus `03` (hellhound, the card the container's name and card-node both point to) sat at 0% the entire time. `ollama-pool-a` almost certainly has the mirror-image problem, sending its work to hellhound instead of its own card, though only `-b` was directly tested here.

  This is very likely a side effect of the same PCI renumbering documented in `bigger-model-plan.md`'s Finding 7 — card nodes get reassigned to match current bus order, but the earlier work only checked and fixed the card-node side, not render nodes, and had no reason to suspect the two could disagree with each other. **Every number this file has ever labeled "hellhound" from a docker-container-based test (as opposed to a raw `HIP_VISIBLE_DEVICES` test, which is unaffected and remains reliable) may actually have run on a different physical card.** Not yet fixed, by the user's choice — needs the `dockge/trading-bot.compose.yaml` device list corrected for these two containers and both restarted, or at minimum the mismatch needs to be re-checked any time a card is physically moved again, the same discipline already called for around the card-to-switch topology itself.

- **2026-08-30 — Repeated the full text-only conversion on the model actually running in production: `gemma4-e4b-qat`, at its real 131,072-token context.** The E2B test above proved the method; this repeats it on the bigger, real model to see whether the same approach and the same numbers hold up.

  Downloaded `google/gemma-4-E4B-it-qat-q4_0-unquantized` from Hugging Face (15.9 GB) — the "unquantized QAT" release, i.e. full-precision weights extracted from Google's own quantization-aware training pipeline, meant for exactly this kind of downstream conversion. Converted text-only (666 tensors this time, vs E2B's 601 — expected, this is the bigger 4B-active model) and quantized to **Q4_0 specifically, not Q4_K_M** — QAT calibrates a model for one target quantization scheme, and this checkpoint's name says which one. Result: **5.15 GB**, one file, on disk at `/home/kr/tools/models/gemma-4-E4B-it-qat-text-Q4_0.gguf`.

  Quick correctness check first, small prompt: "The capital of France is" → **"Paris"**, correct. Then the full test, both ways, at 113,300–113,315 tokens of context (as close to the 131,072 ceiling as a workable test prompt allows) — both produced accurate, on-topic summaries of the (deliberately repetitive) test input, not garbled text.

  | | Raw llama.cpp (hellhound) | ollama (`ollama-pool-e`, unaffected by the device mismatch above) |
  |---|---|---|
  | Prefill | 469.6 tok/s | 427.9 tok/s |
  | Decode | 15.6 tok/s | 14.7 tok/s |
  | Peak CPU | 166% | 346% |
  | Peak RAM (process/container) | 3.3 GB | 5.7 GB |
  | GPU busy (peak / average) | 99% / 89% | 99% / 91% |
  | Peak VRAM | 52% | 52% |

  **Same shape of result as E2B: correct, real, and comfortably within one 8 GiB card even at full context** — 52% VRAM used at 131,072 tokens is real headroom, not a tight fit. Ollama again runs somewhat hotter on CPU and RAM than raw llama.cpp for the same work, consistent with the orchestration overhead seen throughout this file; prefill and decode speed track closely between the two either way, as expected since both run the same underlying engine.

  Decode speed here (14.7–15.6 tok/s) is noticeably slower than E2B's (27.7–31.7 tok/s) at a similar context — expected and not a red flag, since E4B does roughly twice the active compute per token (4B vs 2B active parameters) for a real quality difference, the same tradeoff CLAUDE.md's own model-selection notes already describe between these two.

- **2026-08-30 — Measured against the exact baseline `ollama/gemma4-e4b-qat-128k.Modelfile` already documents, at the same 6.8k-token prompt scale that baseline uses, same card (`ollama-pool-e`), same day.** The Modelfile's own comment records `gemma4:e4b-it-qat` (stock) at 1,122 tok/s prefill / 43.7 tok/s generation / 3.7 GiB VRAM at 128k, measured 2026-08-26. Re-ran both the stock model and the text-only conversion fresh today, live, rather than trusting either number cold:

  | | `gemma4:e4b-it-qat` (stock, remeasured today) | Text-only (converted) |
  |---|---|---|
  | Prefill, 6,515-token prompt | 986.8 tok/s | 998.7 tok/s |
  | Decode | 33.5 tok/s | 33.5 tok/s |
  | On disk | 6.1 GB | 5.15 GB |
  | VRAM at 128k (measured after a real request) | 5.36 GiB | 4.20 GiB |
  | Correctness | Correct | Correct |

  **Two honest findings, not one convenient one:**

  1. **Stripping the vision/audio weights gives essentially no speed gain — about 1% on prefill, none measurable on decode.** This makes sense on reflection rather than being a disappointing result: prefill and decode speed are governed by compute over the *active* weights, which are byte-identical between the stock file and the stripped one. The vision/audio tensors were never being computed on to begin with — removing dead weight from a file doesn't speed up math that was never touching it. The small (~1%) prefill gain seen on the E2B model earlier in this file is not a pattern that repeats at E4B's scale; it's more likely measurement noise than a real effect of stripping.
  2. **The real, repeatable win is memory footprint.** ~1 GB less on disk, ~1.16 GiB (22%) less VRAM at the same 128k context — real headroom, not speed.

  **One number doesn't reconcile, and it's recorded here rather than quietly dropped:** today's stock-model VRAM reading (5.36 GiB) is meaningfully higher than the Modelfile's own documented 3.7 GiB. The most likely explanation is measurement timing — today's figure was taken *after* a real 6.8k-token request had run, which would show a populated KV cache and sized scratch buffers, where the original 3.7 GiB may have been a freshly-loaded, never-used snapshot. Plausible, but not confirmed against how the original number was actually taken — flagged as an open discrepancy, not resolved.

- **2026-08-30 — Tried the same text-only strip on `gemma4:12b`, since CLAUDE.md already documents it spilling 2-5 layers to CPU even in its QAT build. Recovered VRAM did not fix that — and testing it surfaced a real correctness bug, not just a capacity limit.**

  Downloaded `google/gemma-4-12B-it-qat-q4_0-unquantized` (24 GB), converted text-only (667 tensors, 23.8 GB in bf16), quantized to Q4_0 (matching the QAT calibration, same as E4B) — **6.98 GB**, already close to one card's whole 8 GiB before any KV cache.

  **With `llama-server`'s default settings (4 parallel slots), it refuses outright** — its own safety check catches that forcing every layer onto the GPU (`-ngl 999`) can't fit and aborts rather than trying. That default reserves KV cache for 4 slots at once, which isn't how this pool actually uses a card (one analysis per GPU) — so re-tested with `-np 1`, matching real usage.

  **At one slot, it does technically load with every layer on GPU** (7.35–7.73 GiB depending on quantization, 92–97% of the card) — no crash, no error. **But the output is garbage:** `"The capital of Japan is"` → `"7151137151"`, `"1761311111"`, `"5555517177"` — not almost-right, not a template issue, just wrong digits, on every attempt at high layer counts.

  Traced it down carefully, one variable at a time:
  - **Not the conversion.** The unquantized bf16 file (uses the identical conversion this file already validated on E2B and E4B) answers correctly: *"The user is asking for the capital..."*
  - **Not just Q4_0.** Requantized to Q4_K_M instead — still garbled at high GPU-layer counts.
  - **Not VRAM pressure.** Tested at 47 of 48 layers (93% VRAM, tight) — garbled. Tested at 32 of 48 layers (67% VRAM, real headroom) — **still garbled.** Only at 20 of 48 layers did it answer correctly again.

  **So this isn't a memory-capacity problem at all — it's a genuine correctness bug that appears somewhere between putting 20 and 32 of this model's 48 layers on the GPU, independent of how much VRAM is actually free.** Given how new gemma4 support is in llama.cpp generally (the same theme as the earlier tensor-count and tokenizer-config issues found for E2B and E4B), the most likely explanation is a bug specific to how llama.cpp splits a large number of this architecture's layers between GPU and CPU — not something stripping the vision/audio weights can fix, since it isn't a capacity problem to begin with.

  **Direct answer to the question asked: no — even after stripping, `gemma4:12b` does not run reliably with most of its layers on the GPU on this hardware.** The safe, correct configuration found here (20 of 48 layers) is well short of "fits completely," and offloading further doesn't get closer to that goal, it gets closer to silently wrong output. This doesn't contradict CLAUDE.md's existing "2-5 layers spill to CPU, QAT doesn't rescue it" finding — it extends it: the ceiling isn't just about size, there's a correctness wall in the way too, and it sits well below what stripping the vision/audio weights alone could ever close.

  **26B was not attempted, by decision.** Its Hugging Face checkpoint is 51.6 GB — before any of today's findings, the arithmetic case against it was already strong: as a MoE model, all 26B parameters must be VRAM-resident regardless of only 4B being "active" per token, and even at 4-bit that's roughly 13 GB of weights alone, far more than stripping ~1-1.2 GiB of vision/audio (the E4B-measured savings) could ever close. Today's 12B correctness bug adds a second, independent reason not to expect a useful result: a bigger model needs even more GPU-resident layers to be worth running at all, deeper into the same broken territory just found. Closed here rather than spending the download on a near-certain negative result — revisit only if something changes the arithmetic (a fix to the layer-split bug found above, or a smaller MoE variant).

  **This closes the "can we fit 12B/26B on GPU" line of investigation.** Summary for anyone picking this up later: stripping vision/audio genuinely helps disk size and VRAM footprint at model sizes that already fit (E2B, E4B — see the earlier entries), but neither 12B nor 26B is a real candidate for this hardware, for two different reasons that stripping can't touch — a correctness bug for 12B, raw MoE weight size for 26B.

- **2026-08-29 — Confirmed real speedups at small-to-medium prompt sizes, on `llama32-3b-128k`, same card (hellhound), same quantization, same batch size (64), flash attention on both sides:**

  | Prompt size | ollama (production) | raw llama.cpp | Speedup |
  |---|---|---|---|
  | 512 tokens (prefill) | — | 1,031.9 tok/s | — |
  | 512 tokens → 64 generated (decode) | — | 75.8 tok/s | — |
  | 29,034 tokens (prefill) | 462.2 tok/s | — | — |
  | 38 generated (decode) | 36.0 tok/s | — | — |

  At small scale, raw llama.cpp's prefill and decode both come in around **2x** ollama's production numbers — matching what the research write-up predicted from the vendored-version lag and the rocWMMA flash-attention build flag.

- **2026-08-29 — But there's a hard performance cliff between 16k and 29k tokens, and it is not the RDNA2 flash-attention bug found in research.** Stepping the prompt size up on pure prefill (no generation): 512 → 1,031.9 tok/s, 8,192 → 790.5 tok/s, 16,384 → 613.5 tok/s — a normal, gradual decline. At 29,034 tokens (the exact size ollama processed in 63 seconds above), the same run **did not finish in over 8 minutes** and was killed. Ruled out two explanations directly:
  - **Not out of VRAM.** Watched `rocm-smi` live during the hang: only 38% of VRAM was allocated, GPU compute was pinned at 99% "busy," but memory read/write activity sat around 10-11% — the GPU is spinning on real but very inefficient work, not paging to host memory.
  - **Not specific to flash attention.** The same hang reproduced with `-fa off`, which should bypass the rocWMMA kernels entirely.

  The "99% busy, almost no memory traffic, no forward progress" signature matches a different, broader ROCm bug on gfx1030: a runtime function several kernels use to size their own launch parameters (`cudaOccupancyMaxActiveBlocksPerMultiprocessor`) returns a wrong answer on this GPU generation, and the fallback path it forces is drastically slower — not just in the flash-attention kernel this project's research first found it in, but apparently in other kernels too, at large batch counts. **Net effect: raw llama.cpp is a real win at the context lengths this quick test used, but currently breaks down badly at the context lengths the pool actually runs at (29k+ up to 98k-131k) — so it is not yet safe to roll into the live pool.**

- **2026-08-29 — The known community patch does not fix this, and the cliff is not gradual — it's a sharp line at a specific token count.** Applied the workaround from `ggml-org/llama.cpp` discussion #23310 (`ggml/src/ggml-cuda/fattn-common.cuh:1114` — soften `GGML_ASSERT(max_blocks_per_sm > 0)` into a fallback that logs a warning and continues with `max_blocks_per_sm = 1`), rebuilt, and reran the 29,034-token case: still hung past 100 seconds. Expected, in hindsight — that code only runs when flash attention is active, and the earlier `-fa off` test already showed the hang happens without flash attention at all. So this is a **different bug** from the one the research found. Bisected the actual threshold directly:

  | Prompt size | Result |
  |---|---|
  | 16,384 tokens | 613.5 tok/s — fine |
  | 17,000 tokens | 603.6 tok/s — fine |
  | 18,000 tokens | hangs (>60s, no result) |
  | 22,000 tokens | hangs (>60s, no result) |
  | 29,034 tokens | hangs (>8 min, no result) |

  **The break point sits between 17,000 and 18,000 tokens, and it is sharp, not gradual** — throughput was still declining smoothly and reasonably right up to 17,000, then something stops finishing at all just above it. A resource limit or counter overflow being crossed fits this shape far better than a performance regression does; a true slowdown would keep declining smoothly instead of falling off a cliff. Not yet narrowed further (18,000 was the first size tested above the working boundary), and not yet confirmed whether this reproduces on `-fa off` at this specific, narrower boundary (only confirmed at 29,034 so far).

  **Practical read for the pool today:** this puts the safe zone under roughly 17,000 tokens of prompt content — well short of what any of the pool's builds actually need (96k–131k). Until this is root-caused, raw llama.cpp cannot replace ollama for the pool's real workloads, even though it is a genuine ~2x win in the range that does work.

- **2026-08-29 — Ruled out a ubatch/batch mismatch, and confirmed the cliff isn't flash-attention-specific at the narrow 18,000-token boundary either.** Retested 18,000 tokens with `-ub 64` explicitly matched to `-b 64` (previously left at its default of 512): still hung. Retested with `-fa off` at this exact boundary (earlier `-fa off` test was only done at 29,034): still hung. Neither explains it.

- **2026-08-29 — Confirmed this is not a driver-level hang.** Checked `journalctl -k` for GPU reset / ring-timeout messages during the hang: none. AMD's driver has its own watchdog that resets and logs when a GPU genuinely locks up; it never fired. Whatever is happening, the driver still considers the card healthy and responsive.

- **2026-08-29 — `rocprofv3` (ROCm's own kernel-level profiler) can't capture this, because it only writes its trace file on a clean process exit** — killing the hung process after 30 seconds left an empty output directory. Fell back to `strace -c` for 20 seconds during the hang instead: **1,420,653 `ioctl` calls in 20 seconds (~71,000/second, 97.7% of all syscall time).** `ioctl` is how the ROCm driver submits work to the GPU and checks on it. A sustained rate that high is consistent with llama.cpp's normal low-latency design (it spin-polls the GPU for completion instead of sleeping), so it confirms the CPU is genuinely waiting on a real, still-running GPU computation — it does not by itself identify *which* kernel is the slow one.

  **Where this stands:** the break point is real, sharp, reproducible, and not explained by any of the mundane causes checked so far (VRAM, flash attention, batch-size mismatch, driver hang). Pinning down the exact kernel responsible would need either a live GPU debugger attach (`rocgdb`) or adding debug instrumentation to `ggml-cuda` and rebuilding — a meaningfully bigger step than what's been tried so far, and one that ties up a production card for extended stretches while it runs.

- **2026-08-29 — Attached `rocgdb` directly (launched the process under the debugger from the start, since attaching to an already-running process is blocked by this host's `ptrace_scope` setting) and got a real answer: it is not a host-side loop.** The main thread is stuck inside exactly one call: `llama_decode` → `llama_context::process_ubatch` → `llama_context::graph_compute` → `ggml_backend_sched_graph_compute_async` → `ggml_backend_cuda_synchronize` — the function that waits for a dispatched GPU kernel to finish. The other two threads are idle, sitting in `ioctl` inside AMD's HSA runtime library — ordinary background housekeeping, not doing real work. **This rules out a host-side loop entirely: the code has submitted one single unit of GPU work and is waiting on it — the GPU itself is either taking catastrophically long or genuinely stuck on that one dispatch.**

  Finding the exact ggml-cuda kernel responsible from here needs GPU-side wave debugging (enabling debug hooks in the ROCm runtime so a debugger can see code actually executing *on* the card, not just the host side waiting on it) — a further, more fragile step than what's been done so far — or reading through `ggml-cuda`'s kernel-selection code by hand for a branch keyed on context/batch size near 17k–18k tokens.

- **2026-08-29 — Tried GPU-side wave debugging; it didn't expose anything.** Relaunched the same reproduction under `rocgdb` with `HSA_ENABLE_DEBUG=1` set (the standard way to ask ROCm's runtime to register with a debugger so it can show code running on the GPU itself, not just the host side waiting on it). Interrupted it again at the same point: identical result to the run without the env var — only the same three host threads, no GPU-side wave threads exposed. Getting real visibility into what's executing on the card needs more setup than one environment variable (likely deeper ROCm debug-mode configuration, possibly kernel-driver-level support) — a bigger side investigation than fits here today.

  **Status: paused pending a decision on how deep to keep going.** What's solid and reusable regardless of what happens next: a precise reproduction (exact model, exact flags, the sharp 17k/18k token boundary), five ruled-out causes (VRAM, flash attention, batch/ubatch mismatch, driver-level hang, a known unrelated RDNA2 occupancy bug), and a real stack trace proving the stall is on the GPU side, not a host loop. That is enough on its own to file as a well-documented upstream bug report even without the exact kernel identified.

- **2026-08-29 — Read through the quantized-matmul kernel code by hand (`ggml/src/ggml-cuda/mmq.cu`, `mmq.cuh`) and found a strong architectural suspect, though not proven.** The stack trace's `ggml_backend_cuda_synchronize` call, on a model whose KV cache is quantized (`q4_0`), routes through llama.cpp's "MMQ" (matrix-matrix-quantized) kernel — the same kernel handles both the K-cache × Q attention math and the model's regular weight matmuls, whenever the left-hand matrix is quantized. Inside it (`mmq.cuh:1393-1473`), there are two different ways to spread a matmul's work across the GPU's compute units: a simple tiled grid, or a more elaborate "stream-k" scheme where multiple GPU blocks cooperatively finish a shared tile through a "fixup" buffer, coordinated via cross-block signaling.

  **That cross-block coordination is exactly the kind of thing that hangs when a GPU's occupancy reporting is unreliable** — which this project's own earlier research already established as a known problem on this card generation (`gfx1030`/`gfx1032`), in a different kernel (flash attention). Stream-k's whole design assumes every block it launches can run at the same time, so blocks can wait on each other's signals; if the hardware can't actually run them all concurrently (which is precisely what unreliable occupancy detection would misjudge), a block can end up waiting forever for a signal from a block that was never scheduled — a genuine deadlock, not merely slow computation. That matches the symptom exactly: 99% GPU "busy" forever, no driver-level hang detected (the GPU is genuinely executing, just stuck spinning on a wait), same failure with flash attention on or off (this is a separate kernel from the one the earlier bug was found in).

  **Not confirmed.** Whether "stream-k" mode is actually selected for this exact model/quantization/shape lives in a large hand-tuned lookup table (`ggml_cuda_mmq_get_config`, keyed by quantization type, tile size, and compute capability) that isn't practical to resolve by reading alone — confirming this would mean adding debug print statements to the kernel launch code and rebuilding, a similar-sized step to the GPU-wave-debugging attempt above.

- **2026-08-29 — Instrumented the suspect kernel directly, and the "stream-k" hypothesis is wrong.** Added a debug print to `launch_mul_mat_q` (`mmq.cuh:1410-1413`) logging every call's `nrows_x` (the dimension that would equal context length if this were the attention computation) and whether stream-k mode was chosen. Rebuilt, and ran the working 17,000-token case with full logging: **51,724 calls, every single one with `stream_k=0` and `nrows_x` stuck at one of exactly three values (1,024 / 3,072 / 8,192) — the model's fixed weight dimensions (hidden size, intermediate size), never anything near the context length.** This kernel handles the model's regular weight matmuls, not the growing K-cache × query computation. Stream-k mode is never even selected here. The whole hypothesis targeted the wrong kernel file.

  **A second, useful side-finding fell out of this test:** re-running the same 17,000-token prompt with flash attention off (`-fa off`, plain `f16` KV cache this time, since quantized cache refused to load without flash attention) **also hung** — a size that worked fine with flash attention on. So the `-fa off` path has its own, *lower* breaking point than the `-fa on` path; the 17k/18k boundary documented above is specific to the `-fa on` configuration only. The two configurations are hitting this differently, which fits with attention math taking a genuinely different code path in each case.

  **Where this leaves the investigation:** the growing-context attention computation isn't going through the kernel just instrumented, in either configuration. The next candidate is `ggml/src/ggml-cuda/mmvq.cu` (`mul_mat_vec_q`) — a differently-specialized kernel for exactly this broadcasted-attention shape — but confirming that means repeating the same instrument-rebuild-test cycle in a new file, having just spent one full cycle disproving the previous lead.

- **2026-08-29 — Instrumented `mmvq.cu` the same way, rebuilt, and got a genuinely different answer than expected — one that reframes the whole investigation.** With flash attention **on** (the config the 17k/18k boundary was measured on), `mmvq.cu` never sees a context-sized value either — only the same fixed weight dimensions plus one new one, 128,256 (this model's vocabulary size, i.e. the output/LM-head layer). Makes sense in hindsight: with flash attention on, the K-cache computation is fused into the flash-attention kernel family directly and never becomes a standalone matmul call at all — neither `mmq.cu` nor `mmvq.cu` was ever going to show it.

  Re-ran the same 17,000-token prompt with flash attention **off** instead (the config confirmed to hang at this exact size), capturing debug output up to the timeout. **The very last line printed before the stall was the vocabulary/output-layer computation — the last operation of a complete forward pass.** That means every one of the 17,000 tokens had already been fully processed through every attention and feed-forward layer, and the hang happens *after* all the real compute had already been submitted to the GPU — not during it.

  **This lines up with the earlier stack trace and points at a different class of bug than a slow or deadlocked compute kernel.** The main thread was stuck in `ggml_backend_cuda_synchronize` — the call that waits for the GPU to report that a submitted graph has finished. If the graph's actual math was already done (consistent with the vocab layer being the last thing logged) and the wait never returns, the more likely explanation is a **lost completion signal somewhere in ROCm's own signaling/driver layer**, not a kernel computing forever. That would also explain why the card still reads "99% busy" throughout: something GPU-side may still be spinning on a synchronization primitive waiting for a signal that a driver-level bug never delivered, independent of whether the actual attention/FFN math finished.

  **This is a different, and harder, class of investigation than anything tried so far.** Confirming it needs HSA-level tracing (`rocprofv3 --hsa-trace` or similar) rather than more kernel source reading — a new direction, not a continuation of the kernel-instrumentation approach used in this entry and the one above it.

- **2026-08-29 — Major correction: this was never an infinite hang. It is a severe but finite slowdown, and every earlier "hang" was just a timeout set too short.** Continuing the investigation (user asked to keep going autonomously for up to 4 hours without further check-ins), the plan was to bisect the `-fa off` failure down to a minimal, cheap-to-reproduce case for tracing. That bisection found an oddly exact boundary — 6,300 tokens completes, 6,301 hangs — using the same ~15-25 second timeouts as the original discovery.

  **Retesting that "hanging" 6,301 case with a 90-second timeout instead, it completed normally** (537 tok/s). Retested 8,000 tokens (originally "hung" at 25s) with 180 seconds: completed, 445 tok/s. Retested 17,000 tokens with `-fa off` (originally "hung," never confirmed working at this exact flag combination) with 300 seconds: completed, 300.78 tok/s — slower than the `-fa on` case's 604 tok/s at the same size, but a real, finite number.

  **This means the earlier stack trace and the "lost GPU signal" theory were a reasonable read of incomplete data, not a wrong turn — the process really was inside `ggml_backend_cuda_synchronize`, genuinely waiting on the GPU, exactly as a slow-but-working kernel would look.** There was never a deadlock to find. The true shape of the problem is a **throughput curve that degrades faster than the token count grows** — mildly at first (matches the smooth 512→17,000 decline measured earlier with generous timeouts), then steeply enough that a 20-30 second timeout reads as "broken" long before the run actually finishes.

  Re-testing the original `-fa on` boundary (18,000 and 29,034 tokens, the config the pool would actually use) with much longer timeouts to find the real curve, and — the number that actually matters for the pool — the point where this stops being faster than ollama at all.

- **2026-08-29 — The patch from earlier really did fix it; the failure was in how it was tested, not the fix.** Retested 18,000 tokens (`-fa on`, the config the 17k/18k boundary was found on) with a 15-minute timeout instead of the ~100 seconds used originally: **completed in 62.3 seconds, three times in a row, to the decisecond (587.16 / 586.60 / 586.38 tok/s)** — completely stable, no hang, no variance. Retested 29,034 tokens — the exact case the occupancy patch was applied and re-verified against on the same day, which still appeared to fail at a 100-second timeout right after the patch went in: **completed in 127.7 seconds at 458.17 tok/s.** It had simply needed about 28 seconds more than the timeout given it. The patch (`fattn-common.cuh`, softening `GGML_ASSERT(max_blocks_per_sm > 0)` into a graceful fallback) was dismissed too early in the same session, on the strength of a **different** flag combination (`-fa off`, which doesn't even use the patched code path) timing out — never on a long enough retest of the actual configuration it was meant to fix.

  **The real shape of the problem was never a cliff or a deadlock. It's a throughput curve that bends down faster than the token count grows**, smoothly, the whole way — 1,032 tok/s at 512 tokens, declining to 587 at 18,000 and 458 at 29,034 — and every apparent "hang" in this entire investigation, from the very first discovery through the two `rocgdb` sessions, was this same smooth curve observed through a timeout that was too short for that particular size. The stack trace showing the process stuck in `ggml_backend_cuda_synchronize` was accurate the whole time — it really was waiting on the GPU — just for an ordinary (if slow) computation to finish, not for a lost signal or a deadlocked kernel. No driver bug, no lost signal, no stream-k deadlock: the investigation chased three increasingly specific hardware-level hypotheses to explain something that was, underneath, an ordinary performance curve paired with impatient timeouts.

- **2026-08-29 — But the same curve that killed the "deadlock" theory also kills the case for switching to raw llama.cpp at all.** Extended the comparison to the token counts the pool actually runs at, measuring both engines the same way, on the same card (hellhound), same model:

  | Tokens | ollama (production) | raw llama.cpp (patched) | Difference |
  |---|---|---|---|
  | 512 (prefill) | — | 1,032 tok/s | (~2x an earlier small-scale ollama-equivalent reading) |
  | 29,034 (prefill) | 462.2 tok/s | 458.2 tok/s | ~1% — noise |
  | 65,538 (prefill) | 265.2 tok/s | 265.9 tok/s | ~0.3% — noise |
  | 65,538 prefill + 64 decode, chained | 262.2 tok/s (derived) | 263.0 tok/s | ~0.3% — noise |

  (Ollama's own prompt handling capped both large test prompts at exactly 65,538 tokens regardless of how much longer the input text was — likely a fixed behavior tied to this model's 131,072-token context rather than anything to do with this investigation; not chased further since the comparison at that size was already conclusive. 65,538 is still short of the pool's real 96k–131k range, but the trend across four widely-spaced measurements is unambiguous and monotonic, not close to reversing.)

  **The 2x speedup is real, but only survives up to a few thousand tokens of context.** By roughly 29k tokens it has already fallen to about 1%, and by 65k it is gone entirely — both engines land within measurement noise of each other. Since the pool's actual analyses run at 96k–131k tokens, there is no speed to gain by switching, even with the occupancy bug fixed and rocWMMA flash attention enabled. Recorded as the **Bottom line** section at the top of this document.

- **2026-08-29 — Cleaned up the build.** Removed the debug `fprintf` instrumentation added to `mmq.cuh` and `mmvq.cu` while chasing the (since-explained) apparent hang, keeping only the real fix — the one-line `fattn-common.cuh` occupancy-fallback patch — and rebuilt. The working tree at `/home/kr/tools/llama.cpp` now carries exactly one meaningful change from upstream master, should anyone want to reuse or upstream it.
