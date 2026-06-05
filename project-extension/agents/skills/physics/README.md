# Physics Skill Suite

`skills/physics/SKILL.md` is the only discoverable skill entrypoint.
The eight v1 domain modules are routed references because platform skill
discovery is currently top-level only.

Contents:

- `references/` - routing modules, software landscape, and license policy
- `templates/` - open-source smoke and artifact-only/HPC handoff packages
- `runtime/classifier/` - deterministic fixture-backed classifier helper
- `runtime/monitoring-profiles/` - dashboard-compatible profile fixtures
- `runtime/parser-fixtures/` - lightweight sample logs and expected metric envelopes

Focused verification:

```bash
python3 tests/physics/test_physics_suite.py
```

The suite intentionally does not bundle proprietary software or heavy
physics engines. Local tests validate routing, license posture, parser
fixtures, monitoring profile shape, and template lint without scientific
dependencies.

Dogfood status: this PR supplies fixture/handoff evidence only. It does
not claim executed dogfood. Later cascade phases must attach actual
dashboard, result, or failure Notes, or explicitly record partial/blocking
status when execution infrastructure is unavailable.
