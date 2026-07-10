# publish-gate — the pass-twice contract for shipping a built agent

The publish gate decides one thing: **is this built agent fit to ship?** It is the
meta-level analogue of the diligence agent's internal critic loop — same proven
shape, different scope. The diligence loop hardens ONE deck before the IC sees it;
the publish gate hardens THE AGENT ITSELF before it is published. `scripts/
publish_gate.py` implements it.

## The contract (non-negotiable)

> IF the built agent has not passed a fresh, no-memory adversarial gauntlet
> **twice with zero CRITICALs**, the system SHALL refuse to mark it publishable.

`publish_gate.py` emits a verdict JSON; the agent is publishable **iff**
`publishable: true`, which is true **iff** the gauntlet converged:

```json
{
  "publishable": true,
  "converged": true,
  "rounds": 2,
  "consecutive_clean": 2,
  "required_consecutive": 2,
  "sublayers_run": ["quality"],
  "mode": "single",
  "isolation": "single-process",
  "reason": "converged: 2 consecutive clean rounds at round 2",
  "round_log": [ {"round": 1, "passed": true, "n_critical": 0, "consecutive_passes_after": 1}, ... ]
}
```

## How it reuses the paper / diligence gauntlet (DRY)

The gate does **not** re-implement the loop engine. `publish_gate.py` IMPORTS the
canonical engine from `diligence-deck/scripts/critic_loop.py` — `run_critic_loop`,
`validate_verdict`, the two mode factories, and the `MAX_ROUNDS` /
`REQUIRED_CONSECUTIVE_PASSES` constants. That engine is the same twice-clean,
reset-on-fail, CRITICAL-blocks-PASS, capped loop the `paper` skill's gauntlet and
detector-gate use (`../paper/references/adversarial-gauntlet.md`). The gate adds
ONLY the publish semantics on top: the sublayers and the verdict shape.

The single source of truth means a fix to the gate logic lands in one place. The
ONLY copy of the engine that exists is the one COPIED into each emitted agent
(`references/agent-repo-anatomy.md`), because a portable agent must stand alone.

## Termination rules (inherited verbatim)

- **A round passes** iff every ENABLED sublayer returns zero CRITICAL violations.
- **The clean-pass counter resets to zero on ANY failed round.** A pass followed by
  a fail followed by two passes converges at round 4, not round 3 — the fail wipes
  the earlier pass.
- **Convergence requires two CONSECUTIVE clean rounds.** One pass never unlocks.
  The second pass is a fresh read of the (possibly re-touched) agent and catches
  regressions the fixes introduced.
- **The cap is `MAX_ROUNDS = 6`.** Six rounds without two consecutive clean rounds
  → the gate STOPS and FAILS LOUDLY (`publishable: false`, reason names the cap).
  It never runs a seventh round and never silently accepts; the agent hands off for
  human review.

## The double-layered adversary

Each round runs every enabled sublayer as a fresh, no-memory critic; their
violations are merged, and the round passes only if the union has zero CRITICALs.

| Sublayer | Runs | Prompt | Judges |
|---|---|---|---|
| **quality** | ALWAYS | `prompts/quality-critic.md` | Does the agent achieve its declared goal? Are its tools / prompts / policies sound? Is its reasoning trace defensible? |
| **ai_detection** | OPT-IN (`adversarial.ai_detection: true`) | `prompts/ai-detection-critic.md` | Does the output read as human-authored? SKIPPED when the output is understood to be AI-generated. |

**Opt-in is explicit.** The AI-detection sublayer is added only when the declarer
sets `adversarial.ai_detection: true` (config) or passes `--ai-detection`. Quality
can never be turned off; it is the floor. A CRITICAL in EITHER enabled sublayer
fails the round — a factually perfect agent whose output reeks of LLM filler fails
the gate exactly as a fluent-but-wrong agent does, when AI-detection is on.

## Live critics fail closed

The live path is deliberately transport-agnostic. The builder/orchestrator injects
a critic transport; the CLI can use `--live-command`, which receives one JSON
payload on stdin per sublayer round and must write exactly one strict verdict JSON
object to stdout.

Missing transport, transport errors, empty output, invalid JSON, extra trailing
text, non-object JSON, missing/contradictory boolean `pass`, missing
`violations`, or invalid violation severity all become a CRITICAL round failure.
They never count as a clean round and never produce a publishable verdict. The
deterministic mocked selftest still uses injected callables and does not require
a live transport.

Freshness is per sublayer per round: quality always dispatches once per round; the
ai-detection sublayer dispatches once per round only when explicitly enabled. The
quality critic receives the materialized agent review artifact. The ai-detection
critic receives only the output text under human-authorship review, not the goal,
candidate payload, build history, or prior verdicts.

## Platform candidate binding and backend verdict mapping

For platform edits, the live gate must review the exact candidate returned by:

1. `POST /api/agents/{id}/edits`
2. `AgentEditResponse.candidate` + `candidate_fingerprint`

`publish_gate.py` recomputes the platform fingerprint as canonical JSON
(`sort_keys=True`, compact separators, `default=str`) SHA-256 over the returned
candidate payload. A mismatch halts before any attach request.

The quality review surface is not the raw candidate dict alone. The gate
materializes a review artifact from the current agent record plus the candidate:
declared goal, config, manifest, skills, hooks, policies, tests, prompts/tools,
and sample run evidence when available. The binding records both the platform
`candidate_fingerprint` and a separate hash of this materialized review artifact.

The backend-bound body is mapped from the internal verdict to the
`GauntletVerdict` schema:

```json
{
  "publishable": true,
  "clean_rounds": 2,
  "produced_at": "2026-06-23T12:00:00+00:00",
  "candidate_fingerprint": "<platform candidate fingerprint>",
  "rounds": [
    {"round": 1, "passed": true, "violations": []},
    {"round": 2, "passed": true, "violations": []}
  ],
  "notes": "converged: 2 consecutive clean rounds at round 2"
}
```

`rounds` is the per-round list, not the internal integer round count. The mapper
requires a verified candidate-binding record; it does not accept an arbitrary
fingerprint parameter.

## Backend attach flow

The HTTP attach helper is opt-in. It uses `ROCKIELAB_API_URL` or an explicit
`api_url` and posts to the existing session-authenticated agents routes:

1. `POST /api/agents/{id}/edits`
2. `POST /api/agents/{id}/edits/{edit_id}/gauntlet`

The caller must provide the normal dashboard session cookie, e.g.
`Cookie: rockielab_session=...`. The agent edit routes do not use the experiment
runtime `X-Tenant-Token` auth path, and they do not accept a password/CLI bearer
as a user session; `publish_gate.py` refuses attach clients without a Cookie.
Non-2xx responses raise an API error and do not mark a candidate publishable
locally.

## Execution modes (both supported)

- **subagent (preferred).** Each sublayer, each round, is a fresh no-memory
  subagent handed only its prompt + the agent under review. Freshness is
  process-enforced.
- **single (degraded fallback).** When the builder cannot spawn nested subagents,
  each sublayer-round is a fresh reasoning pass in-process with a HARD CONTEXT
  RESET — no memory of any prior verdict. Weaker isolation (a single context can
  leak a tell it already waved through), so the verdict is labelled
  `single-process`. The termination rules are identical.

## Proving the gate logic

`publish_gate.py --selftest` drives the gate with scripted, mocked sublayer
verdicts (no model call) and proves: quality-only convergence, reset-on-fail (round
4 not 3), an AI-detection CRITICAL failing a round whose quality was clean, the
opt-in being skipped when no AI critic is supplied, the refusal/cap path, that one
pass does not unlock, and that both modes drive identical logic. Focused unit tests
cover the live adapter, ai-detection input isolation, platform schema mapping,
candidate materialization/binding, and attach request shape. The live LLM critics
are injected by the builder orchestrator (`prompts/builder.md`); the engine stays
runtime-agnostic and deterministically testable.
