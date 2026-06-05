# LAMMPS Smoke Handoff

Purpose: cheap Lennard-Jones NVT smoke package for Rockie compute or
user HPC. Do not run LAMMPS on the orchestrator host.

Required inputs: none for the generated benchmark; replace with lab
structure/topology for real systems.

Compute mode: `rockie_compute` or `user_hpc_ssh`.

Budget cap: smoke first; full production requires explicit cap.

Dashboard profile: `physics.molecular_dynamics.v1`

Expected outputs:

- `stdout.log`
- `thermo.csv`
- `metrics.json`
- `energy-drift.png`
- `result-note.md` or `failure-note.md`

Parser:

```bash
python3 skills/physics/runtime/parse_physics_log.py molecular_dynamics stdout.log fixture-md
```

Result Note must include method, engine/version, force-field provenance,
inputs, timestep, ensemble, compute shape, budget/spend, plot path,
limitations, and next experiments.

Dogfood status: fixture/handoff evidence only; no simulation claimed.
Executed dogfood requires actual dashboard/result/failure Notes.
