---
name: onboard
description: One-time researcher onboarding interview that compiles a `taste/` corpus (SOUL.md, STYLE.md, METHODOLOGY.md, DISMISSALS.md, MEMORY.md, INDEX.md) capturing the researcher's intellectual taste, beliefs, and values. Auto-injects INDEX.md into every future session via SessionStart. Triggers on first install ("no taste corpus found"), explicit `/onboard`, `/onboard --deep` for Tier 2 voice laddering, or `/onboard --redo` / `/onboard --section <name>` to refresh.
---

# /onboard — researcher taste interview

The marquee onboarding skill. Produces a durable, agent-injectable
record of *who* the researcher is, *what* they believe, *how* they
judge work, and *what dead ends* they refuse to revisit.

Sister to AGENTS.md. AGENTS.md says what to do in this repo. The
`taste/` corpus says who this researcher is — installed per-repo
today, with cross-repo portability planned (symlink
`~/.rockie/taste/` → `<repo>/.rockie/taste/` is the recommended
manual interim).

## When to run

- **First-run** — SessionStart hook flags absence of
  `.rockie/taste/INDEX.md`; agent suggests `/onboard`.
- **Explicit invocation** — user types `/onboard`.
- **Refresh** — `/onboard --redo` rewrites everything; `/onboard
  --section <soul|style|methodology|dismissals>` refreshes one file.
- **Deep mode** — `/onboard --deep` runs Tier 2 (20–30 min,
  voice-first laddering). Otherwise Tier 1 (5–7 questions, ~5 min).

## What the skill does

1. Loads `prompts/interviewer-tier1.md` (or `interviewer-tier2.md` if
   `--deep`) into the active agent's system context.
2. The agent runs the interview turn-by-turn following the prompt's
   phase-gated state machine. The user answers via text or
   `/voice tap`.
3. As the interview progresses, the agent writes intermediate state
   to `.rockie/taste/.draft.json` after every turn (so the session
   can be resumed if interrupted).
4. When coverage reaches the end-condition, the agent emits a summary
   round, asks the user to confirm or correct, then runs
   `runtime/compile.py` to produce the six markdown files in
   `.rockie/taste/`.
5. The agent opens `INDEX.md` in the user's editor for final review,
   then commits the corpus.

## Hard rules

- **One question per turn.** The interviewer prompt enforces this with
  a question-mark self-check; the agent must respect it.
- **Never press a dodged question.** Mark SOFT in the scratchpad and
  move on. Pressing produces confabulation, not truth.
- **Never silently rewrite an existing taste file.** `/onboard --redo`
  is explicit; the agent cannot decide to overwrite SOUL.md
  unprompted. (MEMORY.md and DISMISSALS.md are append-only and may be
  written to by Stop-hook flow, not this skill.)
- **Never invent answers.** If the user is short on a topic, the
  generated file marks the topic as `[SOFT — needs deepening]`
  rather than embellishing.
- **Voice opt-in only.** Tier 1 is text-default; Tier 2 prompts the
  user to `/voice tap` for each answer if they want, but never
  requires it.

## Outputs

```
.rockie/taste/
├── INDEX.md           # auto-injected every session via SessionStart
├── SOUL.md            # identity, worldview, hot takes
├── STYLE.md           # written + spoken voice
├── METHODOLOGY.md     # rigor standards, success criteria
├── DISMISSALS.md      # append-only "never again" log
├── MEMORY.md          # append-only session-experience log
└── .draft.json        # interview transcript (gitignored)
```

The corpus is gitignored by default (personal — like `.env`). Users
can opt to commit it by removing the entry from
`.rockie/taste/.gitignore`. (For shared-team taste, see future
roadmap entry on team-level taste compositing.)

## Agent invocation protocol

When this skill fires, the agent should:

1. Resolve which mode: Tier 1 (default), Tier 2 (`--deep`), refresh
   (`--redo` or `--section`).
2. Read `prompts/interviewer-tier1.md` (or tier2) — this is the
   active system prompt for the duration of the interview.
3. Begin Turn 1 by greeting the user briefly and asking the first
   question. Do NOT explain the schema; the prompt is structured so
   the user discovers what they're contributing turn by turn.
4. After each user answer, regenerate the full scratchpad (do not
   append to it) following the MIRROR structure in the prompt.
5. Persist `.draft.json` after every answer. Schema:
   ```json
   { "started_at": "...", "tier": 1, "topics": {
       "identity": {"q": "...", "a": "...", "soft": false, "ladder": []},
       ...
     }, "coverage": {"identity": 2, "soul": 1, ...} }
   ```
6. End-condition: all topics ≥ 1 AND (all topics ≥ 2 OR seven
   questions asked). At end-condition, summarize captured signal
   per file, ask user to confirm or correct, then compile.
7. Run `python3 .agents/skills/onboard/runtime/compile.py
   .rockie/taste/.draft.json` — this writes the six markdown files
   from templates and the draft JSON.
8. Open `.rockie/taste/INDEX.md` for the user to review and edit.

## Failure modes

- **User goes off-topic for 3+ turns** — agent bridges back per the
  prompt's anti-drift rule.
- **User signals exhaustion** ("can we wrap up?") — agent honors;
  emits compile from current coverage; marks low-coverage files
  `[SOFT — needs deepening]`.
- **Voice transcript is empty / garbled** — agent asks user to type
  this answer instead.
- **Compile script errors** — agent reports the error, retains
  `.draft.json`, and suggests re-running `/onboard` (the existing
  draft is loaded from disk and the interview continues from where
  it stopped).
- **Partial draft (interview interrupted before 3 topics covered)**
  — `compile.py` exits 3 with a "refusing to compile" message. Agent
  re-runs `/onboard` to continue the interview rather than shipping
  a placeholder corpus.

## Re-runs

`/onboard --redo` archives the existing corpus to
`.rockie/taste/.archive/<timestamp>/` and starts fresh. Identity
shifts deserve audit trail.

`/onboard --section <name>` runs only the questions for that section,
re-compiles only that file, archives the prior version.
