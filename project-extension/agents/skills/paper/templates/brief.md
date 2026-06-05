# Paper brief — <paper short title>

Fill this in before drafting a single section. `/paper-draft` refuses to draft
until the brief exists and every planned numerical claim has an evidence row.
See `references/method.md` § "Stage 0 — the brief".

## Venue

- **Name:** <e.g. ICML 2026 Mechanistic Interpretability Workshop>
- **Format:** <page limit excluding references; template/style file; column count>
- **Review style:** <single-blind | double-blind>  ← double-blind triggers the
  anonymization grep in `references/styleguide.md`
- **Archival:** <archival | non-archival>
- **Deadline:** <date / AOE>

## Thesis (one falsifiable sentence)

> <X cannot do Y because Z, and the positive control that breaks Z bends the curve.>

A thesis you cannot falsify is a press release. State the mechanism and the control
that would falsify it.

## Contribution bullets

1. <contribution 1, quantified>
2. <contribution 2, quantified>
3. <contribution 3, quantified>

Each contribution must be supported by a claim in the evidence map below. Tighten
each against the nearest prior work: say in one clause how it differs.

## Per-section page budget

The budgets must sum to the venue page limit (excluding references and appendix).

| Section | Pages | Purpose |
|---|---|---|
| Introduction | 0.0 | <baseline framing, the phenomenon, contribution bullets> |
| Background | 0.0 | <the recipe, the task, the probe> |
| <Core result> | 0.0 | <observation + theory + corroboration> |
| <Scaling / robustness> | 0.0 | <does depth/scale rescue it?> |
| <Positive control> | 0.0 | <the falsification test> |
| Related work | 0.0 | <distinguish from nearest neighbors BY NAME> |
| Discussion / limitations | 0.0 | <scope, alternatives, future work> |
| Conclusion | 0.0 | <one paragraph> |
| **Total** | **0.0** | must equal the venue limit |

## Claims-to-evidence-to-figure map

One row per numerical claim the paper will make. A claim with no evidence row does
NOT go in the paper. This map is the acceptance gate the format auditor checks.

| Claim id | Claim (with the number) | Evidence source (path + identifier) | Figure / table |
|---|---|---|---|
| C1 | <e.g. four flat rank-k curves, range <= 0.6pp> | <EXPERIMENT_LOG.md line N / SUMMARY.txt> | <fig1_rank_curves.pdf> |
| C2 | <e.g. linear probe AUC 0.673 vs 0.846> | <results table / log line> | <fig2_probe_auc.pdf> |
| C3 | <...> | <...> | <...> |

## Figures to generate

List every figure, each produced by the single versioned script
(`templates/figure-gen.py.tmpl`). Self-contained captions, no placeholders.

- `fig1_<name>.pdf` — <what it shows, what was ablated, the takeaway>
- `fig2_<name>.pdf` — <...>

## Nearest prior work (distinguish by name)

For each nearest competitor, the one-sentence distinction:

- **<Competitor A>:** <how this work differs — different object of study / different
  claim type / different diagnosis>.
- **<Competitor B>:** <...>

If you cannot state the distinction in one sentence, the contribution is not yet
sharp.

## Anonymization surface (double-blind only)

The identity tokens the grep must search for (author name, handle, org, domains).
Build this before drafting so the grep is ready when the bundle is. See
`references/styleguide.md` § anonymization.

- Author/handle/org tokens: <...>
- (URL and acknowledgment patterns are project-independent and always apply.)

## Dual output (if both wanted)

- [ ] Venue submission (anonymized LaTeX, page-limited, compiled on Rockie compute)
- [ ] Public write-up (named, full figures, real reproducibility links)

Both consume this same evidence map; a number fixed in one is fixed in the other.
