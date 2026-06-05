# Astro and Cosmology

Use for N-body, hydrodynamics, MHD, cosmology, redshift evolution,
galaxy/cluster simulations, checkpointing, and domain decomposition.

## Open-Source Defaults

- Athena++: grid hydrodynamics and MHD.
- Enzo: cosmology and AMR workflows.
- GADGET-family workflows: review license/version before use.

## Validation

Track simulation time or redshift, conserved quantities, timestep
hierarchy, particle/cell counts, checkpoint cadence, output freshness,
domain decomposition, and load-balance warnings. Use small generated
problems or artifact-only/HPC handoff for expensive production runs.

Profile: `physics.astro_cosmology.v1`

Template: `templates/astro-cosmology/athena-handoff/README.md`
