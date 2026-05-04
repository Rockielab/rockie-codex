---
name: gpu-spend
description: When the user (or you) needs to know GPU spend across configured providers — "what's my burn rate?", "how much have I spent this week?", "is anything still running?", "am I close to budget?", "what's running idle?" — invoke this. Wraps `gpu.py cost --json` (cross-provider router) for accurate, reconciled numbers, then summarizes plus prints each provider's billing-page URL so the user can verify against the real billing UI in one click. ALWAYS prefer this over `runpod.py cost` or per-provider CLIs when reporting spend; the cross-provider router is the only surface that sees every dollar. **Custom-mode users:** if `ROCKIE_GPU_MODE=custom`, invoke `/gpu-custom` instead — `gpu.py cost` will exit with a bypass message in that mode.
---

# /gpu-spend — cross-provider GPU spend snapshot

The single source of truth for "what is the agent costing me right now?"
Reconciles live state against `gpu_pods.accrued_dollars`, sums into
`budget_usage[project:<p>:dollars]`, and prints both the LLM-readable
JSON and the human view with billing URLs.

## When to invoke

- User asks anything about cost, spend, rate, burn, budget, or pods running.
- Before any decision to spin up a new GPU (read state before adding load).
- After terminating a pod, to confirm the bleed has stopped.
- Periodically during long autonomous runs (the budget-reconcile.sh hook
  fires this on every UserPromptSubmit, but the agent should also check
  on entering the Codify phase).

Do NOT invoke if the user asked a non-cost question and you'd just be
showing off. The hook keeps the budget honest in the background.

## What the skill does

Runs:
```bash
python3 .codex/scripts/gpu.py cost --json
```

Output shape (LLM-ergonomic):
```json
{
  "project": "...",
  "providers": [
    { "provider": "runpod", "compute_per_hr": 0.0, "storage_per_hr": 0.011,
      "cumulative_usd": 2.20, "running_pods": 0, "idle_volume_gb": 80,
      "billing_url": "https://...", "total_per_hr": 0.011 },
    ...
  ],
  "grand_total_per_hr": 0.011,
  "grand_cumulative_usd": 2.20
}
```

Read the JSON. Synthesize a 2–3 line summary for the user that:
- Names the top spend driver (provider × compute or storage).
- Calls out idle storage if `running_pods=0` but `idle_volume_gb > 0`
  (user is paying for nothing — recommend `gpu.py terminate`).
- Surfaces the billing URL of any provider with non-zero cumulative
  spend so the user can cross-check.
- Compares `grand_cumulative_usd` to budget ceiling if known
  (`python3 .codex/scripts/budget.py status` shows the ceiling).

## Composition

- **`gpu.py reconcile`** runs implicitly inside `cost`, so numbers are
  always fresh (within seconds of the call). Don't reconcile separately.
- **`budget.py status`** shows the dollars ceiling vs. accrued. If
  cumulative is approaching the ceiling, surface a warning.
- **`/runpod`** and **`/vast`** skills wrap the per-provider native
  CLIs for deeper drill-downs (e.g. RunPod has a unique per-pod
  billing CLI). Use them only after `gpu-spend` to investigate a
  specific provider's contribution.

## Agent invocation template

```
Run `python3 .codex/scripts/gpu.py cost --json`. Read the JSON.
Summarize in 2-3 lines:
1. Top spend driver (which provider, compute or storage).
2. Idle storage warning if any.
3. Cumulative-vs-ceiling status (call `budget.py status` if needed).
End with the relevant billing URL(s). No more than 6 lines total.
```

## Why JSON, not the human table

The human `gpu.py cost` (no flag) is for users; LLMs should always read
`--json` because:
- Stable shape across versions; the table prettifies and may break parsers.
- Rates as floats, not strings — you can compare directly.
- `billing_url` and `cumulative_usd` are first-class fields, not
  buried in formatted output.
