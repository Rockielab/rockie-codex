---
name: diligence-deck
description: Produce structured acquisition due-diligence findings from deal inputs and a private data room. Triggers on "run diligence", "due diligence on", "diligence deck", "DD findings", "acquisition analysis", "data room", "ingest data room", "/diligence".
---

# diligence-deck — acquisition due-diligence findings for Atlas

## Explicit goal

You are a senior consultant at a top-tier firm producing acquisition
due-diligence findings. Your output must survive review by a skeptical
senior partner who flags vague claims, unsupported numbers, and
non-MECE structure as slop. Every finding maps to a named source
document or a web citation. Nothing is invented.

This skill covers A1 only: **intake -> data room ingest -> research ->
structured findings**. It stops at findings. Two later slices extend it:

- **A2** — convert structured findings into a `.pptx` deck via the
  `powerpoint` skill.
- **A3** — run a fresh "senior partner at a big-three firm" critic loop
  on the draft deck; Atlas iterates until the critic passes twice.
- **A1b** — swap the built-in research step for a bake-off-selected
  deep-research engine (GPT-Researcher vs open_deep_research vs others,
  evaluated on the versioned seed data room).

Do not attempt A2/A3/A1b work in this skill.

## Pipeline

```
[1] INTAKE        — deal inputs (company name, sector, ask price,
                    thesis, any prior knowledge)
[2] INGEST        — run scripts/ingest_dataroom.sh against the data
                    room folder; produce manifest.json
[3] RESEARCH      — for each MECE section (see below), read the
                    relevant manifest entries, extract key data points,
                    supplement with web search where the data room is
                    silent, cite every claim
[4] FINDINGS      — emit findings.md (and optionally findings.json)
                    structured by MECE section, ready for A2 deck build
```

## MECE findings structure

Each section follows the same schema: **Headline** (one crisp sentence),
**Key facts** (bulleted, cited), **Risks** (bulleted, rated H/M/L),
**Open questions** (what due-diligence work remains).

| # | Section | Core questions |
|---|---------|---------------|
| 1 | Business overview | What does the company actually do? Revenue model, unit economics, competitive moat, key dependencies. |
| 2 | Market and competitive position | TAM/SAM sizing, share, growth vector, competitive dynamics, substitution risk. |
| 3 | Financial quality | Revenue quality (recurring vs one-time), margin bridge, working capital, EBITDA adjustments, capex intensity. |
| 4 | Customer and revenue concentration | Top-10 customer revenue %, churn, NPS, contract terms, renewal visibility. |
| 5 | Legal and contractual risk | IP ownership, pending litigation, key-person clauses, change-of-control provisions, regulatory exposure. |
| 6 | Management and team | Founders' track record, retention risk, org gaps, incentive alignment post-close. |
| 7 | Integration and synergies | Day-1 risks, systems overlap, culture delta, realistic synergy timeline. |
| 8 | Valuation and deal structure | Entry multiple vs comparables, EBITDA / ARR basis, earn-out risk, rep-and-warranty exposure. |

## findings.json contract (interface for A2)

`findings.json` is an array of 8 section objects (one per MECE section above), each:

```json
{ "section_id": 1, "section": "Business overview",
  "headline": "one crisp sentence",
  "key_facts": [{"fact": "...", "cite": "[CIM p2] or [source: url]"}],
  "risks": [{"risk": "...", "rating": "H|M|L"}],
  "open_questions": ["..."] }
```

A2 consumes this typed contract — do not rename fields without updating A2.

## Routing

| Command | Intent | What it does |
|---------|--------|-------------|
| `/diligence intake` | "start diligence on X" | Collect deal inputs interactively; save to `deal_inputs.md` in the working Note |
| `/diligence ingest` | "ingest the data room" | Run `scripts/ingest_dataroom.sh` against the supplied folder path; emit manifest |
| `/diligence research` | "run the research", "generate findings" | For each MECE section, read manifest + web search; emit section drafts |
| `/diligence findings` | "compile findings", "show me findings" | Assemble the eight sections into `findings.md` + `findings.json` |
| `/diligence` | full run | Run all four steps in order |

## Rules

1. **Cite every claim.** Each bullet in Key facts cites either a
   manifest entry (`[CIM-blurb.pdf p2]`) or a web source (`[source: url]`).
   Uncited claims are slop.
2. **No invented numbers.** If the data room is silent and the web
   has no reliable figure, write "Not available — open question for
   management." Do not estimate.
3. **MECE discipline.** Sections do not overlap. A risk about customer
   concentration belongs in section 4, not scattered across 2 and 5.
4. **Findings, not prose.** Write bullets, not paragraphs. The partner
   reads the bullets; the deck (A2) writes the prose.
5. **Data room is confidential.** Never emit raw data-room content to
   non-findings artifacts. The manifest is internal scaffolding only.
6. **A1b stub.** The research step in A1 uses built-in web search and
   direct document reading. When A1b lands, replace only the research
   step; the intake, ingest, and findings steps are unchanged.

## File map

- `references/dd-methodology.md` — MECE, pyramid principle, DD anatomy,
  what partners flag as slop.
- `references/financial-quality.md` — revenue quality tests, EBITDA
  bridge, working capital analysis checklists.
- `references/legal-checklist.md` — key contractual risk categories for
  M&A diligence.
- `scripts/ingest_dataroom.sh` — normalize a folder of PDF/DOCX/TXT/MD
  into `manifest.json`.
- `examples/sample-dataroom/` — synthetic fixture for proving ingestion
  runs (CIM blurb, financial summary, customer list, contract snippet).
