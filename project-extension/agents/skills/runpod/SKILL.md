---
name: runpod
description: RunPod-specific operations — provisioning, listing, terminating, and crucially per-pod billing breakdowns. RunPod is the only provider with a native billing CLI (`runpodctl billing pods --output json`) that gives per-resource spend; use it when you need finer detail than `gpu.py cost`. For routine cross-provider questions, prefer /gpu-spend; reach for /runpod when you specifically need RunPod's per-pod / serverless / network-volume billing breakdown, or when working with RunPod-specific knobs (SECURE-cloud, gpuType ids).
---

# /runpod — RunPod ops + per-pod billing detail

RunPod is one of four providers rockie supports through `gpu.py`,
but it's the **only one with a billing CLI worth wrapping**. Per the
CLI surveys (`docs/_internal/cli-surveys/runpod.md`):
`runpodctl billing pods --output json` gives per-pod spend, network
volume costs, and serverless usage in JSON — strictly more detail
than our REST `current_spend()` aggregates.

## When to invoke

- User asks "what is each RunPod pod costing me?" or wants per-pod
  spend resolution that `/gpu-spend` doesn't have.
- User specifically references RunPod (single-provider operation).
- You need the RunPod-only `--secure` (SECURE-cloud datacenter)
  filter — it's not exposed across providers.
- Resume a stopped RunPod pod (RunPod has both `podResume` (on-demand)
  and `podBidResume` (spot) — semantically rich).

For everything else (cross-provider create / spend / status), prefer
`/gpu-spend` or `gpu.py` directly.

## Tools available

### Per-pod billing (RunPod-unique)
```bash
runpodctl billing pods --output json
runpodctl billing serverless --output json
runpodctl billing networkvolume --output json
```
Prerequisites: `brew install runpod/runpodctl/runpodctl` (or curl install
per https://github.com/runpod/runpodctl); auth via `runpodctl config
--apiKey "$RUNPOD_API_KEY"` — shares the env var our adapter uses.

### Cross-provider tool, scoped to RunPod
```bash
python3 .codex/scripts/gpu.py cost --providers runpod --json
python3 .codex/scripts/gpu.py list-pods --providers runpod
python3 .codex/scripts/gpu.py create --providers runpod --gpu-type "NVIDIA H100 80GB HBM3" --hours 1
```

### RunPod-specific verbs (legacy single-provider CLI)
```bash
python3 .codex/scripts/runpod.py reconcile -v
python3 .codex/scripts/runpod.py create --gpu-type-id "NVIDIA H100 80GB HBM3" \
    --secure --bid 1.5 --hours 1 --yes
python3 .codex/scripts/runpod.py resume <pod_id> --on-demand --yes
```
The `runpod.py` CLI carries the `--secure` flag and explicit
`--on-demand` resume path that `gpu.py` doesn't surface.

## Decision tree

| User wants | Tool |
|---|---|
| "What does each pod cost?" (per-pod detail) | `runpodctl billing pods --output json` |
| "What am I spending on RunPod?" (aggregate) | `gpu.py cost --providers runpod --json` |
| "What pods do I have?" | `gpu.py list-pods --providers runpod` |
| "Provision an H100 spot, SECURE-cloud only" | `runpod.py create --secure --gpu-type-id ... --yes` |
| "Resume on-demand to avoid preemption" | `runpod.py resume <id> --on-demand --yes` |
| "Reconcile the budget against RunPod" | `gpu.py reconcile --providers runpod` |

## Why both `gpu.py` and `runpod.py` exist

`gpu.py` is the generic router — same verbs, four providers. It's
strict about the Protocol shape so cross-provider features (cooldown,
ranked fallback, JSON output) work uniformly. `runpod.py` predates it
and exposes RunPod-specific knobs (`--secure`, explicit on-demand
resume) that didn't generalize to the Protocol. Both write to the
same `gpu_pods` table and the same `budget_usage[project:<p>:dollars]`
counter, so they're consistent.

If you don't need a RunPod-specific knob, prefer `gpu.py`.

## Agent invocation template

```
Question: <user's question>

If it's a per-pod billing detail question:
  runpodctl billing pods --output json
  → parse, summarize per-pod spend + idle warnings

If it's "what's running" or "what am I spending":
  python3 .codex/scripts/gpu.py cost --providers runpod --json

If it's a provision request with --secure or on-demand:
  python3 .codex/scripts/runpod.py create --secure ... (or resume --on-demand)

Keep summaries to 3-4 lines. End with billing URL when reporting spend.
```
