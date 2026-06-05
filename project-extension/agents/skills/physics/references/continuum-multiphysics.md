# Continuum Multiphysics

Use for CFD, finite element analysis, thermal/mechanical models, coupled
PDE workflows, fluid-structure/heat/stress coupling, and mesh-based
simulation.

## Open-Source Defaults

- OpenFOAM: CFD, multiphase, turbulence, reacting flows.
- SU2: compressible/incompressible CFD and optimization.
- MOOSE: coupled PDEs, multiphysics, materials applications.
- CalculiX: structural FEA and thermal/stress analysis.

COMSOL and Ansys require researcher-provided licensed environments.

## Validation

Check mesh quality, units, boundary conditions, material properties,
solver residuals, CFL/timestep, integrated forces/fluxes/stresses,
divergence warnings, and conservation. Do a coarse mesh smoke or
artifact-only handoff before expensive refinement.

Profile: `physics.continuum_multiphysics.v1`

Template: `templates/continuum-multiphysics/openfoam-cavity-handoff/README.md`
