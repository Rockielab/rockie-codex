# detector-gate — the final AI-vs-human loop

The detector gate is the last filter before a draft is marked accept-ready. After
the gauntlet has hardened the claims and the style judge has driven prose violations
to zero, the gate answers one question: does this read like a human wrote it, or does
it still carry the tells of machine-generated text? A domain expert who senses LLM
slop stops trusting the paper regardless of how sound the claims are.

## Precondition (hard)

The detector gate runs **only after the gauntlet and the style judge both pass.**

- The gauntlet must have terminated with no unresolved CRITICAL attack and no
  critical format finding (`references/adversarial-gauntlet.md`).
- The style judge must report zero violations against `references/styleguide.md`.

Running the detector gate earlier wastes rounds: the gauntlet's rebuttal fixes
rewrite prose, and the style judge catches the mechanical tells (banned words,
contractions, em-dashes) that the detector would otherwise flag as low-hanging
fruit. The detector gate is for the residual, harder tells that survive a clean
style pass — rhythm, structure, hedging patterns, over-balanced sentences,
generic transitions, "summary of a summary" paragraphs.

## The panel

At least **two** fresh, no-memory judges (`prompts/detector-judge.md`) classify the
draft independently. Each judge:

- Sees only the draft (or a section of it), with no knowledge that it was
  machine-assisted and no memory of prior rounds. A judge that knows the answer is
  looked for is biased; a fresh judge gives an honest read.
- Returns a single classification — **AI-written** or **human-written** — with a
  confidence, framed as a percentage-human read ("100% human", "70% human, 30%
  AI", etc.).
- If it does not return "100% human", it **cites the specific tells**: the exact
  sentences or patterns that read as machine-generated, and why. A rejecting judge
  that cannot name a tell has not done its job.

Use two judges minimum; three is better for a borderline draft. They run
independently (no shared thread) so their tells do not converge. Each judge is a
fresh-context subagent dispatched with only `prompts/detector-judge.md` and the
prose (see `SKILL.md` § "How roles are run") — "fresh" is what makes the second
clean round an independent confirmation, not the same panel agreeing with itself.

**Degraded mode (no subagent dispatch).** When the runner cannot spawn separate
processes for the judges, the panel cannot be *truly* independent. Simulate the
independence via **role-reset**: run each judge as a separate fresh reasoning
pass that sees only the prose plus `prompts/detector-judge.md`, with a hard
context reset between judges and between rounds, carrying no memory of any prior
verdict (`SKILL.md` § "How roles are run" → degraded single-process mode). The
"fresh panel each round" requirement becomes "reset the role each round". This
is **weaker** than separate processes — a single context can leak a tell it
already waved through, so two clean rounds in single-process mode is a softer
signal than two clean rounds across real subagents; label the verdicts
`single-process` and read them accordingly. The `MAX_ROUNDS = 6` cap and the
cap-hit escape (below) apply unchanged.

## The termination rule (hard)

The gate **terminates only on two consecutive rounds in which every judge returns
"100% human".** One clean round is not enough — a single round of all-clean can be
luck or a soft panel. Two consecutive clean rounds, on a panel of fresh judges, is
the bar.

The loop (bounded by `MAX_ROUNDS = 6`, see the next section):

1. Run the panel on the current draft. Increment the round counter; record this
   round's worst judge score so the best-scoring draft is always known.
2. If any judge classifies the draft as AI-written (anything short of "100%
   human"), collect every cited tell, apply fixes that remove those tells, and go
   back to step 1. This counts as a non-clean round; the consecutive-clean counter
   resets to zero.
3. If every judge returns "100% human", increment the consecutive-clean counter.
   - Counter = 1: run one more round (step 1) with a **fresh** panel (new judges,
     no memory of the prior round).
   - Counter = 2: the gate passes.
4. If the round counter reaches `MAX_ROUNDS` without the gate having passed, stop
   and take the cap-hit hand-off (next section). Never run a seventh round.

## The iteration cap and escape (hard — the gate never blocks indefinitely)

Two consecutive clean rounds is the pass bar, but a draft that never reaches it
must not loop forever. The gate runs **at most six rounds** (`MAX_ROUNDS = 6`). If
six rounds pass without two *consecutive* clean rounds, the gate **stops** and
hands off — it does not run a seventh round and it does not silently accept.

The cap-hit hand-off:

1. Keep, across all rounds, the **best-scoring draft** — the revision whose worst
   judge gave the highest percentage-human read (e.g. a round that scored "95%
   human, 92% human" beats one that scored "100% human, 70% human", because the
   gate's bar is the *worst* judge in a round).
2. When round six finishes without two consecutive clean rounds, surface that
   best-scoring draft as the output, together with a **Note** that lists the
   remaining cited tells from that best round (the exact sentences/patterns the
   judges still flagged, verbatim from their reports) so a human can act on them.
3. Set the gate status to **`detector-cap-hit — human review needed`**. This status
   is distinct from `accept-ready`: a cap-hit draft is NOT accept-ready, and
   `/publish` refuses it (`references/publish.md` requires the detector gate to have
   *passed*, not merely terminated).

The detector is a quality signal, not a gate that can trap a paper. A draft that
genuinely cannot reach two consecutive clean rounds needs a human's judgment —
surface it with the evidence and stop, rather than burning unbounded rounds.

## Applying the cited fixes

When a judge cites a tell, the fix is a real rewrite, not a word swap. The residual
tell categories and their rewrites are in `prompts/detector-judge.md` § "What to
listen for" — break over-balanced symmetry, cut generic transitions, unstack hedges,
delete summary-of-a-summary paragraphs, vary featureless rhythm. Apply the fixes,
then re-run the panel. Do not argue with a tell; if a fresh judge read it as
machine-generated, a reviewer might too.

## Output and hand-off

Each round's judge verdicts persist as a lab Note (the draft's detector history) via
`POST /api/notes` (see `references/publish.md`), so the iteration is visible — a
reviewer of the process can see the draft went from "70% human, tells cited" to two
consecutive "100% human" rounds, or to a cap-hit with the residual tells recorded.
This is the evidence that the detector loop did real work and was not a rubber stamp.

The gate terminates in exactly one of two states:

- **Pass** — two consecutive clean rounds. Mark the draft **accept-ready**. Only an
  accept-ready draft proceeds to `/publish` (`references/publish.md`).
- **Cap hit** — `MAX_ROUNDS` reached without two consecutive clean rounds. Mark the
  status `detector-cap-hit — human review needed`, surface the best-scoring draft and
  the residual-tells Note, and stop. `/publish` refuses a cap-hit draft exactly as it
  refuses any draft that is not accept-ready.

The persisted Note records which terminal state the gate reached, so the hand-off is
auditable.
