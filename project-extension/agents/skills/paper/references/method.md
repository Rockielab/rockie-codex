# method — the proven end-to-end drafting workflow

This is the spine of `/paper-draft`. It reproduces the method that produced a
real ICML Mechanistic-Interpretability-workshop submission (a negative-result
paper on rank-blindness in matrix-valued latent chain-of-thought). The method is
not a suggestion: a paper that skips a stage gets caught by the gauntlet, the
style judge, or the detector gate, and you waste the round. Run the stages in
order.

The governing principle: **ordinary LLM drafting produces filler.** A first draft
reads fluent and says little; its numbers are vague, its captions defer to a
figure that does not exist, and its voice is generic. The job of this method is
to make the writing earn every sentence — a real thesis, a page budget that
forces cuts, every number tied to evidence, and a hostile review that does real
work rather than rubber-stamping.

## Stage 0 — the brief (refuse to draft without it)

Fill `templates/brief.md` first. The brief is the contract for the whole draft.
It carries:

- **Venue.** Name it. The venue sets format (page limit, template), review style
  (single vs double blind), and archival status. A double-blind venue triggers
  the anonymization grep in `references/styleguide.md`.
- **Thesis.** One sentence, falsifiable. "X cannot do Y because Z, and we show a
  positive control that breaks Z." A thesis you cannot falsify is a press
  release, not a paper. The reference paper's thesis: "the gradient cannot see
  rank through a flatten-then-project readout because the Jacobian is constant in
  Z; a nonlinear-in-Z readout is the positive control."
- **Per-section page budget.** Assign pages before writing. The budget forces the
  paper to spend its space on the claim, not on throat-clearing. Example budget
  for an 8-page paper: intro 0.75, background 0.75, the core result 2, the
  scaling section 1.5, the positive control 1.5, related work 0.5, discussion and
  limitations 0.5, conclusion 0.25.
- **Claims-to-evidence-to-figure map.** One row per numerical claim the paper will
  make. Each row names: the claim, the exact evidence source (a log line, a
  results table, a SUMMARY file — by path and identifier), and the figure or
  table that displays it. **A claim with no evidence row does not go in the
  paper.** This map is the acceptance gate the format auditor checks at stage 05.

Do not draft a single section until the brief exists and every planned numerical
claim has an evidence row. If the lab does not yet have the evidence for a claim
the thesis needs, that is a finding — flag it and narrow the thesis, do not write
the claim and backfill later.

## Stage 1 — the outline (page-budgeted)

Fill `templates/outline.md`. One row per section: the section, its page budget
from the brief, the claims it carries (by id from the brief's map), and the
figures it shows. The outline is where you catch a paper that is over budget
before you write 8 pages of prose you then have to cut.

Sanity checks on the outline:

- The page budgets sum to the venue limit (excluding references and appendix).
- Every claim in the brief's map appears in exactly one section.
- Related work distinguishes this paper from its nearest neighbors **by name**.
  The reference paper had to distinguish itself from SIM-CoT (different diagnosis)
  and from two February-2026 linear-attention rank papers (different object of
  study and different claim type). If you cannot say in one sentence how this work
  differs from the closest prior work, the contribution is not yet sharp.

## Stage 2 — section drafting (one file per section)

Write one file per section. Discipline for each section:

- **Every numerical claim cites its evidence row — in one concrete format.** When
  you write a number, place an HTML comment naming the brief's evidence row
  **immediately after the claim**, in exactly this form:
  `<!-- evidence: <table/row id> -->`. The `<table/row id>` is the identifier of
  the row in the brief's claims-to-evidence map (e.g. `results-table:auc-codi`).
  For example:

  ```
  Matrix-CODI reaches AUC 0.673 <!-- evidence: results-table:auc-codi --> on the
  held-out split, within seed noise of the SFT baseline.
  ```

  This is the **one** mechanism — not a prose aside, not a footnote, not a bare
  citation. The comment is invisible in the rendered paper but greppable in the
  source, and the format auditor at stage 05 greps for exactly this token to
  confirm every number maps to a row (`prompts/format-auditor.md`). A number with
  no `<!-- evidence: ... -->` comment immediately after it fails the audit.
- **No placeholder language.** No "TODO", no "pending", no "will be added in the
  appendix", no "results forthcoming". If a result is not ready, the claim that
  depends on it is not ready; cut it or demote it to clearly-flagged future work.
  The reference paper's depth sweep had three of four data points pending; the fix
  was to demote it to a one-paragraph "preliminary, deferred to camera-ready",
  not to write a four-point trend from one point.
- **Voice from the start.** Editorial "we", no first person "I", no contractions,
  no banned words. Writing in the right voice from the first draft is far cheaper
  than line-editing it in later. See `references/styleguide.md`.
- **Scope claims to the evidence.** "Matrix-CODI underperforms at every scale"
  with two data points inside seed noise is an overclaim; "does not exceed vanilla
  SFT at any tested scale, gaps within seed noise" is the honest version. The
  gauntlet will catch every overclaim; pre-empt it.

## Stage 3 — figures (one versioned script, self-contained captions)

Generate every figure from a single versioned script, `templates/figure-gen.py.tmpl`
filled in. One script means the figures are reproducible and a reviewer can trace
each panel to the code that made it. Run the script on Rockie compute (the
`/experiment` path), never on the orchestrator host.

Caption discipline: every caption is **self-contained**. A reader who reads only
the caption knows what the panel shows, what was ablated or measured, and what the
takeaway is — without reading the body. No caption defers to text that "will be
added". The reference paper's format audit flagged a caption that said "will be
added in the appendix when the re-runs complete" as a blocking issue.

## Stage 4 — the style judge

Before the gauntlet, dispatch a fresh-context style judge (`prompts/style-judge.md`)
against `references/styleguide.md`. It flags every violation the styleguide names.
The draft does not enter the gauntlet until the judge reports zero violations: style
is cheap to fix and expensive to leave, so clear it before the adversarial passes.

(Every review role in this method — this style judge, the five gauntlet stages, and
each detector judge — runs as a fresh-context subagent; see `SKILL.md` § "How roles
are run".)

## Stage 5 — the adversarial gauntlet

Run the five-stage gauntlet in `references/adversarial-gauntlet.md` (attack →
defense → rebuttal → style → format). It does not terminate while any CRITICAL
attack is unresolved; the rebuttal emits an ordered fix list, which you apply before
re-running on the affected claims. This stage does the most work.

## Stage 6 — the detector gate

Only after the gauntlet and the style judge both pass, run the detector gate in
`references/detector-gate.md`. At least two fresh, no-memory judges classify the
draft AI-written vs human-written; each rejecting judge cites specific tells. Apply
the cited fixes and re-run. The gate terminates only on two consecutive rounds of
all-judges "100% human". Then mark the draft accept-ready.

## Dual output (when the venue plus a public write-up are both wanted)

The reference method produced two outputs from one body of evidence: the formal
venue submission (anonymized LaTeX) and a public web write-up (named, with full
charts and reproducibility links). If the user wants both:

- The **venue submission** is anonymized for double-blind: no names, handles, org,
  or URLs (use an anonymized code link). Target the venue's page limit. Compile on
  Rockie compute.
- The **public write-up** uses editorial "we" (not "I"), shows the full figures,
  and links real reproducibility artifacts (scripts, logs). It is not anonymized.
- Both consume the same claims-to-evidence map, so every number in both traces to
  the same evidence row.

Keep the two in sync: a number fixed in one is fixed in the other.

## Acceptance criteria for an accept-ready draft

A draft is accept-ready only when all of these hold:

1. The brief exists and every numerical claim in the draft maps to an evidence row.
2. Every figure comes from the versioned script; every caption is self-contained.
3. The style judge reports zero violations.
4. The gauntlet terminated with no unresolved CRITICAL attack, and the rebuttal's
   fix list is fully applied.
5. The format/acceptance audit confirms every number maps to evidence and every
   citation and figure reference resolves.
6. The detector gate terminated on two consecutive rounds of all-judges "100%
   human".
7. For a double-blind venue, the anonymization grep returns zero identity leaks.

Anything short of all seven is a draft in progress, not accept-ready. `/publish`
refuses a draft that is not accept-ready.

## Where each artifact persists

Every output this method produces is a lab Note (`POST /api/notes`; the bundle adds
a downloadable artifact). See `references/publish.md` for the route, body schema,
and auth.

- The two lit-review artifacts (reading list, machine index) — one Note each
  (`references/lit-review.md`).
- The five gauntlet artifacts (`01`–`05`) — one Note each, `note_type: "ai"`
  (`references/adversarial-gauntlet.md`).
- The detector history (per-round verdicts, or the cap-hit residual-tells Note) — a
  Note (`references/detector-gate.md`).
- The final published bundle — a Note **plus** a downloadable artifact
  (`references/publish.md`).

Sources are read-only inputs; all of the above are outputs. Never write an output
back over a Source.

### Offline / local-only fallback (no tenant API reachable)

The `POST /api/notes` path above is the primary persistence and is used whenever
the tenant API is reachable. A local or offline run may have **no tenant API** —
no `$ROCKIELAB_API_URL`, a disconnected runner, a bare local checkout. The
method must not lose its artifacts in that case.

When the Notes API is unreachable, write each artifact to a file in a single
**run directory** instead: `paper-run/<artifact>.md` (create `paper-run/` once at
the start of the draft). For example:

- `paper-run/brief.md`, `paper-run/outline.md`, the per-section draft files
- `paper-run/01_attack_report.md` … `paper-run/05_format_audit.md` (the gauntlet)
- `paper-run/detector-history.md` (per-round verdicts, or the cap-hit tells)
- `paper-run/bundle/` (the assembled bundle, when `/publish` runs offline)

This is a fallback for durability, not a replacement: **Note-persistence happens
when connected.** When the run later has tenant access, push the run-directory
artifacts through `POST /api/notes` (and the bundle through the artifact emitter)
so they land as lab Notes — `references/publish.md`. Prefer the API whenever it is
reachable; fall back to `paper-run/` only when it is not.
