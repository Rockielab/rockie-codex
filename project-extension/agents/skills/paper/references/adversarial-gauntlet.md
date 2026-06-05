# adversarial-gauntlet — the five-stage hostile review

The gauntlet does the most work. It runs a complete draft through five
fresh-context subagents in a fixed order, each producing a numbered artifact, and
refuses to terminate while any attack rated CRITICAL is unresolved. The reference
ICML submission: 20 attacks (2 CRITICAL), every one dispositioned by the defense,
a 20-item ordered fix list from the rebuttal, every number confirmed against
evidence by the format audit.

The gauntlet is not a rubber stamp. An attack agent that returns "looks good" has
failed its job. The bar is a domain expert who wants to reject the paper.

Each stage runs as a fresh-context subagent dispatched with its prompt file plus
the draft and the prior-stage artifacts it needs — see `SKILL.md` § "How roles are
run". A runner with no subagent dispatch runs each stage as a separate fresh
reasoning pass with a hard context reset between stages and rounds (the
**degraded single-process mode** in that same section); the stage order, the
numbered artifacts, and the CRITICAL-blocks-termination rule below are identical
either way.

## Stage order (fixed) and the numbered artifacts

The stages run in this exact order. Note the artifact numbering: the rebuttal is
artifact 04 and the style critique is artifact 03, but the rebuttal runs **before**
the style critique. The numbers are the artifact's identity, not its run position.

| Run order | Stage | Artifact | Prompt | Produces |
|---|---|---|---|---|
| 1 | Attack | `01_attack_report.md` | `prompts/attack-agent.md` | Numbered attacks, sorted by severity, each with a defuse path |
| 2 | Defense | `02_defense_report.md` | `prompts/defense-agent.md` | One disposition per attack: DEFEND / PARTIAL / CONCEDE+FIX |
| 3 | Rebuttal | `04_rebuttal_report.md` | `prompts/rebuttal-agent.md` | Ordered fix list + a verdict table; final dispositions |
| 4 | Style | `03_style_critique.md` | `prompts/style-judge.md` | Line-level style violations against `references/styleguide.md` |
| 5 | Format | `05_format_audit.md` | `prompts/format-auditor.md` | Cross-ref / citation / number-to-evidence / anonymization audit |

Each of the five artifacts persists as its own lab Note (`note_type: "ai"`, the
artifact name in the title or `metadata`) so the round history is reconstructable.
The persistence call is `POST /api/notes`; see `references/publish.md` for the route,
body schema, and auth. These Notes are outputs, never a mutation of a Source.

## The termination rule (hard)

**The gauntlet SHALL NOT terminate while any attack rated CRITICAL is unresolved.**

"Resolved" means one of:

- The defense rated the attack DEFEND and the rebuttal confirmed the defense holds
  as-is (the attack was wrong on a factual or technical premise), OR
- The rebuttal emitted a fix for the attack, the fix was applied to the draft, and
  the gauntlet was re-run on the affected claims with the attack no longer CRITICAL.

A CRITICAL attack that is merely "acknowledged" or "deferred to camera-ready" is
NOT resolved. The reference paper's two CRITICAL attacks (A1 the unfalsifiable
post-hoc pivot, A2 the allegedly-broken SVD control) were each driven to
resolution: A2 by a factual correction (the code used the stable `svdvals`, not
the unstable `svd`), A1 by a surgical rewrite that converted an unfalsifiable
claim into a falsifiable refined hypothesis with an explicit falsifier. Either
path closes a CRITICAL; nothing else does.

SERIOUS and MINOR attacks may be resolved by a fix or accepted as a scoped
limitation that the rebuttal records; they do not block termination, but the
rebuttal's verdict table must account for each.

## The stages (each prompt owns its own output shape)

Each stage's prompt file defines what that agent emits; below is only the
orchestration each stage adds. Do not re-describe the prompts here.

- **Stage 1 — attack (`01_attack_report.md`, `prompts/attack-agent.md`).** Numbered
  attacks sorted CRITICAL-first, each with a severity, a type, and a concrete defuse
  path.
- **Stage 2 — defense (`02_defense_report.md`, `prompts/defense-agent.md`).** One
  disposition per attack in the same order (DEFEND / PARTIAL / CONCEDE+FIX). The
  reference defense rated 7 DEFEND, 8 PARTIAL, 5 CONCEDE+FIX across 20 attacks.
- **Stage 3 — rebuttal (`04_rebuttal_report.md`, `prompts/rebuttal-agent.md`).** The
  ordered fix list (CRITICAL first) plus a verdict table — the operational output of
  the gauntlet. The writer then applies the fixes and the gauntlet re-runs (see
  "Re-run discipline" below).
- **Stage 4 — style (`03_style_critique.md`, `prompts/style-judge.md`).** The same
  style judge as the pre-gauntlet pass, re-run because the rebuttal fixes introduce
  new prose. The draft must reach zero violations against `references/styleguide.md`.
- **Stage 5 — format audit (`05_format_audit.md`, `prompts/format-auditor.md`).** The
  acceptance gate: every numerical claim maps to an evidence row, every cross-ref and
  citation resolves, no placeholders, double-blind anonymization clean. A critical
  format finding (broken ref, unmatched number, identity leak) blocks the gauntlet
  exactly as an unresolved CRITICAL attack does.

## Re-run discipline

The gauntlet is iterative. The typical loop:

1. Attack → defense → rebuttal produces the fix list.
2. Writer applies the fix list in severity order.
3. Style + format audit on the revised draft.
4. If any CRITICAL attack is still unresolved, or any critical format finding
   stands, re-run the affected claims through attack/defense/rebuttal.
5. Terminate only when no CRITICAL attack and no critical format finding remain.

Record each round's artifacts (numbered, with a round suffix if needed) as lab
Notes. When the gauntlet terminates clean, the draft proceeds to the detector gate
(`references/detector-gate.md`) — which runs **only** after the gauntlet and the
style judge both pass.
