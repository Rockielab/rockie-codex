# Budget mechanisms

rockie tracks four budget dimensions. All auto-increment (no manual
accounting needed). Caps are opt-in — leave a dimension absent from
`.codex/budget.toml` to disable enforcement for that dimension.

| Dimension | Auto-tracked by | Semantics |
|---|---|---|
| `tool_calls` | `hooks/budget-gate.sh` on every `PreToolUse(Bash)` | Counts bash invocations. Blocks at ceiling. |
| `wallclock_s` | `hooks/learn-capture.sh` (Stop) via `budget.py tick-wallclock` | Seconds since `SessionStart`. Updates monotonically per Stop. |
| `tokens` | `hooks/learn-capture.sh` (Stop) via `budget.py tick-tokens --transcript` | **Proxy**: transcript file bytes ÷ 4. Rough but universal. |
| `dollars` | `scripts/runpod.py create` on successful provision | Upper-bound estimate: `bid × gpu_count × hours`. Over-counts if pod stops early. |

## When to set which ceilings

### Codex Max subscription, local harness

Leave `tokens`, `tool_calls`, and `wallclock_s` absent — Codex Max has
no per-call charge, so none of these correspond to real spend. Only
cap `dollars`:

```toml
[project]
dollars = 50.00    # overnight H100 budget
```

### Cloud Codex API (pay-per-token)

Tokens now map to dollars. Set both:

```toml
[session]
tokens      = 5000000     # ~$20-40 worth of Sonnet-4.6 input+output
wallclock_s = 28800       # 8h session cap

[project]
dollars     = 50.00       # separate, tracks RunPod spend only
```

### Future rockie-as-a-platform (cloud-hosted autonomous runs)

All four ceilings matter. tool_calls additionally caps runaway
hook-loop bugs. Add reasonable defaults to the platform-level config
template.

## Adding a new dimension

If you plug in a new provider (Vast.ai, Lambda, Anthropic API), and
its spend doesn't fit into `dollars` (e.g. you want separate tracking
per provider), add a new metric to `VALID_METRICS` in `budget.py`:

1. `budget.py` — add `"vast_dollars"` (or whatever) to `VALID_METRICS`.
2. Your provider wrapper adds to it: `budget.py add vast_dollars 4.5`.
3. `budget.toml` gets `[project] vast_dollars = 30.00`.
4. `budget-gate` enforces automatically — no hook changes needed.

Check via `budget.py status`; reset per-scope via `budget.py reset`.

## What's NOT tracked

- **Real token counts from the LLM.** rockie doesn't have access to
  Codex's token counter, so the token dimension uses a bytes-per-token
  proxy. If your use case needs exact token accounting, plug in a
  tokenizer and replace `cmd_tick_tokens` in `scripts/budget.py`.
- **Accurate dollars on pod stop.** The dollars counter charges at
  creation based on `bid × count × hours` estimate. If the pod runs
  shorter (preemption) or longer, we over/under-count. Documenting
  here as a known imprecision; a reconciliation pass on `runpod.py
  stop` is a roadmap item.
- **Other CI runners or API providers.** Only `dollars` for RunPod is
  wired today. Vast/Lambda/etc. TBD as their skills land.
