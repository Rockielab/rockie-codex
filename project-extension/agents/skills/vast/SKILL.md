---
name: vast
description: Vast.ai-specific operations — discovery (`vastai search offers` is the best filter/sort UX of any provider's CLI), provisioning, and listing. Vast aggregates rentals from many individual hosts of varying quality, so the reliability filter is mandatory. For routine cross-provider questions, prefer /gpu-spend; reach for /vast when you specifically need fine-grained offer discovery (filter by region, dlperf-per-dollar, host reliability, NVLink presence) or are operating on Vast-only.
---

# /vast — Vast.ai ops + offer discovery

Per the CLI surveys (`docs/_internal/cli-surveys/vast-ai.md`),
`vastai search offers` has the cleanest discovery UX in the GPU-rental
space — filter/sort syntax, `--raw` JSON output, and recurring poll
support (`--every 60`). Wrap it for "find me cheap H100 in EU with
good reliability" queries that go beyond what our cross-provider
`gpu.py price` can express.

## Vast peculiarities you must know

- **No GPU-type catalog.** Each rentable machine is its own offer with
  an ephemeral `offer_id`. `gpu.py price` re-searches at submit time
  to pick a fresh one — never cache `offer_id`s.
- **`reliability >= 0.95` is mandatory.** Without it, you get
  preempted by host misbehavior, not by the spot market. Adapter
  defaults to 0.95; override with `--reliability-min 0.98` for
  longer runs.
- **No new bid on resume.** Vast resumes at the original bid. Don't
  pass `--bid` to resume; the adapter logs a warning and ignores it.
- **Paused != $0/hr.** While paused, you still pay storage
  (~$0.10/GB/month). Use `terminate`, not `stop`, when done.
- **`cancel_unavail: true` is mandatory.** Adapter sets it; if you
  bypass, failed-to-start instances bill queued hours.

## When to invoke

- User wants to discover offers with non-trivial constraints (geo,
  NVLink, multi-GPU NVLink topology, bandwidth, dlperf score).
- Operating on Vast-only (e.g. user has only Vast credit).
- Investigating a Vast-specific issue (preempted host, billing
  mismatch).

## Tools available

### Native CLI for discovery
```bash
pip install vastai

vastai set api-key "$VAST_API_KEY"

vastai search offers \
    'gpu_name=H100_SXM num_gpus=1 reliability>0.97 geolocation=US' \
    --order min_bid --raw

# Recurring watch
vastai search offers 'gpu_name=A10' --every 60
```
Auth: `VAST_API_KEY` env var (shared with our adapter — no conflict).

### Cross-provider tool, scoped to Vast
```bash
python3 .codex/scripts/gpu.py cost --providers vast --json
python3 .codex/scripts/gpu.py list-pods --providers vast
python3 .codex/scripts/gpu.py price 'RTX 3090' --providers vast
python3 .codex/scripts/gpu.py create --providers vast \
    --gpu-type 'RTX 3090' --hours 1 --yes
```

For Vast-specific knobs through `gpu.py`:
```bash
# Tighten reliability floor for a long run
gpu.py create --providers vast --gpu-type H100_SXM --reliability-min 0.98 ...

# Vast adapter reads spec.extras["reliability_min"] and
# spec.extras["verified_only"]
```

## Decision tree

| User wants | Tool |
|---|---|
| "Find me a cheap H100 with NVLink in EU" | `vastai search offers ...` (filter syntax) |
| "Watch for an A10 to come back in stock" | `vastai search offers --every 60` |
| "What am I spending on Vast?" | `gpu.py cost --providers vast --json` |
| "What pods do I have on Vast?" | `gpu.py list-pods --providers vast` |
| "Provision the cheapest reliable spot" | `gpu.py create --providers vast --gpu-type ... --yes` |
| "Why was I preempted?" | `gpu.py get-pod --provider vast <id>` then check actual_status / intended_status mismatch in metadata |

## Cumulative spend caveat

Vast has no public "current month spend" API endpoint. `gpu.py cost`
computes cumulative from `gpu_pods.accrued_dollars` (our reconcile),
NOT from Vast's billing record. If you need the authoritative number
for tax / reimbursement, send the user to https://cloud.vast.ai/billing/
(also embedded in `gpu.py cost --json` output as `billing_url`).

## Agent invocation template

```
Question: <user's question>

If it's a discovery question (filter offers, watch for stock):
  vastai search offers '<filter>' --order <field> --raw
  → parse JSON, surface top 3-5 offers with $/hr + reliability + geo

If it's a spend / status question:
  python3 .codex/scripts/gpu.py cost --providers vast --json

If it's a provision request:
  python3 .codex/scripts/gpu.py create --providers vast --gpu-type ... --yes

Always remind the user reliability_min defaults to 0.95 — recommend
0.98 for runs longer than 4 hours.
```
