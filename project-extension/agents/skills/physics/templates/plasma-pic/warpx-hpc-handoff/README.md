# WarpX HPC Handoff

Purpose: artifact-only/HPC handoff for a minimal PIC plasma case.
Local execution is not safe because WarpX builds and runs are heavy.

Required inputs: grid, timestep, species, particles per cell, boundary
conditions, output cadence, openPMD path.

Compute mode: `user_hpc_ssh` or `github_handoff`.

Budget cap: small timestep smoke before production.

Dashboard profile: `physics.plasma_pic.v1`

Expected outputs: stdout/stderr, openPMD metadata, field-energy metrics,
checkpoint/output freshness, dashboard Note, result or failure Note.

Dogfood status: fixture/handoff evidence only; no simulation claimed.
Executed dogfood requires actual dashboard/result/failure Notes.
