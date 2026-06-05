# Inference API gateways — 2026 landscape

**Last verified:** 2026-05-29

The agent reads this before deciding what to wrap a loaded inference endpoint with (step 7 of the inference-engineer skill — though the LiteLLM sidecar is currently the always-default).

## OpenAI-compatible gateways

- **LiteLLM** (BerriAI, **MIT**) — Python proxy that fronts 100+ providers behind a single OpenAI schema (`/chat/completions`, `/embeddings`, `/images`, vision via OpenAI multimodal payloads, audio). **Pass-through endpoints** for non-OpenAI surfaces (Anthropic, Vertex, custom HTTP) — but pass-throughs don't fire `async_pre_call_hook`, so spend/guardrail logic is partially lost on those routes. Postgres for state, Redis for shared rate-limits. OTel native. ~86% higher latency than Kong AI Gateway per Kong's own benchmark — not the fastest, but the broadest + best multi-tenant story.
- **vLLM's built-in OpenAI server** (Apache 2.0) — built into vLLM itself, exposes `/v1/*` directly from the inference engine — zero extra hop. The 2026 consensus pattern is **vLLM as the engine + LiteLLM (or similar) in front** for auth/routing/budgets.
- **FastChat** (Apache 2.0) — multi-model controller + web UI; for raw throughput teams pair it with vLLM, then front with LiteLLM.
- **Helicone** (Apache 2.0, Rust, ~8ms P50) — observability-first, lightweight gateway. **Acquired by Mintlify March 2026** — roadmap shifting to docs; treat as migration risk. Avoid as default.
- **Portkey** (MIT gateway core, **fully open-sourced March 2026**) — bundles routing + guardrails + prompt mgmt; 20–40ms overhead; PII/HIPAA/SOC2 controls. Best-in-class RBAC + virtual keys but heavier. Reasonable fallback if LiteLLM-shape is too thin.
- **Kong AI Gateway** (Apache 2.0 open core) — fastest in Kong's own benchmark, but the interesting AI plugins (Semantic Cache, Prompt Guard, RAG Injector) are **Enterprise-gated**. Worth it only if you already run Kong.
- **OpenLLM** (BentoML, Apache 2.0) — runtime + OpenAI-compatible server in one. Good for "I just want an endpoint from a HF model" — but OpenAI-compat is interface-only and it doesn't solve multi-tenant auth/billing.

## Non-LLM-shaped models

- **NVIDIA Triton** (BSD-3) — heavyweight standard for vision/segmentation/scientific. HTTP + gRPC, dynamic batching, multi-framework backends. No auth, no billing — needs a gateway in front.
- **TorchServe** — PyTorch-only, REST, simpler than Triton; declining momentum.
- **BentoML Service** (Apache 2.0) — Python decorator → REST/gRPC; handles pre/post-processing, batching, packages into a deployable "Bento." Most ergonomic for custom/scientific.
- **Hand-rolled FastAPI** — still common for one-off scientific models; reinvents batching/metrics. Avoid.

**No single 2026 OSS project unifies LLM + vision + custom under one gateway.** The pattern: BentoML or Triton handles per-model serving (any modality), and an OpenAI-style gateway (LiteLLM / Portkey) fronts them, exposing OpenAI-shaped routes for LLM/vision/embeddings and pass-through routes for the rest.

## Authentication, rate-limiting, billing for multi-tenant

**LiteLLM wins outright.** Four-level hierarchy (Org → Team → User → Key), **JWT → virtual-key mapping**, per-key/team/user **budgets enforced in real-time via `update_spend()`** on every `/chat/completions`, `/embeddings`, `/images` call. Redis-coordinated RPM/TPM across replicas. Audit logs, RBAC, IP ACLs, key rotation, secret managers. Portkey the only real competitor on RBAC depth but charges in latency and (post-PANW-acquisition) governance risk.

## Decision — what the inference-engineer skill defaults to

**Primary default: LiteLLM proxy as a sidecar in every inference pod, in front of vLLM (LLMs) + Triton/BentoML (vision/scientific).**

- One tenant-key surface (the Cloudflare-tunneled hostname + bearer)
- Real billing on OpenAI-shaped routes (chat/embeddings/images)
- Per-modality serving behind the proxy; the proxy routes by path
- The bootstrap script `runtime/start_litellm_proxy.sh` launches the sidecar alongside the model server
- Pass-through-doesn't-fire-pre-call-hook limitation is accepted; per-tenant accounting at the BentoML/Triton layer for non-LLM modalities is the workaround

**Fallback: Portkey OSS** (now Apache 2.0) if we ever need bundled guardrails/PII/RBAC and can swallow 20-40ms.

**Avoid as defaults:** Helicone (Mintlify acquisition risk), Kong AI Gateway (Enterprise gating of AI plugins).

## Rules of thumb for the inference-engineer skill

- **Always wrap with LiteLLM.** Even if the user "just wants the endpoint" — the LiteLLM sidecar is what gives them a tenant-keyed, OpenAI-shaped, rate-limited, audit-logged surface for $0 extra cost (it's a tiny Python proxy).
- **For non-LLM modalities, register the model server's HTTP route as a LiteLLM `pass_through_endpoint`** authenticated by the same virtual key. The user gets one bearer token for everything.
- **Don't expose vLLM's `/v1/*` directly to the public.** Always go through LiteLLM; it owns the auth + budget hooks.

## Sources

- [LiteLLM proxy virtual keys + budgets](https://docs.litellm.ai/docs/proxy/virtual_keys)
- [LiteLLM pass-through endpoints](https://docs.litellm.ai/docs/proxy/pass_through)
- [Best 7 Open Source AI Gateways 2026 — Future AGI](https://futureagi.com/blog/best-open-source-ai-gateways/)
- [Top 5 LLM Gateways in 2026 — DEV](https://dev.to/varshithvhegde/top-5-llm-gateways-in-2026-a-deep-dive-comparison-for-production-teams-34d2)
- [Kong AI Gateway benchmark vs Portkey/LiteLLM](https://konghq.com/blog/engineering/ai-gateway-benchmark-kong-ai-gateway-portkey-litellm)
- [Helicone vs Portkey 2026 — Respan](https://www.respan.ai/market-map/compare/helicone-vs-portkey)
- [Deploying gpt-oss with vLLM + BentoML](https://www.bentoml.com/blog/deploying-a-large-language-model-with-bentoml-and-vllm)
