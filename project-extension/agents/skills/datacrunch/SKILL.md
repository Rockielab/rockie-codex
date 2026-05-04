---
name: datacrunch
description: Verda Cloud (formerly DataCrunch) operations — provisioning, listing, terminating. Verda has a real spot tier with EU-first geography (FIN-01, ICE-01, etc.), differentiating from RunPod/Vast which are US-heavier. Authenticates via OAuth2 client-credentials (NOT static API key) — adapter handles token minting + refresh transparently. For routine cross-provider questions, prefer /gpu-spend; reach for /datacrunch when you specifically need EU geography, Verda's `discontinued` preemption signal detail, or Verda-specific knobs (on_spot_discontinue volume policy, location_code pinning).
---

# /datacrunch — Verda (DataCrunch) ops

Per market research (`docs/_internal/market-research/SYNTHESIS.md`),
Verda was selected as a top-3 direct adapter for its EU geography
(differentiates from US-heavy RunPod/Vast) and its real spot tier
with a clean preemption signal (`status: "discontinued"`).

## Verda peculiarities you must know

- **OAuth2, not static keys.** Set `DATACRUNCH_CLIENT_ID` +
  `DATACRUNCH_CLIENT_SECRET` (NOT `DATACRUNCH_API_KEY`). Adapter mints
  a JWT bearer token from `/v1/oauth2/token` and refreshes when
  needed. Failure to refresh → AuthError → router skips Verda for the
  rest of the call.
- **SSH key pre-registered.** Upload pubkey to the dashboard or via
  `POST /v1/ssh-keys`, set `DATACRUNCH_SSH_KEY_ID` to the returned UUID.
  Vast-style raw-pubkey-at-create is NOT supported.
- **`is_spot: true` flag, not separate endpoint.** Same `POST /v1/instances`
  endpoint for both spot and on-demand; the flag chooses tier.
- **Preemption = `status: "discontinued"`.** Cleaner than Vast's
  intended/actual mismatch. The volume's fate is controlled by
  `on_spot_discontinue`: `keep_detached` (default), `move_to_trash`
  (96-hour grace), or `delete_permanently`.
- **10-minute billing increments.** Short-lived test pods round up to
  the next 10 minutes. Reconcile undercounts by a few cents on
  preempted-quickly pods; not worth complicating the math.
- **Lifecycle is one endpoint.** `PUT /v1/instances` with
  `{"action": "shutdown"|"start"|"delete"|...}`. There's no DELETE
  method on `/v1/instances/{id}` — it's PUT-with-action.
- **Image is enum, not Docker tag.** Default
  `ubuntu-22.04-cuda-12.4-docker`. Custom images require a
  pre-customized OS volume id.

## When to invoke

- User wants EU geography (Verda has Finland, Iceland datacenters).
- Need to detect/handle preemption with the cleanest signal of any
  provider (single field check vs Vast's two-field comparison).
- Verda-only operation (other providers offline or missing capacity).

## Tools available

### Cross-provider tool, scoped to Verda
```bash
python3 .codex/scripts/gpu.py cost --providers datacrunch --json
python3 .codex/scripts/gpu.py list-pods --providers datacrunch
python3 .codex/scripts/gpu.py price 1H100.80S.22V --providers datacrunch
python3 .codex/scripts/gpu.py create --providers datacrunch \
    --gpu-type 1H100.80S.22V --hours 1 --yes
```

### Verda-specific knobs through extras
```bash
# Pin to Iceland datacenter
gpu.py create --providers datacrunch --gpu-type 1H100.80S.22V ...
# (location_code is set via SpotSpec.extras["location_code"]; the
# router reads region/extras and threads through)

# Custom volume retention policy on preemption
# Adapter reads spec.extras["on_spot_discontinue"]:
#   "keep_detached" (default — survives preemption)
#   "move_to_trash" (96hr grace, then deleted)
#   "delete_permanently" (immediate)
```

There is no native CLI for Verda. The web UI is at
https://cloud.verda.com/; for everything programmatic, use `gpu.py`.

## Decision tree

| User wants | Tool |
|---|---|
| "What am I spending on Verda?" | `gpu.py cost --providers datacrunch --json` |
| "What pods do I have on Verda?" | `gpu.py list-pods --providers datacrunch` |
| "Cheapest H100 in EU" | `gpu.py price 1H100.80S.22V --providers datacrunch` |
| "Provision a spot H100 in Finland" | `gpu.py create --providers datacrunch --gpu-type 1H100.80S.22V --yes` |
| "Tear down without losing data" | `gpu.py terminate --provider datacrunch <id> --yes` (default keeps volume) |
| "Detect preemption" | `gpu.py get-pod --provider datacrunch <id>` then check status; "PREEMPTED" status means `verda_status=discontinued` |

## Cumulative spend caveat

Verda's API exposes `price_per_hour` per running instance. `gpu.py cost`
computes cumulative from `gpu_pods.accrued_dollars` (our reconcile),
not from a Verda billing endpoint. Authoritative number is at
https://cloud.verda.com/billing (also embedded in `gpu.py cost --json`
as `billing_url`).

## Agent invocation template

```
Question: <user's question>

For programmatic ops (spend / status / provision / terminate):
  python3 .codex/scripts/gpu.py {cost,list-pods,price,create,terminate} \
      --providers datacrunch [...]

If working with EU-specific geo or preemption-policy questions, surface
Verda's `on_spot_discontinue` policy choice. If the user wants their
data preserved across preemption, recommend keep_detached (default).
```
