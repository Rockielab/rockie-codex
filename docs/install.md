# Install

## Requirements

- macOS or Linux
- `python3`
- `/usr/bin/sqlite3` with FTS5 enabled
- `rsync`
- Node 20+ only if you want the dashboard-backed `deploy-team-dashboard` workflow

## Standard install

```bash
git clone https://github.com/saml212/rockie-codex.git ~/rockie-codex
cd ~/rockie-codex
./install.sh ~/path/to/your/project
```

This installs:

- `<project>/.codex/`
- `<project>/.agents/skills/`
- `~/.codex/` unless `--project-only` is passed

## Project-only install

```bash
./install.sh --project-only ~/path/to/your/project
```

Use this in CI or if you do not want to touch `~/.codex/`.

## What gets merged

- project hooks merge into `<project>/.codex/hooks.json`
- user-global hooks merge into `~/.codex/hooks.json`
- the installer preserves existing hook entries and avoids duplicate command registrations
- a managed `.gitignore` block is merged into the target repo

## AGENTS template

After install:

```bash
cp ~/rockie-codex/agents-md/AGENTS.md.template ~/path/to/your/project/AGENTS.md
```

Or for an ML research repo:

```bash
cp ~/rockie-codex/agents-md/ml-research.md ~/path/to/your/project/AGENTS.md
```

## Dashboard dependency

If you want the dashboard-backed team workflow:

```bash
cd ~/.codex/teams/orchestrator
npm install
```

## Verify

```bash
bash tests/smoke-test.sh
```

## Uninstall

Remove the installed runtime from the target repo:

```bash
rm -rf <project>/.codex <project>/.agents/skills
```

Optionally remove the managed gitignore block and any `AGENTS.md` content you
do not want to keep. For user-global helpers, remove the relevant entries from
`~/.codex/`.
