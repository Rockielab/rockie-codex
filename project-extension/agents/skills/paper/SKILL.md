---
name: paper
description: Write submission-grade research papers end to end inside a Rockie lab, the way a careful human researcher does — not generic LLM filler. Three entry points. /lit-review pulls and ranks a corpus and persists a human reading list Note plus a machine-readable index Note. /paper-draft produces a brief, a page-budgeted outline, per-section drafts, an adversarial review gauntlet (attack, defense, rebuttal, style, format), and a final AI-vs-human detector gate. /publish assembles a downloadable bundle, lands it as a lab Note, and optionally exports to GitHub or Hugging Face. Triggers on "write a paper", "lit review", "literature review", "draft the paper", "review my paper", "run the gauntlet on this draft", "publish the paper", "submit to <venue>", "/lit-review", "/paper-draft", "/publish".
---

# paper — submission-grade research writing for a Rockie lab

This skill turns a lab's evidence (experiment logs, result Notes, a corpus of
sources) into a paper that survives hostile review. It is **agent-instruction
driven**: you, the Rockie agent, follow this procedure and dispatch your own
fresh-context subagents for the review gauntlet and the detector gate. There is
no heavy runtime here. The single code artifact, `templates/figure-gen.py.tmpl`,
is a template a figure agent fills in and runs on Rockie compute — this skill
never executes it.

The method this skill reproduces is documented in `references/method.md`. It is
the same pipeline that produced a real ICML MI-workshop submission: a hard
styleguide, a five-stage adversarial gauntlet, and a detector loop that does not
stop until two consecutive rounds of fresh judges call the prose "100% human".
Do not invent a lighter method. The whole point is that ordinary LLM drafting
produces filler; this procedure filters it out.

## Routing

Pick the entry point from the user's intent. The three are a pipeline but each
runs independently — a user can lit-review without drafting, or publish a draft
that was gauntleted in an earlier session.

| Entry point | Trigger intent | What it does | Reference |
|---|---|---|---|
| `/lit-review` | "lit review", "survey the literature on X", "what's the prior work" | Rank a candidate corpus; persist a human reading-list Note + a machine-readable index Note | `references/lit-review.md` |
| `/paper-draft` | "write the paper", "draft section N", "run the gauntlet", "review my draft" | Brief → page-budgeted outline → per-section drafts → gauntlet → detector gate → accept-ready draft | `references/method.md`, `references/styleguide.md`, `references/adversarial-gauntlet.md`, `references/detector-gate.md` |
| `/publish` | "publish", "submit to <venue>", "export to GitHub/HF" | Assemble bundle → land as Note + downloadable artifact → optional GitHub/HF export → Rock-Collection stub | `references/publish.md` |

If the user's request spans more than one entry point ("write and publish a
paper on X"), run them in order: `/lit-review` → `/paper-draft` → `/publish`,
treating each one's persisted Notes as the next one's input.

### Routing rules

1. **Sources in, Notes out.** Treat the lab's Sources as read-only inputs. Every
   artifact this skill produces — reading lists, indices, drafts, review reports,
   bundles — is a Note (or a downloadable artifact), never a mutation of a Source.
   This is a hard rule shared by all three entry points.
2. **The lab is the substrate.** Persist through the platform-context Notes and
   artifacts services (see `references/publish.md` for the API shape). A fresh
   agent that joins the lab later must be able to reconstruct where you were from
   the persisted Notes alone.
3. **Compute runs on Rockie, not here.** Any figure generation or LaTeX compile
   routes through the lab's runtime (the `/experiment` path), never the
   orchestrator host. This skill emits the script and the command; the runtime
   runs it.
4. **Never fabricate.** No invented citations, no invented numbers, no fabricated
   canonical URL. Every numerical claim in a draft maps to a real evidence row
   (`references/method.md` § "Claims-to-evidence map"); the Rock-Collection push
   is an explicit labeled stub until #57 lands (`references/publish.md`).

## How roles are run (fresh-context subagents)

Every review role in this skill — each gauntlet stage (attack, defense, rebuttal,
style, format), the pre-gauntlet style judge, and each detector judge — runs as a
**fresh-context subagent**, not as a sub-task of your own thread. You (the
orchestrating Rockie agent) dispatch each role through your Agent/Task tool,
passing it three things:

1. **The role prompt file** — `prompts/attack-agent.md`, `prompts/defense-agent.md`,
   `prompts/rebuttal-agent.md`, `prompts/style-judge.md`, `prompts/format-auditor.md`,
   or `prompts/detector-judge.md` — as the subagent's instructions.
2. **The current draft** (or the section under review).
3. **The relevant evidence** — the brief's claims-to-evidence map, the prior-stage
   artifacts the role needs (e.g. the defense agent gets `01_attack_report.md`), and
   for the detector judge nothing but the prose itself.

**"Fresh" is load-bearing.** A fresh subagent has *no memory of prior rounds* and no
knowledge that the draft is machine-assisted, so it cannot be coached, cannot
remember a tell it waved through last round, and cannot converge with the other
judges on a shared blind spot. Re-using one thread across rounds (or letting a judge
see the previous round's verdicts) defeats the gate — an agent that knows the answer
is being looked for grades softly. Spawn a new subagent per role per round.

This is the same dispatch pattern the `deploy-team` skill uses
(`skills/deploy-team/SKILL.md`); `paper` just sequences some roles (attack → defense
→ rebuttal) where `deploy-team` fans out.

### Degraded mode — single-process fallback (supported, not a failure)

The multi-subagent dispatch above is **preferred**. But some runtimes cannot
dispatch subagents at all — a single tenant agent with no Agent/Task tool, an
offline or constrained runner. The skill MUST still work there. **When no
subagent dispatch is available, run each role as a separate fresh *reasoning
pass* inside your own process** instead of as a separate subagent. This is a
supported fallback, not a degraded result — the same roles, the same prompts,
the same termination rules; only the isolation mechanism changes.

The single rule that makes it work is a **hard context reset between roles and
between rounds**. For each pass:

1. **State only:** the current draft (or the section under review), the role's
   prompt file as the instructions for *this* pass, and the role's required
   evidence (the brief's claims-to-evidence map, the prior-stage artifacts the
   role needs). Nothing else.
2. **Carry no memory** of prior roles or prior rounds into the pass — no
   recollection of earlier verdicts, no awareness that the draft is
   machine-assisted, no "I already looked at this". Treat each pass as if it
   begins cold. That self-imposed amnesia is what substitutes for a fresh
   subagent's empty context: a role that remembers its own prior verdict grades
   softly, exactly the failure the fresh-subagent path avoids.
3. **Label the output `single-process`** (e.g. in the artifact header or the
   Note `metadata`) so a reviewer of the run knows the role isolation was
   simulated by role-reset, not enforced by separate processes.

Because the reset is self-imposed rather than enforced by a separate context,
single-process isolation is **weaker** than the subagent path — note that
honestly and do not claim subagent-grade independence. The termination rules are
unchanged: the gauntlet still SHALL NOT terminate on an unresolved CRITICAL, and
the detector gate still needs two consecutive all-"100% human" rounds and still
caps at `MAX_ROUNDS = 6` (`references/detector-gate.md`,
`references/adversarial-gauntlet.md`).

## /paper-draft — the spine

`/paper-draft` is where the method lives. The full procedure is in
`references/method.md`; the short version:

1. **Brief.** Fill `templates/brief.md`: venue, thesis (one falsifiable
   sentence), per-section page budget, and the claims-to-evidence-to-figure map.
   Refuse to start drafting until the brief exists and every planned numerical
   claim names an evidence row.
2. **Outline.** Fill `templates/outline.md`: one row per section with its page
   budget and the claims it carries.
3. **Draft.** One file per section. Every numerical claim cites its evidence row.
   Figures come from one versioned script (`templates/figure-gen.py.tmpl`) with
   self-contained captions — no "TODO", "pending", or "will be added".
4. **Style.** Dispatch the style judge (`prompts/style-judge.md`) against
   `references/styleguide.md`. Drive every violation to zero. Fail on any hit.
5. **Gauntlet.** Run the five stages in order — attack, defense, rebuttal, style,
   format — per `references/adversarial-gauntlet.md`. The gauntlet does not
   terminate while any CRITICAL attack is unresolved. The rebuttal emits an
   ordered fix list; apply it and re-run the affected claims.
6. **Detector gate.** Only after the gauntlet and style judge both pass, run the
   detector gate (`references/detector-gate.md`): at least two fresh, no-memory
   judges classify the draft AI vs human. It terminates only on two consecutive
   rounds of all-judges "100% human". Mark the draft accept-ready.

## When NOT to use this skill

- A quick summary, a blog post, or an internal memo — those do not need the
  gauntlet. This skill is for submission-grade output where hostile review is
  expected.
- Editing a Source in place — this skill never mutates Sources.
- Running anything heavy on the orchestrator host — route to Rockie compute.

## File map

- `references/method.md` — the proven end-to-end drafting workflow.
- `references/styleguide.md` — banned words, editorial "we", em-dash ban, the
  verbatim DO-NOT list, and the double-blind anonymization grep.
- `references/adversarial-gauntlet.md` — the five-stage review gauntlet.
- `references/detector-gate.md` — the AI-vs-human detector loop.
- `references/lit-review.md` — ranking + the dual-artifact (reading list + index) schema.
- `references/publish.md` — bundle assembly, export, and the Rock-Collection stub.
- `prompts/style-judge.md` — the style-judge subagent prompt.
- `prompts/attack-agent.md` — stage 01: the attacker.
- `prompts/defense-agent.md` — stage 02: the defender.
- `prompts/rebuttal-agent.md` — stage 04: the rebuttal/fix-list author.
- `prompts/format-auditor.md` — stage 05: the format + acceptance auditor.
- `prompts/detector-judge.md` — the fresh no-memory AI-vs-human judge.
- `templates/brief.md` — the brief skeleton.
- `templates/outline.md` — the page-budgeted outline skeleton.
- `templates/figure-gen.py.tmpl` — the single versioned figure script (template, never executed here).
