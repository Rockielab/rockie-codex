# GPU provider setup

rockie provisions GPUs through the cross-provider router at
`scripts/gpu.py`. To use it, set up at least one provider's credentials
in your project's `.env` file. **Two or more providers** unlocks
preemption survivability — when one provider's spot pool runs out or
preempts you, the router hops to the next.

`install.sh` runs an interactive credential wizard that walks through
this. If you skipped it (or are adding a provider later), follow the
relevant section below.

---

## Quick reference

| Provider | Spot tier | Auth shape | Min credit | SSH key | Set in `.env` |
|---|---|---|---|---|---|
| **RunPod** | ✓ (auction) | static API key | none | account-level | `RUNPOD_API_KEY` |
| **Vast.ai** | ✓ (bid auction) | static API key | $5 | account-level | `VAST_API_KEY` |
| **Prime Intellect** | ✓ (pass-through) | static API key | $10 | UUID per key | `PRIME_API_KEY`, `PRIME_SSH_KEY_ID` |
| **Verda (DataCrunch)** | ✓ (fixed-floor) | OAuth2 client | varies | UUID per key | `DATACRUNCH_CLIENT_ID`, `DATACRUNCH_CLIENT_SECRET`, `DATACRUNCH_SSH_KEY_ID` |

**Permissions reminder:** `.env` should be `chmod 600` (the wizard does
this; double-check if you create it manually). It's also gitignored —
verify with `git check-ignore -v .env` before committing.

---

## RunPod

1. Sign up at https://www.runpod.io/
2. Add a payment method or prepaid credit at https://www.runpod.io/console/user/billing
3. Generate an API key at https://www.runpod.io/console/user/settings → API Keys → Create API Key
4. Copy the key — it's shown once
5. Add to `.env`:
   ```
   RUNPOD_API_KEY=rpa_...
   ```
6. Verify:
   ```bash
   set -a; . .env; set +a
   python3 .codex/scripts/gpu.py auth --providers runpod
   ```
   → `[auth] runpod: ok`

**SSH:** RunPod injects your account-level SSH key into pods at create
time. You don't need to specify a key UUID per request. Manage keys at
the same console settings page.

---

## Vast.ai

1. Sign up at https://cloud.vast.ai/
2. **Add billing/credit** at https://cloud.vast.ai/billing/ ($5 minimum top-up). Required before instance creation — you'll get `insufficient_credit` errors otherwise. Search/list/price endpoints work on an empty account.
3. Generate an API key at https://cloud.vast.ai/account/ → API Keys → Generate New
4. Copy the key (shown once; ~64 hex chars)
5. **Upload an SSH key** at https://cloud.vast.ai/account/ → SSH Keys (or via API: `POST /api/v0/ssh/`). Vast injects this at create-time when `runtype=ssh`.
6. Add to `.env`:
   ```
   VAST_API_KEY=...
   ```
7. Verify:
   ```bash
   python3 .codex/scripts/gpu.py auth --providers vast
   ```

**Reliability filter:** the adapter defaults to `reliability_min=0.95` to
filter out flaky hosts (the #1 complaint in vast-python issues without
this). For long runs, bump to `0.98` via
`gpu.py create --providers vast --reliability-min 0.98 ...`.

**Storage on stopped instances:** Vast keeps charging storage rates while
an instance is paused. Use `terminate`, not `stop`, when finished.

---

## Prime Intellect

Prime is an aggregator routing to RunPod / Hyperbolic / FluidStack /
Lambda / io.net underneath. Best value: access to **Hyperbolic** (no
public direct-API alternative) and unified billing across upstreams.

1. Sign up at https://app.primeintellect.ai/
2. Add prepaid credits or a payment method at https://app.primeintellect.ai/dashboard/billing ($10 minimum top-up)
3. **Upload your SSH public key** at https://app.primeintellect.ai/dashboard/ssh-keys. Note the returned UUID — you need it for create.
4. Generate an API key at https://app.primeintellect.ai/dashboard/tokens → Generate New Key
5. Copy the key (shown once)
6. Add to `.env`:
   ```
   PRIME_API_KEY=...
   PRIME_SSH_KEY_ID=<the-uuid-from-step-3>
   ```
7. Verify:
   ```bash
   python3 .codex/scripts/gpu.py auth --providers prime
   ```

**Aggregator caveat:** when `gpu.py create --providers prime` returns
`BidRejected` or `NoCapacity`, that's the underlying upstream cloud
saying no, not Prime itself. The router will hop to the next provider
in your rank.

**No pause/resume.** Terminating a Prime pod is final — the root disk
is gone. For persistent state, attach a separate disk via the dashboard
or skip Prime for that workload.

**SDK note:** if you want the official `prime` Python CLI in addition to
our adapter, prefer `pip install prime-sandboxes` (~50KB) over
`pip install prime` (~200MB; pulls torch transitively).

---

## Verda Cloud (formerly DataCrunch)

Verda has the cleanest spot preemption signal of any provider in our
fleet (single field: `status: "discontinued"`) and EU-first geography
(Finland, Iceland data centers) — useful when latency or data-residency
matter.

1. Sign up at https://cloud.verda.com/
2. Add billing/credit at https://cloud.verda.com/billing
3. **Upload your SSH public key** at https://cloud.verda.com/account-settings/ssh-keys (or via API: `POST /v1/ssh-keys`). Note the returned UUID.
4. Generate an OAuth2 client at https://cloud.verda.com/account-settings/api → Create new client. You'll get a **client_id** and **client_secret** — copy both. Verda doesn't issue static API keys; the adapter uses the client to mint short-lived JWT bearer tokens.
5. Add to `.env`:
   ```
   DATACRUNCH_CLIENT_ID=...
   DATACRUNCH_CLIENT_SECRET=...
   DATACRUNCH_SSH_KEY_ID=<the-uuid-from-step-3>
   ```
6. Verify:
   ```bash
   python3 .codex/scripts/gpu.py auth --providers datacrunch
   ```
   → adapter mints a token via `POST /v1/oauth2/token`, then probes `GET /v1/balance`

**Volume retention on preemption:** the default `on_spot_discontinue`
policy is `keep_detached` — your OS volume survives preemption and can
be reattached. To save storage costs, override per-create with
`--extra on_spot_discontinue=delete_permanently` (data-destructive) or
`move_to_trash` (96-hour grace period).

**10-minute billing increments:** Verda bills in 10-min chunks, not
per-second. Short-lived test pods round up. Reconcile slightly
under-counts cost on quickly-preempted pods (~few cents at H100 rates).

**Region pinning:** the adapter searches for any location with stock by
default. Pin a specific region with `--extra location_code=FIN-01`
(Finland) or `ICE-01` (Iceland) etc.

---

## Verifying the full setup

After configuring 1+ providers:

```bash
# Auth probe — confirms each configured provider responds
python3 .codex/scripts/gpu.py auth

# Cross-provider price compare
python3 .codex/scripts/gpu.py price 'NVIDIA H100 80GB HBM3'   # RunPod's id
python3 .codex/scripts/gpu.py price 'H100_SXM'                # Vast's id

# Spend dashboard (humans)
python3 .codex/scripts/gpu.py dashboard

# Same data, JSON for LLMs
python3 .codex/scripts/gpu.py cost --json
```

For your first real provision, use the cheapest GPU available
(RTX 3090, A10, L4) for ~5 minutes to verify the round-trip:

```bash
python3 .codex/scripts/gpu.py create --gpu-type 'RTX 3090' --hours 0.1 --yes
# → router picks the cheapest available spot across configured providers,
#   prints SSH endpoint when running

# When done:
python3 .codex/scripts/gpu.py terminate --provider <name> <pod_id> --yes
```

---

## Troubleshooting

**`auth: AUTH FAILED` for a provider you just configured:**
- Verify the key is in `.env` and not in your shell environment with a
  typo: `grep PROVIDER_KEY .env`
- Source it: `set -a; . .env; set +a`
- Run a raw curl probe — see the per-provider section above for the
  exact command

**`OutOfStock` immediately on a popular GPU type:**
- Try a different GPU type with `gpu.py list-gpus`
- Check the per-provider billing page: low credit can present as
  out-of-stock errors on some providers (Vast does this)

**Reconcile hook fires every prompt but numbers look stale:**
- Check `.state/last_reconcile_ts` — should be updated within
  `RECONCILE_TTL_SECS` (default 120s)
- Run manually: `python3 .codex/scripts/gpu.py reconcile -v`

**Pod created but `gpu.py list-pods` doesn't show it:**
- The pod is recorded in `gpu_pods` table but may have been provisioned
  outside the harness. `list-pods` queries each provider's live API for
  ALL pods on the account, not just harness-managed ones — should still
  show up. If not, check `auth` first.
