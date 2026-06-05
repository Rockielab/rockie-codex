# PYTHIA Event Handoff

Purpose: artifact-only package for a small event-generation smoke run.
Do not build or run PYTHIA/ROOT on the orchestrator host.

Required inputs: beam/process card, event count, seed, output format.

Compute mode: `rockie_compute`, `user_hpc_ssh`, or `github_handoff`.

Budget cap: smoke event count first; full generation requires explicit cap.

Dashboard profile: `physics.particle_transport_collision.v1`

Expected outputs:

- generator stdout/stderr
- event file metadata, not full large binary dumps in chat
- parsed events, rejection rate, cross section
- histogram or summary plot when ROOT output is available
- result or failure Note

Dogfood status: fixture/handoff evidence only; no simulation claimed.
Executed dogfood requires actual dashboard/result/failure Notes.
