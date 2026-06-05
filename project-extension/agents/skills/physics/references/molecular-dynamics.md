# Molecular Dynamics

Use for classical atomistic/coarse-grained dynamics, enhanced sampling,
energy minimization, equilibration, trajectory production, transport
coefficients, and thermodynamic observables.

## Open-Source Defaults

- LAMMPS: materials, polymers, coarse-grained, custom potentials.
- GROMACS: biomolecular and high-throughput classical MD.
- OpenMM: Python-authored methods and fast prototyping on compute nodes.
- CP2K: mixed classical/ab initio or QM/MM-adjacent workflows.

## Inputs and Outputs

Inputs: structure/topology, force-field provenance, timestep,
thermostat/barostat, ensemble, constraints, cutoffs, seeds, run length.
Outputs: logs, thermo table, trajectory, restart/checkpoint, energy
files, parsed metrics, plot artifact, result or failure Note.

## Validation

Run minimization first. Smoke-test with short NVT/NVE dynamics before
full production. Watch temperature, pressure, total/potential/kinetic
energy, energy drift, density, neighbor-list warnings, constraint
failures, and trajectory freshness.

Profile: `physics.molecular_dynamics.v1`

Template: `templates/molecular-dynamics/lammps-smoke/README.md`
