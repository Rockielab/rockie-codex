# Kernel engineering — 2026 landscape

**Last verified:** 2026-05-29

Read this before invoking `/inference-kernel-engineer` (the post-load optimization sub-skill). The inference-engineer parent skill *references* this for context but doesn't invoke kernel work directly — kernels are a Day-2 optimization, not Day-1.

## Premise

For most loaded models on specific hardware, there's a 1.2–3× speedup available by profiling the hot op + rewriting it. LLMs are getting good at writing GPU kernels (Triton, CUDA). But the bar to get a *real* speedup that survives correctness + downstream eval validation is high — KernelBench shows raw frontier LLMs *regress* against `torch.compile` baselines without execution feedback loops.

## Tooling

- **Triton (OpenAI)** — De facto Python-based GPU kernel DSL for ML; powers `torch.compile`, vLLM, SGLang, FlashAttention 2/3, FlexAttention. Triton 3.x covers Ampere through Blackwell. LLM-reliable territory in 2026: fused elementwise/reduction/norm/quant chains, custom attention masks, MoE routing, RMSNorm+matmul fusions. Specialized agents (GEAK) hit 54-63% correctness on TritonBench; raw frontier LLMs <15%.
- **CUDA / PTX direct** — Worth it only when (a) target is Blackwell SM100 and you need TMA / TCGEN05 / Tensor Memory async pipelines that Triton's abstractions don't expose, or (b) you're writing a primitive that will be reused thousands of times. FlashAttention-4 itself retreated from Triton to CuTeDSL / CUTLASS for exactly this on Blackwell.
- **torch.compile / Inductor** — Obviates hand-written kernels for memory-bound elementwise/reduction chains, norm+quant fusions, and most pointwise epilogues. Does **not** obviate: large GEMMs (10-20% on table vs cuBLAS/CUTLASS), novel hardware patterns Inductor can't pattern-match, anything where TensorRT-LLM or a vendor library already wins. **Default: try `torch.compile(mode="max-autotune")` before writing anything custom.**
- **Off-the-shelf primitives to reach for first** (in this order):
  1. `torch.nn.functional.scaled_dot_product_attention` (SDPA)
  2. FlexAttention (PyTorch 2.5+) for mask variants — reports 1.2-3.2× over hand-written Triton on compute-bound attention
  3. FlashAttention-3 (Hopper) / FlashAttention-4 (Blackwell, via cuDNN or CuTeDSL)
  4. CUTLASS 3.x / CuTeDSL for GEMM epilogues
  5. cuBLASLt for matmul

## Profiling primitives — canonical 2026 loop

Two-stage, well-established: **PyTorch Profiler → Nsight Systems → Nsight Compute**.

1. Annotate forward with `torch.cuda.nvtx.range_push("prefill")` / `("decode")` — separate them; prefill is compute-bound, decode memory-bound, different hot ops.
2. PyTorch Profiler gives top-N ops by CUDA time + shapes + stack.
3. `nsys profile --trace=cuda,nvtx,osrt --pytorch=autograd-nvtx --cuda-graph-trace=node` for system gaps, launch overhead, idle bubbles.
4. Nsight Compute (NCU) on the single hot kernel for warp stall reasons, achieved occupancy, Tensor Core utilization, memory throughput.

The LLM-kernel literature converges on NCU as the profiler agents read from (CudaForge, GPU Kernel Scientist, KernelBand all parse NCU JSON).

## LLM-as-kernel-engineer literature (current SOTA)

- **KernelBench (Stanford, Ouyang et al. 2025)** — 250 PyTorch modules across Level 1 (single op) / Level 2 (fused op) / Level 3 (full arch). Single-shot frontier baselines weak (DeepSeek-R1 12/36/2%, o1 10/24/12%, Sonnet 10/7/2%). With 10-turn iterative refinement R1 jumps to 43/72/18%. **Critical finding: raw LLM-generated CUDA frequently regresses vs `torch.compile` baseline — execution feedback loop is mandatory.**
- **AI CUDA Engineer (Sakana, Feb 2025)** — Evolutionary + LLM, 17K-kernel archive. **Reward-hacked**: third parties found memory exploits in the eval sandbox letting it skip correctness checks. Cautionary tale; Sakana published a follow-up "Robust Agentic CUDA Kernel Benchmarking" hardening the harness.
- **Late 2025 / early 2026 SOTA**: KernelCoder/ConCuR (Oct 2025, LoRA on QwQ-32B, beats GPT-4 / Sonnet-4 / DeepSeek-V3.1 on KernelBench), CudaForge (Nov 2025, beats Kevin-32B and o3), Kevin-32B (multi-turn RL), CUDA-L1, GEAK (Triton-specialized, 4-agent: generator / reflector / evaluator / optimizer), TritonRL, KernelBand, PRAGMA, TritonForge.

**Playbook convergence:** profile (NCU) → pick hot op → generator writes candidate → evaluator runs correctness + perf → reflector reads error traces / NCU metrics → optimizer mutates → keep best of N → repeat.

## The sub-skill loop (what `/inference-kernel-engineer` does)

```
input: (loaded_model, hardware_id, calibration_inputs)
  1. baseline = torch.compile(model, mode="max-autotune"); record TTFT / throughput
  2. profile: NVTX-wrap prefill + decode; PyTorch Profiler → nsys → top-3 hot kernels
  3. for each hot kernel:
       a. SHORTCUT: try SDPA / FlexAttention / FA3-4 / CUTLASS first — if a primitive fits, use it, skip to 4
       b. NCU dump (warp stalls, occupancy, mem throughput) → context for generator
       c. agent loop (cap N=10 iters, GEAK-style 4 roles): generate Triton candidate → correctness vs eager reference (atol/rtol) → benchmark vs baseline → reflect on NCU delta
       d. keep candidate iff (correct AND ≥1.15x faster AND no numeric drift on eval suite)
  4. integrate winners behind a feature flag; re-run end-to-end benchmark + downstream eval (perplexity / task accuracy) to catch reward-hacking
  5. emit report: per-kernel speedup, integrated speedup, eval delta, NCU before/after
```

**Primitives the loop calls:** `torch.profiler`, `nsys`, `ncu --import`, `triton.testing.do_bench`, `torch.testing.assert_close`, `torch.compile`, FlexAttention / SDPA, FlashAttention-3/4, CUTLASS / CuTeDSL bindings.

## Hard rules

- **Human checkpoint at step 4.** Before integration, human signs off on: (a) eval-suite delta is within noise, (b) the benchmark sandbox wasn't gamed (compare against a held-out input the agent never saw), (c) speedup is reproducible on a cold cache. **This is the Sakana lesson:** the harness will reward-hack if you let it auto-merge.
- **Try off-the-shelf before writing.** SDPA → FlexAttention → FA3/4 → CUTLASS. Hand-write only when those leave 15%+ on the table.
- **Cost cap on the optimization run.** Cap at $5 default; the optimization itself can burn more GPU time than the model spent during dogfood. Surface the cap in the cost-confirm of the sub-skill.
- **Hardware-portability note.** AMD path is Triton → Composable Kernel (CK); Apple MPS and TPU don't have FA2/3 equivalents. The loop detects device and skips kernel-writing for non-NVIDIA/AMD targets, falls back to vendor SDPA.

## Sources

- [KernelBench (arXiv 2502.10517)](https://arxiv.org/html/2502.10517v1)
- [Stanford CRFM "Fast Kernels"](https://crfm.stanford.edu/2025/05/28/fast-kernels.html)
- [Simon Guo retrospective on automated GPU kernels](https://simonguo.tech/blog/2025-10-automated-gpu-kernels.html)
- [ConCuR / KernelCoder](https://arxiv.org/pdf/2510.07356)
- [Sakana AI CUDA Engineer paper](https://pub.sakana.ai/static/paper.pdf)
- [CudaForge (arXiv 2511.01884)](https://arxiv.org/pdf/2511.01884)
- [awesome-LLM-driven-kernel-generation](https://github.com/flagos-ai/awesome-LLM-driven-kernel-generation)
- [FlashAttention-3 (Tri Dao)](https://tridao.me/blog/2024/flash3/)
- [FlexAttention (PyTorch blog)](https://pytorch.org/blog/flexattention/)
- [vLLM profiling docs](https://docs.vllm.ai/en/stable/contributing/profiling/)
