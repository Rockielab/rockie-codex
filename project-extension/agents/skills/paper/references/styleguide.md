# styleguide — the hard style contract

This is the contract the style judge (`prompts/style-judge.md`) enforces, and the
voice every section is written in from the first draft. It is deliberately strict.
The banned-word list and the universal voice/DO-NOT rules below are **verbatim** — do
not soften, reorder, or "improve" them. A draft fails the style judge on a single
hit. (The project-specific bans in the DO-NOT section are EXAMPLES from the reference
project and ARE meant to be substituted per project — they are clearly labeled as
such where they appear.)

The reason for strictness: the words and tics below are the fingerprints of
generic LLM prose. A domain expert reads "interestingly, the gradient really just
cannot see rank" and stops trusting the paper. Strip the fingerprints and the
writing reads like a careful human wrote it, which is the bar the detector gate
(`references/detector-gate.md`) measures.

## Banned words (verbatim — fail on any hit)

The following words are banned anywhere in the prose (body, abstract, captions,
section titles). This list is verbatim and exhaustive for the hard-fail check:

```
honest
actually
really
just
clearly
obviously
interestingly
nicely
remarkable
surprising
unfortunately
essentially
wildly
literally
parsimonious
cleanest
sharpest
```

Notes on the banned words:

- These are hedges, intensifiers, and self-congratulation. "Clearly" and
  "obviously" tell the reader the thing is obvious instead of showing it.
  "Remarkable", "surprising", "cleanest", "sharpest" grade your own work.
  "Just", "really", "actually" are filler. Cut them; the sentence is stronger.
- The check is case-insensitive and matches whole words. "Just" is banned;
  "adjust" and "justify" are fine (the banned token is the standalone word).
- If a banned word is genuinely load-bearing as a technical term (rare), it must
  be quoted as a named object, not used as prose — and the style judge will ask
  you to justify it.

## Voice rules

1. **Editorial "we", never "I".** Research-paper convention. Even a solo author
   writes "we show", "we report". First-person singular "I" is a hard fail.
2. **No first-person-about-the-author / narrative-process phrasing.** Do not
   narrate your own research process in the prose: not "our original hypothesis",
   not "we report a negative result with a mechanism", not "the paper's sharpest
   claim". Write the finding, not the story of finding it. The reference paper's
   style critique flagged exactly these narrative-process slips.
3. **No contractions.** "do not", not "don't"; "cannot", not "can't"; "it is",
   not "it's". A contraction is a hard fail.
4. **No em-dash as a conversational pause.** The em-dash used as a dramatic pause
   ("the curve is flat — every time") is a blog tic. Use a comma, a colon, a
   semicolon, or two sentences. (An em-dash inside a properly punctuated
   parenthetical aside is tolerated, but prefer commas.)
5. **No rhetorical-question section headings.** Headings are noun phrases that
   name the section's content ("The Flatten-Then-Project Readout Is Rank-Blind"),
   not questions ("Does the Gradient See Rank?").
6. **Self-contained captions.** Every figure and table caption is complete on its
   own: it names the subtask, the method or ablation, and the takeaway, and it
   does not defer to body text or to content that "will be added". A caption that
   says "pending", "TODO", or "will be added in the appendix" is a hard fail.
7. **Passive voice for mechanisms, active "we" for findings.** Describe the
   mechanism in plain declaratives; attribute the findings to "we".
8. **Quantify claims.** "Matrix-CODI underperforms" is weak; "matrix-CODI is
   1.3pp below vanilla SFT, within the three-seed standard deviation of 1.2pp" is
   a claim a reviewer can check. Scope every claim to its evidence.

## Abstract length

The abstract is **200 to 230 words**. Shorter reads thin; longer reads padded.
Count the words and trim to the band. The reference paper's style critique flagged
a 288-word abstract that had to come down to the band. The problem-method-result-
significance shape (what is the question, what did we do, what did we find, why it
matters) fits the band comfortably.

## The DO-NOT list

Two layers: the universal voice rules apply to every paper; the project-specific
bans are EXAMPLES from the reference brief, replaced per project.

### Universal DO-NOT rules (apply to every paper)

- Use editorial "we" (research-paper convention), NOT first-person "I".
- Do not narrate the experimental apparatus in a way that brags ("we ran N
  experiments", "our large GPU fleet"). State what the experiment showed.
- Do not put cost, funding source, or compute-scale boasts in the prose.
- For a double-blind venue, do not include author names, institution,
  acknowledgments, or a non-anonymous code link (use an anonymous code host such as
  `https://anonymous.4open.science/`).

### Project-specific bans — EXAMPLES (verbatim from the reference PAPER_WRITER_BRIEF.md)

The matrix-CODI project's bans, shown as concrete instances of the universal rules.
For the reference project, carry them to the letter; for any other project, replace
them with that project's equivalents (its forbidden words, real GPU count, funding
language). Do NOT carry these exact strings into an unrelated paper.

```
# EXAMPLES — reference (matrix-CODI) project only; substitute per project
- Do NOT include the word "audit" anywhere
- Do NOT brag about experiment counts
- Do NOT mention compute budget in dollars or H100-hours
- Do NOT say "we ran 8×H100 pods" — this project uses 1×H100
- Do NOT mention "self-funded"
- Anonymous code link: use https://anonymous.4open.science/ — do NOT include
  the actual GitHub URL in the submission
```

## Anonymization identity-leak grep (double-blind venues)

For any double-blind venue, the draft (and every figure, table, and code link in
the submission bundle) must pass an identity-leak grep before it can be submitted.
The grep searches for names, handles, organizations, and URLs that would
de-anonymize the author.

Run a case-insensitive search across the whole submission for, at minimum:

```
# Author / handle / org identifiers (extend per project)
larson
samtlarson
saml212
pebble
pebbleml
rockie
# de-anonymizing URL / host patterns
github.com/
huggingface.co/
.pebbleml.com
# acknowledgment / funding language
acknowledg
self-funded
funded by
```

Expected result for an anonymized submission: **zero matches.** Any match is a
blocking identity leak — fix it before submission. The format auditor
(`prompts/format-auditor.md`) runs this grep as part of stage 05 for double-blind
venues; the public (named) write-up is exempt because it is intentionally not
anonymized.

The author/handle/org tokens above are the reference project's identity surface;
replace them per project. The URL and acknowledgment patterns are project-independent
and always apply. Build the token list before the draft so the grep is ready when the
bundle is.

## What a clean pass looks like

When the style judge passes, the draft has: editorial "we" throughout, zero banned
words, zero contractions, zero em-dash-as-pause, noun-phrase headings,
self-contained captions, a 200-to-230-word abstract, no apparatus bragging, and
(for double-blind) zero identity-leak grep matches. Only then does the draft enter
or re-enter the gauntlet.
