# Force Fields

Use when the request is primarily about parameter selection,
parameterization, charge assignment, mixing rules, missing terms,
water/ion compatibility, surfaces, metals, unusual residues, or mixed
biomolecular/material systems. Load this module as a dependency for most
classical MD plans.

## Default Path

1. Identify system classes: protein/nucleic acid, lipid, small molecule,
   polymer, inorganic surface, metal, electrolyte, mixed interface.
2. Pick force-field families with matching validation domain before
   convenience: AMBER/CHARMM-family biomolecules, OPLS/GAFF/CGenFF-style
   small molecules, INTERFACE/ClayFF/ReaxFF/COMB/EAM-style materials
   only when they match the chemistry and target property.
3. Check charge model, protonation state, water model, ion parameters,
   combining rules, cutoffs, constraints, and long-range electrostatics.
4. Produce a provenance table linking parameter source, version,
   literature/source URL, and known validity range.
5. Require minimization and bad-contact checks before dynamics.

## Danger Zones

- Metals and reactive chemistry are not handled by ordinary biomolecular
  force fields.
- Ions can be water-model-specific; mixing ion sets across TIP3P, SPC/E,
  OPC, and TIP4P variants can change osmotic and structural behavior.
- Unusual residues, ligands, cofactors, surfaces, and polymer end groups
  need explicit parameter provenance.
- Lorentz-Berthelot mixing may be wrong for interface or ion adsorption
  studies unless validated.
- Mixed biomolecular/material systems often require interface-specific
  validation and small benchmark comparisons.

## Monitoring Signals

Profile: `physics.force_fields.v1`

Track parameterization status, missing parameters, charge assignment,
water/ion compatibility, mixing rules, minimization result, bad contacts,
and parameter provenance.

## Templates

- `templates/force-fields/parameter-audit.md`
- `templates/force-fields/result-note-outline.md`
- `templates/force-fields/failure-note-outline.md`
