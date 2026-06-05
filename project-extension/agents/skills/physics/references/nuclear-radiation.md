# Nuclear and Radiation Transport

Use for neutron/photon transport, shielding, reactor-like tallies,
source convergence, depletion setup, radiation dose, and cross-section
library issues.

## Open-Source Defaults

- OpenMC: Monte Carlo neutron/photon transport when data libraries are
  authorized and available.
- Geant4: radiation transport through detector/geometry workflows.

MCNP-style workflows may be export-controlled or institution-restricted.
Use only authorized user environments and refuse access-control evasion.

## Validation

Track histories, tallies, relative error, missing cross-section data,
Shannon entropy/source convergence when applicable, inactive/active
batches, seeds, and statistical uncertainty. Never fabricate completed
histories from an input deck.

Profile: `physics.nuclear_radiation.v1`

Template: `templates/nuclear-radiation/openmc-handoff/README.md`
