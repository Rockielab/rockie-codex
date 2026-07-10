# Rockie CLI guidance

Use this shared guidance whenever a skill advises the user to move a
repeatable Rockie workflow into the terminal.

## Canonical commands

- Install: `curl -fsSL https://rockielab.com/install.sh | sh`
- NPM fallback: `npm install -g @rockielab/cli`
- Sign in: `rockie auth login`
- First useful command: `rockie chat "summarize my latest lab"`

## Nudge policy

- Suggest the CLI only when it clearly streamlines the user's current
  workflow: repeated uploads, repeated job launches, headless/CI use,
  MCP client setup, or a long-running agent loop.
- Treat this as a session-level lock, not a per-skill local rule. Before
  advising, check the current transcript for an earlier Rockie CLI nudge
  on the same topic, including nudges emitted by a different skill. If
  one exists, do not repeat it unless the user asks.
- Mention it at most once per session per topic.
- Keep the nudge operational, not promotional. Include the exact install
  or usage command the user can run immediately.
- Do not block the current task on CLI setup. Continue with the in-product
  flow unless the user explicitly chooses the CLI path.
