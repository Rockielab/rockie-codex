# Environment variables

rockie ships with zero secrets in source. Every secret — RunPod API
key, ntfy topic, future provider keys — lives in a local `.env` file
that's gitignored and never committed.

## Quickstart

```bash
# From your project (or from the rockie clone itself):
cp .env.example .env
$EDITOR .env               # fill in real values

# Load into your shell — every subprocess rockie spawns in this
# shell inherits the vars.
set -a; . .env; set +a

# Verify:
python3 .codex/scripts/runpod.py auth
```

## Where `.env` lives

- **In the rockie repo itself** — `~/Experiments/rockie/.env`.
  Used when you're developing or testing rockie.
- **In a user's research repo after `install.sh`** — the installer
  copies `.env.example` into `<project>/.codex/_local/env.example`
  (coming soon) or you place `.env` at the project root and source it
  from your shell.

Either way, the rules in `install-assets/gitignore.rockie` and in
the installer's merged block ensure `.env` is never tracked.

## What goes in `.env`

See `.env.example` at the repo root for the full list. Current
variables:

| Name | Purpose | Where used |
|---|---|---|
| `RUNPOD_API_KEY` | RunPod GraphQL auth | `scripts/runpod.py` |
| `NTFY_TOPIC` | Push notification topic | `scripts/notify.sh`, `scripts/ntfy_poll_responses.sh` |
| `NTFY_SERVER` | ntfy server override (optional) | `scripts/notify.sh` |
| `VAST_API_KEY` *et al* | Future provider keys | planned |

## Auto-loading in a new shell

If you want `.env` to load automatically when you `cd` into the repo,
use `direnv` (one-time setup):

```bash
brew install direnv
# Hook direnv into your shell: add `eval "$(direnv hook zsh)"` to ~/.zshrc
echo 'dotenv' > .envrc   # loads .env on cd-in
direnv allow .
```

rockie doesn't require direnv — the manual `set -a; . .env; set +a`
is fine.

## Rotation

Treat `.env` like any other credentials file:

- Keys that have been shared in a chat, a screenshot, a log, or a git
  diff are compromised — rotate them in the provider's dashboard.
- Delete old values from `.env` rather than commenting them out.
- Scan `git log -p .env` periodically (it should be empty — if it
  isn't, a key was committed once and is compromised; rotate).

## What the agent sees

rockie's hooks and skills read env vars just like any other
process. The `stage-inject`, `load-relevant-rules`, etc. hooks run
under the Codex session's shell, so they see whatever was
exported there. If you start autopilot with `nohup`, remember to
source `.env` first:

```bash
set -a; . .env; set +a
nohup bash .codex/scripts/autopilot_loop.sh \
      > .codex/memory/autopilot.log 2>&1 &
```

## For contributors

Before opening a PR:

1. `grep -r 'rpa_' . | grep -v '.env\|.env.example'` — nothing
   should match (rpa_ is the RunPod key prefix). Replace with
   whatever prefix your key family uses.
2. `git log -p -- .env` — history should be empty.
3. `git check-ignore -v .env` — must show the gitignore rule.
