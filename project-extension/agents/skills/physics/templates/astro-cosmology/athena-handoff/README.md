# Athena++ Astro Handoff

Purpose: artifact-only/HPC handoff for a small hydrodynamics or MHD
benchmark. Local execution is not safe for production cases.

Required inputs: problem generator, mesh, time limit, output cadence,
checkpoint cadence, boundary conditions, units.

Compute mode: `user_hpc_ssh` or `github_handoff`.

Budget cap: low-resolution smoke before production.

Dashboard profile: `physics.astro_cosmology.v1`

Expected outputs: stdout/stderr, checkpoints, conserved-quantity
summary, output freshness metadata, plot path, result/failure Note.

Dogfood status: fixture/handoff evidence only; no simulation claimed.
Executed dogfood requires actual dashboard/result/failure Notes.
