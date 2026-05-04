# Security Policy

## Reporting

Please report vulnerabilities privately to:

`security@<placeholder>`

Include:

- affected file(s)
- a concrete reproducer
- expected impact

## Scope

This project is a local-first harness. The primary risk surfaces are:

- adversarial model output being persisted into the memory DB
- unsafe shell or path handling in hooks and scripts
- dashboard/orchestrator process exposure on the local machine
- accidental publication of secrets or private project context

## Current hardening priorities

- parameterized DB writes for captured memory
- path-containment checks around file writes and staged context
- idempotent installer behavior that avoids clobbering existing local state
- explicit documentation for unsupported or partially mapped Codex behavior

## Out of scope

- compromise of the Codex runtime itself
- compromise of the local machine or shell environment
- secrets already exposed outside this repository
