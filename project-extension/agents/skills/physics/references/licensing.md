# Physics Licensing and Authorized Environment Policy

## License Postures

Every package row in `software-landscape.md` must use exactly one value:

- `open_source`
- `free_academic_or_noncommercial`
- `commercial_or_proprietary`
- `restricted_export_or_controlled`
- `unknown_needs_review`

Prefer `open_source` when it can answer the scientific question
credibly. Non-open tools can be part of a run plan only when the
researcher provides authorized access.

## Allowed Licensed Paths

- Tenant secrets that resolve inside the approved runtime path.
- SSH/HPC module environments already available to the researcher.
- Researcher-provided license server variables or license files.
- Existing binary paths or mounted filesystems supplied by the user.
- Artifact-only or GitHub handoff packages that the researcher runs in
  their authorized environment.

## Refusals

Refuse requests to:

- download, bundle, mirror, scrape, or redistribute proprietary installers
- bypass license checks or institution access controls
- crack license servers, alter binaries, or forge entitlement
- expose license tokens, private server names, SSH keys, module paths
  or other credential material in chat/logs/Notes
- provide controlled nuclear or export-sensitive data outside an
  authorized researcher environment

If verification fails, stop before compute. Create a failure Note plan
with the missing environment field, redacted evidence, and an
open-source fallback such as Quantum ESPRESSO/CP2K instead of VASP,
OpenFOAM/SU2/CalculiX instead of COMSOL/Ansys, OpenMC/Geant4 instead of
MCNP where scientifically and legally appropriate, or force-field
validation without Amber/CHARMM binaries.

## Redaction Rules

Redact exact values for:

- license tokens and secret environment variables
- license server hostnames, ports, and server strings
- private endpoints and SSH targets
- full module paths and full paths under sensitive or institution mounts
- institution-restricted data library locations

Use stable placeholders such as `<redacted-license-server>`,
`<redacted-module-path>`, and `<authorized-hpc-path>` in Notes and logs.
