# Inference serving stacks — 2026 landscape

**Last verified:** 2026-05-29 (refresh via `/inference-research-refresh` when stale)

The agent reads this before picking a serving stack at step 3 of the inference-engineer skill.

## Per-stack capsules

| Stack | Best at | Modality | Batching | License | Docker | OpenAI API |
|---|---|---|---|---|---|---|
| **vLLM** (v0.19+) | General-purpose LLM serving; widest model coverage | LLM + VLM (Llava, Qwen-VL, Phi-3.5-vision); native embeddings since 0.19 | Continuous (PagedAttention) | Apache 2.0 | First-class (`vllm/vllm-openai`) | Native |
| **TGI** (v3.x) | HF-ecosystem LLM serving; safe-tensors | LLM + multimodal (Idefics, Llava) | Continuous | Apache 2.0 (re-licensed from HFOIL in 2.0+) | First-class | Native (Messages API) |
| **NVIDIA Triton** (25.12) | Multi-framework, multi-model heterogeneous; not LLM-first | Anything (TF/PT/ONNX/TRT/Python backends) | Dynamic batcher (config'd per-model) | BSD-3 | First-class (NGC) | Via TensorRT-LLM/vLLM backend or shim |
| **BentoML / OpenLLM** | Packaging + multi-model microservices; cloud deploy | Any (BentoML), LLM-focused (OpenLLM) | Adaptive (BentoML), continuous via vLLM/TRT-LLM (OpenLLM) | Apache 2.0 | First-class (`bentoctl`) | Native (OpenLLM) |
| **Ray Serve** | LLM + arbitrary Python pipelines on existing Ray clusters | Any | Continuous (vLLM engine) + dynamic | Apache 2.0 | Via Ray image | Via `ray.serve.llm` (vLLM under the hood) |
| **LMDeploy** | Low-latency quantized LLM (INT4/W4A16, TurboMind) | LLM + VLM (InternVL) | Continuous | Apache 2.0 | First-class | Native |
| **SGLang** (v0.5.10+) | Agentic / multi-turn / structured-output; highest prefix-cache reuse | LLM + VLM + native embeddings; diffusion (FastVideo) added late 2025 | Continuous + RadixAttention prefix cache | Apache 2.0 | First-class | Native |
| **MLC-LLM** | Edge / mobile / WebGPU / Apple Silicon; cross-arch via TVM Unity | LLM (some VLM) | Per-request (latency-first) | Apache 2.0 | Limited (mostly device-side) | Native (Python REST) |
| **HF TEI** | Encoder embeddings (BGE, Jina, E5, GTE) | Embedding only | Dynamic | Apache 2.0 | First-class | OpenAI `/v1/embeddings` |
| **NVIDIA Dynamo** (v1.0 GA Mar 2026) | Multi-GPU LLM/MoE fleets; KV-aware routing; disaggregated prefill/decode | Above vLLM/SGLang/TRT-LLM | Inherits engine | Apache 2.0 | First-class | Inherits engine |

## Decision matrix — pick the default

| Workload | Default stack | Why |
|---|---|---|
| Single-user interactive LLM chat | **LMDeploy** (or **MLC-LLM** on Apple Silicon) | Lowest TTFT on quantized weights; SGLang close second |
| High-throughput multi-user LLM API | **vLLM** (single node) → **Dynamo + vLLM/SGLang** (multi-node) | vLLM is gold standard for general production; Dynamo 1.0 adds disaggregated prefill/decode + KV-aware routing |
| Batch / overnight LLM jobs | **vLLM offline mode** (`LLM(...).generate()`) | Throughput-optimal, no HTTP overhead; SGLang close on agentic batches |
| Vision / SAM-family segmentation | **Triton** (TensorRT/ONNX backend) | LLM servers don't support segmentation heads; Triton's dynamic batcher + TRT plugin is the default |
| Embeddings — encoder (BGE, Jina, E5) | **HF TEI** | Canonical encoder server; lightweight, fast |
| Embeddings — LLM-based (e.g. Qwen3-Embedding) | **vLLM** or **SGLang** (native `/embeddings` since late 2025) | Reuse the LLM stack; NVIDIA BEI is 3.3× faster on B200 if you have one |
| Multimodal (Llava, Qwen-VL) | **vLLM** or **SGLang** | Both first-class VLM; SGLang prefix-caches the vision encoder across turns |
| Custom scientific / regression (ESMFold, AlphaFold) | **Triton** with Python or PyTorch backend; **BentoML** if you want single-Python deploy story | Non-transformer-text falls outside LLM-server scope |

## What changed in 2026 (load-bearing for default picks)

- **NVIDIA Dynamo 1.0 GA (March 16 2026)** — explicitly the successor to Triton Inference Server *for generative workloads*. Orchestration OS above vLLM / SGLang / TensorRT-LLM, with disaggregated E/P/D, KV-aware routing, S3/Azure KV-tier offload, K8s Inference Gateway plugin. Triton remains the right call for **non-generative** multi-framework serving. Dynamo only enters the picture when crossing 1 GPU for a single model.
- **TensorRT-LLM C++ runtimes deprecated** (3-month migration window); Volta support removed; PyTorch bumped to 2.9.1 in 25.12 images.
- **vLLM, SGLang, LMDeploy converge on throughput**: at 4-GPU TP, SGLang 16,215 tok/s ≈ LMDeploy 16,132 tok/s, both ~29% over vLLM 12,553 tok/s; bottleneck is orchestration overhead, not kernels.
- **Embeddings split**: vLLM 0.19 and SGLang 0.5.10 added native `/embeddings`; NVIDIA's **BEI** ships 3.3× over vLLM on B200.
- **TGI re-licensed to Apache 2.0** (TGI 2.0+ dropped HFOIL restrictions).
- **MLC-LLM** still the only serious answer for WebGPU / on-device; cloud-side shrinking as vLLM-metal and vllm-mlx catch up on Apple Silicon.

## Rules of thumb for the inference-engineer skill

- **Default to vLLM for any LLM.** It's the safe pick; swap to LMDeploy if the user explicitly says "lowest latency, quantized OK" or to SGLang if "agentic multi-turn" or "structured output JSON."
- **Default to Triton for any non-LLM model.** Vision / segmentation / scientific / regression all live here.
- **Default to TEI for any encoder embedding model.** Don't reach for vLLM/SGLang `/embeddings` unless the user's model is itself an LLM.
- **Don't reach for Dynamo today.** Single-node single-model serving is 99% of the demand; Dynamo is for when N>1 GPU per model.
- **Don't reach for BentoML unless the user has a custom Python preprocessor / postprocessor that doesn't fit any other stack.**

## Sources

- [NVIDIA Dynamo 1.0 announcement](https://nvidianews.nvidia.com/news/dynamo-1-0)
- [Dynamo GitHub](https://github.com/ai-dynamo/dynamo)
- [TensorRT-LLM release notes](https://nvidia.github.io/TensorRT-LLM/release-notes.html)
- [vLLM docs](https://docs.vllm.ai/)
- [SGLang GitHub](https://github.com/sgl-project/sglang)
- [LMDeploy GitHub](https://github.com/InternLM/lmdeploy)
- [HF TEI](https://github.com/huggingface/text-embeddings-inference)
