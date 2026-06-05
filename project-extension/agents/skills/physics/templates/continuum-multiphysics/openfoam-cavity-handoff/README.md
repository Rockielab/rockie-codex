# OpenFOAM Cavity Handoff

Purpose: small cavity-flow case outline for compute or user HPC. Do not
run OpenFOAM on the orchestrator host.

Required inputs: mesh/case files, boundary conditions, solver, end time,
write interval, material properties.

Compute mode: `rockie_compute`, `user_hpc_ssh`, or `artifact_only`.

Budget cap: coarse mesh smoke first.

Dashboard profile: `physics.continuum_multiphysics.v1`

Expected outputs:

- solver log
- residual metrics JSON
- residual plot
- case metadata
- result or failure Note

Parser:

```bash
python3 skills/physics/runtime/parse_physics_log.py continuum_multiphysics solver.log fixture-cfd
```

Dogfood status: fixture/handoff evidence only; no simulation claimed.
Executed dogfood requires actual dashboard/result/failure Notes.
