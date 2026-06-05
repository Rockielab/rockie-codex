# Inference quality + perf + cost evaluation — 2026

**Last verified:** 2026-05-29

Read this before invoking `/inference-eval` (the post-deploy quality / latency / cost probe sub-skill). The parent inference-engineer skill offers `/inference-eval` as an opt-in at step 8.

## General-purpose LLM eval harnesses

- **[lm-evaluation-harness](https://github.com/EleutherAI/lm-evaluation-harness)** (EleutherAI) — the de facto standard. Covers MMLU, ARC, HellaSwag, GSM8K, TruthfulQA, BBH, ~200 tasks. Point at any OpenAI-compatible endpoint with `pip install lm_eval[api]`, then:

  ```
  lm_eval --model local-completions \
          --model_args base_url=<vllm-url>,model=<name> \
          --tasks mmlu_pro,gsm8k --limit 200
  ```

  Use `local-chat-completions` if `/chat/completions` only. `local-completions` unlocks all 4 task types (generate_until, loglikelihood, loglikelihood_rolling, multiple_choice) if logprobs are exposed; chat-completions is generate_until only. **Standard pairing for vLLM-hosted models.**

- **[OpenCompass](https://github.com/open-compass/opencompass)** — Shanghai AI Lab. Stronger than lm-eval for distributed multi-GPU eval on clusters, Chinese benchmarks (C-Eval, CMMLU), longer-context tasks. Use it when sweeping many models across a fleet.

- **[HELM](https://crfm.stanford.edu/helm/)** (Stanford CRFM) — still maintained but research-grade, slow, opinionated. Worth it only if you need robustness / fairness / calibration alongside accuracy. For production gating, lm-eval is the right default.

## Modality-specific

- **Embeddings:** [MTEB v2](https://huggingface.co/spaces/mteb/leaderboard) (2026) — not directly comparable to v1; Qwen3-Embedding-8B (70.58) and Jina v5-text-small (71.7) are reference points. vLLM 0.19+ / SGLang 0.5.10 ship native embedding endpoints.
- **Vision / segmentation:** COCO (instance), ADE20K (semantic — the SAM-family standard), PASCAL VOC (classic). For SAM-class models, **[Semantic Segment Anything (SSA)](https://github.com/fudan-zvg/Semantic-Segment-Anything)** on ADE20K is the canonical eval; UnSAM reports 40.3% MaxIoU / 59.5% OracleIoU.
- **Multimodal:** [MMMU](https://mmmu-benchmark.github.io/) is saturated (>80% on frontier). Use [**MMMU-Pro**](https://arxiv.org/abs/2409.02813) (vision-only-input variant drops scores 16-27 points) and **MathVista** for math/chart reasoning.
- **Scientific (protein structure):** **[PSBench](https://github.com/BioinfoMachineLearning/PSBench)** (2026, CASP17-integrated) is the open benchmark; AF2/ESMFold/OmegaFold comparison on 1,337 PDB chains using TM-score, GDT-TS, RMSD. **[ProteinWorkshop](https://github.com/a-r-j/ProteinWorkshop)** for representation learning.

## Latency + throughput

- **[vllm/benchmarks/benchmark_serving.py](https://github.com/vllm-project/vllm/blob/main/benchmarks/benchmark_serving.py)** — measures TTFT, TPOT/ITL, throughput, p50/p99. Supports vllm/tgi/lmdeploy/deepspeed backends for cross-framework comparison.
- **[GenAI-Perf](https://docs.nvidia.com/nim/benchmarking/llm/latest/metrics.html)** (NVIDIA) — wraps perf_analyzer, emits TTFT, Time-To-Second-Token, ITL, output-tokens/sec/user. Best for concurrency sweeps.
- **k6 / wrk** — fine for raw HTTP but blind to streaming/tokens; need `xk6-sse` extension. Under-measure LLMs because they collapse streamed responses to total-byte time.

**Recommended one-liner** for a fresh endpoint:

```
genai-perf profile -m <model> --endpoint-type chat --streaming \
  --synthetic-input-tokens-mean 200 --output-tokens-mean 100 \
  --concurrency 1,4,16,64 --request-count 400 --warmup-request-count 10
```

Divide GPU $/hr by output-tokens/sec to get $/1k tokens.

## The eval sub-skill loop (what `/inference-eval` does)

Single sub-skill triggered by the user opting in at step 8 of the parent skill. Dispatches three parallel one-shot calls keyed on modality:

| Modality | Quality | Perf | Cost |
|---|---|---|---|
| LLM (chat / generation) | `lm_eval --tasks mmlu_pro,gsm8k --limit 200 --model local-completions` (~5min subset) | `genai-perf profile … --concurrency 1,16,64` | GPU $/hr ÷ output tok/s |
| Embedding | `mteb run -m <endpoint> --tasks STS22,BankingClassification` | same, embed endpoint | $/1M embeddings |
| Vision / SAM | mIoU on ADE20K-1% subset | wrk + p99 image latency | $/1k images |
| Multimodal | MMMU-Pro 300-question subset via lm-eval | GenAI-Perf with image input | $/1k requests |
| Scientific (protein) | PSBench mini (50 targets, TM-score) | wall-clock TM-score/sec | $/structure |

Persist three numbers to a JSONL alongside the deploy SHA:
- `quality_score` (the modality-specific number)
- `p99_latency_ms`
- `dollar_per_1k_units` (tokens / embeddings / images / requests / structures)

## Hard rules

- **Subset everything to ~200 examples.** Full benchmarks are for monthly snapshots, not per-deploy gates. 200 examples gives reasonable signal in ~5 min.
- **Gate promotion on regression > 2% quality OR > 20% p99.** Anything worse than that needs a human look.
- **Always run the cost number even if the user didn't ask.** Knowing $/1k units is the difference between "this works" and "this is viable."
- **Don't run on the same GPU as serving.** Eval workload competes with the model's request capacity. Either spin a tiny separate pod or do eval *before* the load is exposed to other tenants' MCP tools.

## Sources

- [lm-evaluation-harness API guide](https://github.com/EleutherAI/lm-evaluation-harness/blob/main/docs/API_guide.md)
- [OpenCompass](https://github.com/open-compass/opencompass)
- [HELM](https://crfm.stanford.edu/helm/)
- [MTEB leaderboard](https://huggingface.co/spaces/mteb/leaderboard)
- [MMMU-Pro paper](https://arxiv.org/abs/2409.02813)
- [MMMU](https://mmmu-benchmark.github.io/)
- [vLLM benchmark_serving guide](https://www.gpu-mart.com/blog/how-to-benchmark-vllm-online-serving)
- [GenAI-Perf + vLLM (Denvr)](https://www.denvr.com/post/llm-inference-benchmarking-with-nvidia-genai-perf)
- [LLM SLO engineering 2026 (Spheron)](https://www.spheron.network/blog/llm-inference-slo-ttft-itl-latency-budget-guide-2026/)
- [BentoML LLM Inference Handbook](https://bentoml.com/llm/inference-optimization/llm-performance-benchmarks)
