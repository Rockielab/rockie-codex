---
name: prime
description: Prime Intellect-specific operations — provisioning, listing, terminating. Prime is an aggregator that surfaces RunPod/Hyperbolic/Lambda capacity through one API; spot tier is hit-or-miss depending on which upstream is selected. Per the CLI surveys, the `prime` CLI has no billing/cost verbs — for spend, use `/gpu-spend`. Reach for /prime when you specifically need Prime's interactive env / pod browser (`prime env list`, `prime pods ssh`) or are operating on Prime-only.
---

# /prime — Prime Intellect ops

Per the CLI surveys (`docs/_internal/cli-surveys/prime-intellect.md`),
the `prime` CLI is beta-stage with modern UX (Typer + Rich) but
**zero billing verbs**. There's no way to query spend through the CLI;
it's REST-only via `gpu.py`. The CLI's strength is interactive
exploration — listing environments, ssh into pods, killing pods.

## Prime peculiarities you must know

- **Prime is an aggregator, not a provider.** `cloudId` from
  availability search routes to RunPod / FluidStack / Hyperbolic /
  Lambda underneath. The "spot" tier is real but hit-or-miss; if no
  spot row is returned, our adapter raises `BidRejected` and
  `gpu.py create` hops to the next provider.
- **Pre-registered SSH key required.** Set `PRIME_SSH_KEY_ID` env var
  to the UUID of your uploaded key (https://app.primeintellect.ai/dashboard/ssh-keys).
- **No pause/resume.** `terminate` is the only exit; root-disk data
  is gone. For persistent state across runs, attach a separate disk.
- **`pip install prime` pulls 200MB of torch.** For minimal installs,
  use `pip install prime-sandboxes` (SDK only, ~50KB).

## When to invoke

- User wants interactive environment / pod browsing on Prime
  (the CLI's text-only UX is fine for human consumption).
- Operating on Prime-only.
- Investigating a Prime-specific routing question (which upstream
  cloud handled my pod?).

## Tools available

### Native CLI for interactive ops
```bash
pip install prime-sandboxes  # OR `pip install prime` if you don't mind 200MB
prime config set-api-key "$PRIME_API_KEY"

prime env list
prime pods list
prime pods ssh <pod_id>          # opens an interactive ssh session
prime pods kill <pod_id>          # terminates
```
Auth: `PRIME_API_KEY` env var (shared with our adapter).

### Cross-provider tool, scoped to Prime
```bash
python3 .codex/scripts/gpu.py cost --providers prime --json
python3 .codex/scripts/gpu.py list-pods --providers prime
python3 .codex/scripts/gpu.py price H100_80GB --providers prime --gpu-count 1
python3 .codex/scripts/gpu.py create --providers prime --gpu-type H100_80GB \
    --hours 1 --yes
```

## Decision tree

| User wants | Tool |
|---|---|
| "Open an interactive ssh into my Prime pod" | `prime pods ssh <id>` |
| "What environments / templates does Prime offer?" | `prime env list` |
| "What am I spending on Prime?" | `gpu.py cost --providers prime --json` (CLI has no billing verbs) |
| "What pods do I have on Prime?" | `gpu.py list-pods --providers prime` (or `prime pods list` for human view) |
| "Provision spot, fall back to on-demand" | `gpu.py create --providers prime ... --yes` (adapter falls through to on-demand if no spot row) |
| "Tear down and start fresh" | `gpu.py terminate --provider prime <id> --yes` |

## Cumulative spend caveat

Prime's CLI has no billing verbs at all. `gpu.py cost` reads cumulative
from `gpu_pods.accrued_dollars` (our reconcile), not from a Prime
billing API. The authoritative number is at
https://app.primeintellect.ai/dashboard/billing (also embedded in
`gpu.py cost --json` as `billing_url`).

## Agent invocation template

```
Question: <user's question>

If interactive (ssh, env browse):
  prime pods ssh <id>   |   prime env list

Otherwise (spend / status / provision):
  python3 .codex/scripts/gpu.py {cost,list-pods,create} --providers prime ...

Note: Prime is an aggregator. If a create returns BidRejected or
NoCapacity, that's the underlying upstream (RunPod/Hyperbolic/Lambda)
saying no — not Prime's fault. The router will hop to the next provider.
```
