# lit-review — ranking and the dual-artifact schema

`/lit-review` builds a lab's literature foundation. It takes a candidate corpus
(sources the user supplies, plus any the agent finds through search), ranks it,
and persists **two** Notes: a human-readable curated reading list and a
machine-readable index. The split matters: a person joining the lab reads the
reading list to orient; a later drafting agent consumes the index directly to
write the related-work section without re-reviewing everything. Both are Notes
(outputs); the corpus stays as Sources (inputs).

## Inputs

- The candidate corpus: papers the user names, papers already in the lab as
  Sources, and papers the agent finds by search on the topic.
- The lab's thesis or research question, if one exists (from a brief or a prior
  session). Ranking is relative to the question the lab is trying to answer.

## Ranking

Rank every candidate on four axes, then sort. Do not keep everything — a reading
list that keeps 80 papers is not curated. Keep the items that earn their place on:

1. **Relevance.** How directly does the paper bear on the lab's thesis or question?
   A paper that is the nearest prior work, a direct competitor on the mechanism, or
   the source of the phenomenon ranks highest. Tangential background ranks low.
2. **Recency.** Newer work that the field will expect the paper to engage ranks
   higher, especially direct competitors published in the last few months. (The
   reference project had to engage two February-2026 linear-attention rank papers
   because a reviewer would expect it.) Recency does not override relevance — a
   foundational older paper still ranks high if it is load-bearing.
3. **Citation depth.** How heavily cited / how central to the subfield. A
   well-cited paper is one the related-work section is expected to position against.
4. **Replication status.** Has the result been replicated or is it a single
   unreplicated claim? A replicated result is safer to build on; an unreplicated
   claim is worth engaging but should be flagged as such. Note when the lab's own
   work fails to replicate a cited baseline (the reference project's vanilla SFT
   was 15pp below the cited number — that gap is itself a finding the lit review
   surfaces).

For each kept item, annotate a one-line **"why this matters"** — the single reason
it is on the list (nearest prior work / direct competitor on the mechanism / source
of the phenomenon / the metric definition we adopt / the methodological caveat we
must cite). This one-liner is what a person scanning the reading list reads first.

## Artifact 1 — the human-readable reading list (a Note)

A curated, ranked Markdown reading list for a person. For each kept item:

- Title, authors, venue, year, and a stable identifier (arXiv ID / DOI).
- The one-line "why this matters".
- A short (2-4 sentence) summary in plain language: what the paper claims and how
  it relates to the lab's question.
- A flag for replication status and any known caveat (unreplicated, contested,
  superseded, "we could not match their baseline").

Group by role: nearest prior work, direct competitors, foundational background,
methodological references. A person reads this top-to-bottom and knows the
landscape.

## Artifact 2 — the machine-readable index (a Note)

A structured index a later drafting agent consumes directly. One record per kept
item, in a stable schema (JSON or YAML in the Note body). Each record has, at
minimum:

```yaml
- id: <stable identifier, e.g. arXiv:2602.04852>
  title: <title>
  authors: <authors>
  venue: <venue>
  year: <year>
  abstract: <the paper's abstract, verbatim or a faithful condensation>
  claimed_result_vector:        # the paper's claims as discrete, checkable items
    - <claim 1, with its quantified result if any>
    - <claim 2>
  open_questions:               # what the paper leaves unresolved / a reviewer would ask
    - <open question 1>
  dependencies:                 # other index ids this paper builds on or competes with
    - <id of a paper this one extends>
    - <id of a paper this one contradicts>
  relation_to_thesis: <one line: nearest-prior | competitor-mechanism | source-of-phenomenon | metric-source | method-caveat>
  replication_status: <replicated | unreplicated | contested | could-not-match>
```

The `claimed_result_vector`, `open_questions`, and `dependencies` fields are what
make the index useful to a drafting agent: it can position the lab's work against
each competitor's specific claim, anticipate the open questions a reviewer will
raise, and build the dependency graph of the subfield (who extends whom, who
contradicts whom). The reference project's related-work section had to distinguish
its work from competitors on **two axes** (different object of study, different
claim type) — the index's `claimed_result_vector` and `relation_to_thesis` fields
are exactly what makes that distinction writable without re-reading every PDF.

## Both persist as lab Notes

Persist **two** Notes via `POST /api/notes` (see `references/publish.md` for the
route, `NoteCreate` body schema, and auth): the human reading list (`note_type:
"human"`, since a person curates it) and the machine-readable index (the YAML index
in `content`, with a `metadata` schema marker). Never write either as a Source —
Sources are read-only inputs; these are outputs. A fresh agent that joins the lab
later reads the index Note and inherits the literature foundation; it does not
re-review the corpus.

## The draft consumes the index

When `/paper-draft` writes the related-work section (method stage 1-2), it reads
the index Note directly as the basis for related work. The drafting agent:

- Uses each record's `relation_to_thesis` and `claimed_result_vector` to write the
  one-sentence distinction from each competitor.
- Uses `dependencies` to order the related-work narrative (foundational →
  competitors → caveats).
- Uses `open_questions` to anticipate reviewer attacks the gauntlet will raise.

This is the hand-off the dual-artifact design exists for: the lit review is done
once and the draft inherits it, rather than the drafting agent re-deriving the
landscape under deadline.
