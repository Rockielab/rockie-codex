# Electronic Structure

Use for DFT, quantum chemistry, SCF calculations, geometry optimization,
phonons, band structures, orbitals, charges, forces, and ab initio MD
setup.

## Open-Source Defaults

- Quantum ESPRESSO: plane-wave periodic DFT and band workflows.
- CP2K: Gaussian/plane-wave DFT, AIMD, large condensed-phase systems.
- GPAW: Pythonic DFT workflows and educational smoke cases.
- Psi4: molecular quantum chemistry and small reference calculations.
- ABINIT: plane-wave DFT and response-property workflows.

Licensed paths such as VASP, Gaussian, and ORCA require user-provided
authorized environments. Do not bundle or download them.

## Validation

Check pseudopotential provenance, basis/cutoff convergence, k-points,
smearing, charge/spin state, SCF residuals, force thresholds, geometry
step behavior, and wall time per step. Non-convergence is a failure Note
candidate, not a reason to silently loosen physics.

Profile: `physics.electronic_structure.v1`

Template: `templates/electronic-structure/qe-scf-smoke/README.md`
