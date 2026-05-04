# Contributing to rockie-codex

## Ground rules

- Keep the port honest. If Codex cannot do something the original harness did, document the delta instead of faking parity.
- Every upstream port in [docs/PORTS.md](/Users/samuellarson/rockie-codex/docs/PORTS.md) should cite source repo, file path, and line range.
- Prefer additive, composable changes over replacing the harness’s core differentiators.
- If you touch runtime behavior, extend or adjust `tests/smoke-test.sh`.
- Do not copy code from non-MIT/non-Apache-2.0 sources into this repo.

## Required commit policy

All commits must be signed off by the contributor (git commit -s); do not include any AI-generated co-author trailers in commit messages.

## Local verification

```bash
bash tests/smoke-test.sh
```

For dashboard/orchestrator changes, also run syntax checks:

```bash
node --check user-extension/codex/teams/orchestrator/index.js
node --check user-extension/codex/teams/orchestrator/iteration.js
```

## Porting guidance

- Use [docs/EVENT-MAPPING.md](/Users/samuellarson/rockie-codex/docs/EVENT-MAPPING.md) as the source of truth for Codex runtime assumptions.
- Repo-scoped skills belong in `.agents/skills/`.
- Repo and home hooks belong in `hooks.json`, not `config.toml`.
- Historical slash-command names may stay in prose as nicknames, but public docs should explain the actual Codex skill invocation path.

## Pull requests

- Keep PRs small and logically grouped.
- Call out user-visible behavior changes in the PR summary.
- Note any incomplete parity or deliberate Codex-specific deviation.
