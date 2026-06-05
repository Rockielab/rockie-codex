# Cost-confirm template — HARD gate, no improvisation

The agent MUST use this template verbatim at step 4 of the inference-engineer skill. Substitute the bracketed values from steps 1-3; do not change the structure, the wording, or the question.

## The template

```
Before I spin up a GPU, here's what I'm about to do — please confirm.

**Model:** [model URL or HF repo, e.g. mistralai/Mistral-7B-Instruct-v0.3]
**Modality:** [chat / text-embedding / image-segmentation / etc]
**Workload shape:** [interactive / production-api / batch / etc]
**GPU:** [SKU, e.g. L40S 48GB spot]
**Compute:** Rockie GPU (best available, Rockie-priced via `rockie-gpu`)
**Serving stack:** [vLLM / Triton / TEI / BentoML]
**Gateway:** LiteLLM sidecar (OpenAI-compatible /v1/chat/completions, /v1/embeddings, etc)
**Spend cap:** $[cap_dollars] (hard kill; pod tears down automatically when hit)
**Estimated bootstrap time:** [~N minutes for clone + install + load]
**$/hour:** $[rate] [spot / on-demand]
**Estimated cost if I run it for the full 1-hour cap:** $[cap_dollars]

Reasoning for this SKU:
[ONE sentence from the decision tree in research/hardware-workload.md — e.g. "L40S spot fits 7B FP8 in 48GB with headroom, costs ~3x less than H100 for single-user interactive."]

**Reply with one of:**
- `yes` — I'll provision now
- `smaller` — I'll pick a cheaper GPU (tell me what tier — `bigger` for the inverse)
- `different model` — paste a different URL
- `no` — abort, no provisioning
- `wait` — I'll explain what's confusing first, then re-ask
```

## Rules for the agent

- **Do not paraphrase.** Do not say "this will cost about $X, sound good?" or "ready?" or "shall I go?" — those are the historical failure modes where agents pretend the user said yes.
- **Wait for an unambiguous reply.** If the user says "hmm", "maybe", "I think so" — those are NOT `yes`. Re-ask: *"Sorry, need an unambiguous yes / smaller / different model / no / wait — which is it?"*
- **If they say `smaller` or `bigger`:** loop back to step 3 (re-pick SKU) and re-issue this template.
- **If they say `different model`:** loop back to step 2 (re-classify source).
- **If they say `no`:** stop. Say "Aborted. No GPU provisioned." Do not retry without a fresh user request.
- **If they say `wait`:** answer their question, then re-issue this template unchanged.
- **If they say anything else** (e.g. an off-topic message): answer the off-topic question, then re-issue this template unchanged. Do not assume their off-topic question implies consent.

## Why this exists

Step 4 is the load-bearing safety gate. Before it: zero GPU spend. After it: real money. Every other failure mode in the skill is recoverable (a bad SKU, a flaky pod, a wrong serving stack); a `yes` that wasn't really a `yes` is not — the pod is spun up and the spend has started.

Historical incidents this prevents: agents inferring consent from "ok" / "sure, sounds good" / silence / a topic change. The fix is mechanical: this template, verbatim, every time.
