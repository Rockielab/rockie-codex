# Plasma and PIC

Use for particle-in-cell, kinetic plasma, laser-plasma, sheath, beam,
and field/particle workflows.

## Open-Source Defaults

- WarpX: exascale electromagnetic PIC and openPMD outputs.
- Smilei: PIC plasma simulation with Python namelists.
- PIConGPU: GPU-heavy PIC workflows.
- Gkeyll: kinetic and fluid plasma modeling.

## Validation

Track timestep, Courant constraints, particles per cell, charge/current
conservation, field energy, boundary conditions, output dump cadence,
and openPMD/HDF5 freshness. Prefer artifact-only/HPC handoff for GPU or
large MPI cases.

Profile: `physics.plasma_pic.v1`

Template: `templates/plasma-pic/warpx-hpc-handoff/README.md`
