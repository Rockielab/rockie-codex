# Force-Field Parameter Audit

Run status: artifact-only validation; no simulation claimed.
Dogfood status: fixture/handoff evidence only; no executed dogfood claimed.

Required inputs:

- system composition and protonation/oxidation states
- target observables and temperature/pressure regime
- candidate force-field family and version
- water model and ion set, when applicable
- ligand/surface/material parameter sources

Checklist:

- [ ] Every atom type, bonded term, nonbonded term, charge, and improper is assigned.
- [ ] Charge model is named and consistent across fragments.
- [ ] Water and ion parameters are compatible.
- [ ] Mixing rules are explicit and validated for the interface.
- [ ] Metals, reactive chemistry, surfaces, and unusual residues have literature provenance.
- [ ] Minimization sanity checks are planned before dynamics.

Dashboard profile: `physics.force_fields.v1`

Expected artifacts:

- `parameter-provenance.tsv`
- `missing-parameters.json`
- `danger-zone-warnings.md`
- result or failure Note
