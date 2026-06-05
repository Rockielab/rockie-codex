# Hardware selection + workload classification — 2026

**Last verified:** 2026-05-29

The agent reads this at step 3 (cost estimate) of the inference-engineer skill, after the workload shape has been classified from `prompts/intake-clarify.md`. Pick the SKU from the decision tree, then the serving stack from `serving-stacks.md`.

## GPU SKU comparison

This table is hardware specs only — relative cost ranking is the
right-most "Best at" column. Get live, all-in per-hour pricing from
`rockie-gpu market` at runtime; never hard-code a price here.

| GPU | VRAM | BW | FP8 / FP16 TFLOPS | Best at |
|---|---|---|---|---|
| **B200** | 192GB HBM3e | 8 TB/s | ~4500 / ~2250 | 70B+ low-latency, FP4/FP8 frontier (priciest tier) |
| **H200** | 141GB HBM3e | 4.8 TB/s | ~1979 / ~989 | 70B serving, long context |
| **H100 SXM** | 80GB HBM3 | 3.35 TB/s | ~1979 / ~989 | Production API workhorse |
| **H100 PCIe** | 80GB | 2 TB/s | ~1513 / ~756 | Same, lower BW |
| **A100 80GB** | 80GB HBM2e | 2 TB/s | – / 312 | Long-context memory-bound, NVLink training |
| **A100 40GB** | 40GB | 1.55 TB/s | – / 312 | Legacy 7–13B serving |
| **L40S** | 48GB GDDR6 | 864 GB/s | 733 / 362 | Cheapest $/Mtok at batch ≥8 (FP8) |
| **A40** | 48GB | 696 GB/s | – / 150 | 13B inference, cost-tier serving |
| **A6000** | 48GB | 768 GB/s | – / 155 | Dev / staging 7–34B |
| **A10G** | 24GB | 600 GB/s | – / 125 | 7–8B AWS-native serving |
| **L4** | 24GB | 300 GB/s | 242 / 121 | Embeddings, small-batch, vision |
| **RTX 4090** | 24GB | 1 TB/s | – / 165 | 7–13B single-user (DC EULA risk) |
| **T4** | 16GB | 320 GB/s | – / 65 | Edge, INT8 quantized small models |

Cheapest-tier SKUs (left→right by typical cost): T4 / L4 / RTX 4090 →
A40 / A6000 / A10G → L40S → A100 → H100 → H200 → B200. Confirm the
current all-in price for any SKU with `rockie-gpu market` before
quoting cost.

## Workload taxonomy (six canonical shapes)

The three intake questions (in `prompts/intake-clarify.md`) map to one of these:

1. **interactive** — single user / small team poking at it; low QPS; latency-tolerant if <2s; batch=1 dominant. Memory-BW bound.
2. **production-api** — customers hit an endpoint; p99 matters; continuous batching critical; TTFT <500ms, TPOT <50ms typical SLO.
3. **batch** — N docs/prompts to process by tomorrow; throughput-only; spot OK; restart-tolerant; cheapest $/token.
4. **embedding-throughput** — index N million docs; compute-light, BW-light; fits on L4/T4 swarms.
5. **vision-segmentation** — images in, masks/boxes out; smaller VRAM, higher SM-compute ratio; L40S/L4 sweet spot.
6. **scientific** — long sequences, regression heads, large memory; favors A100 / H200 / H100 80GB.

## Decision tree — (model class × workload shape) → SKU

| Model class | Interactive | Production API | Batch |
|---|---|---|---|
| **LLM 7B / 8B** | RTX 4090 / A10G spot | L40S spot + vLLM continuous batching | L4 / T4 spot swarm + vLLM offline mode |
| **LLM 13–34B** | L40S spot, FP8 quant | L40S or H100 PCIe | A40 / A6000 spot |
| **LLM 70B** | H100 80GB single, FP8 | H100×4 SXM + vLLM TP=4 or H200×2 | L40S×4 spot, FP8 quantized |
| **LLM 405B / frontier** | H200×8 or B200×4 | B200×8 NVL or H200×8 NVLink | H100×8 spot, INT4 quantized |
| **Vision 1B** (e.g. SAM-family) | L4 / T4 | L40S | L4 spot swarm |
| **Embedding 100M** (BGE-style) | T4 / L4 | L4 cluster, batch=512 | T4 spot, large batch |
| **Scientific 3B** (ESMFold-style) | A100 80GB (BW) | A100 / H200 | A100 spot |

Concrete examples (cost via `rockie-gpu market` at runtime):
- *Llama-3-8B + interactive → L40S spot, vLLM, FP8.*
- *Llama-3-70B + production API → H100×4 SXM, vLLM TP=4, expect 250-300 tok/s/stream, ~3500 tok/s aggregate.*
- *Mistral-7B + 50M-doc batch → L4 spot ×8, vLLM offline mode `LLM(...)` with `max_num_seqs=256`.*
- *facebook/sam3 + interactive vision → L40S spot, Triton + TensorRT, image-segmentation MCP schema.*

## Batch mode — when it pays

**Heuristic:** if the workload (a) tolerates ≥1h end-to-end latency, (b) is ≥10K requests, and (c) is restart-tolerant, batch wins on cost by ~50-70%.

**OSS equivalent of OpenAI/Anthropic batch APIs (50% discount):** **vLLM offline mode** is the canonical answer — instantiate `LLM(...)` directly (no HTTP/router/streaming layer) and call `llm.generate(prompts)` on a large list. Skips request queuing, scheduling, serialization overhead; saturates GPU at `max_num_seqs=256+`. Pair with **spot instances** for 60-70% additional savings — checkpoint progress to S3 every N prompts so preemption is cheap. SGLang has equivalent batch mode; Ray Data + vLLM scales horizontally across spot pools.

**Steer to batch when:** synthetic data generation, RL rollouts, bulk classification / summarization, embedding indexing, evals.

**Steer to real-time when:** any user-facing UI, agent loops with tool calls, streaming required, p99 SLO exists.

## Spend cap defaults

- **interactive:** $/hr × 1 hr (user is exploring; bound the burn)
- **production-api:** $/hr × 4 hrs (give them a real session)
- **batch:** $/hr × estimated time-to-completion (compute from total tokens / per-second throughput; cap at $25 unless user overrides)

User can always extend at step 8 via `/inference-engineer extend <load_id> <new-cap-cents>`.

## Sources

- Live, all-in per-hour pricing: `rockie-gpu market` at runtime (never a named-supplier snapshot).
- [Spheron L40S vs A100 (2026)](https://www.spheron.network/blog/l40s-vs-a100/)
- [GPUYard H100 vs L40S vs A100 Benchmarks 2026](https://www.gpuyard.com/blogs/llm-inference-benchmarks-h100-l40s-a100-roi/)
- [Databricks LLM Inference Performance Engineering](https://www.databricks.com/blog/llm-inference-performance-engineering-best-practices)
- [Aleksa Gordić — Inside vLLM](https://www.aleksagordic.com/blog/vllm)
- [arXiv 2511.17593 — vLLM vs TGI Comparative Analysis](https://arxiv.org/pdf/2511.17593)
