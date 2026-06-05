# Quantum ESPRESSO SCF Smoke Handoff

Purpose: small silicon SCF input deck for Rockie compute or authorized
HPC. Do not run `pw.x` on the orchestrator host.

Required inputs: pseudopotential file path supplied in the compute
environment and validated in the run plan.

Compute mode: `rockie_compute`, `tenant_runtime`, or `user_hpc_ssh`.

Budget cap: smoke first; no full convergence study without explicit cap.

Dashboard profile: `physics.electronic_structure.v1`

Expected outputs:

- `silicon.out`
- `metrics.json`
- `scf-residual.png`
- result or failure Note

Parser:

```bash
python3 skills/physics/runtime/parse_physics_log.py electronic_structure silicon.out fixture-scf
```

Dogfood status: fixture/handoff evidence only; no simulation claimed.
Executed dogfood requires actual dashboard/result/failure Notes.
