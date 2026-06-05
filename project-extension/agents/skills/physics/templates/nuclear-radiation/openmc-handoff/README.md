# OpenMC Radiation Handoff

Purpose: artifact-only/HPC handoff for neutron/photon tally workflows.
Local execution is not assumed because cross-section data and use
authorization must be supplied by the researcher.

Required inputs: geometry/materials, source, tallies, batches,
particles, seed, authorized cross-section library path.

Compute mode: `user_hpc_ssh`, `tenant_runtime`, or `artifact_only`.

Budget cap: low-history smoke first.

Dashboard profile: `physics.nuclear_radiation.v1`

Expected outputs: statepoint metadata, stdout/stderr, tally summary,
relative error, Shannon entropy when applicable, result/failure Note.

Dogfood status: fixture/handoff evidence only; no simulation claimed.
Executed dogfood requires actual dashboard/result/failure Notes.
