<!--
Thanks for contributing!

Before you submit, please make sure:
 - `bash tests/smoke-test.sh` still passes
 - Any port cites source file + line range (CONTRIBUTING.md §"Shape of a port")
 - You ran `/clean` (or the audit underneath) before committing
-->

## Summary
<!-- What does this PR do and why? -->

## Port citation (if applicable)
- Source: `<owner>/<repo>` → `<file>:<lineStart>–<lineEnd>`
- License: MIT | Apache-2.0 | ⚠ restrictive → reimplemented pattern only

## Testing
<!-- What smoke-test assertion(s) did you add/modify?
     If you tested by hand, describe the steps. -->

## Checklist
- [ ] Composes with existing differentiators (doesn't duplicate)
- [ ] Smoke test updated + passing (`bash tests/smoke-test.sh`)
- [ ] Docs updated (`docs/PORTS.md`, `CHANGELOG.md`, README if user-facing)
- [ ] No `[LEARN]` data from a specific project leaked
- [ ] No personal info (email, paths, IDs) added
