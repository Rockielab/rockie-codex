# Quickstart

## 1. Install the harness

```bash
git clone https://github.com/saml212/rockie-codex.git ~/rockie-codex
cd ~/rockie-codex
./install.sh ~/path/to/your/project
```

## 2. Add `AGENTS.md`

```bash
cp ~/rockie-codex/agents-md/AGENTS.md.template ~/path/to/your/project/AGENTS.md
```

## 3. Open Codex in the target project

Start Codex from the project root so it can see:

- `AGENTS.md`
- `.codex/hooks.json`
- `.agents/skills/`

## 4. First-session moves

Recommended order:

1. Ask Codex to use `$onboard`
2. If you want a mode overlay, ask Codex to use `$mode`
3. If you want a pre-commit audit, ask Codex to use `$clean`

The docs still use names like `/onboard` and `/mode` as historical shorthand,
but the practical Codex path is `$skill` or natural language.

## 5. Verify the install

```bash
bash ~/rockie-codex/tests/smoke-test.sh
```

## 6. Team workflows

- Use `deploy-team` for the repo-local Python/Codex team path
- Use `deploy-team-dashboard` if you specifically want the live dashboard workflow
