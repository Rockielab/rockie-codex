---
name: excel
description: Triggers on creating, modifying, formatting, analyzing, validating, or exporting real Excel `.xlsx` workbooks while preserving structure and verifying written artifacts.
---

# excel

Use this skill when the user asks for an Excel workbook or an `.xlsx`
artifact, including creating, modifying, formatting, analyzing,
validating, or exporting workbook content. For read-only analysis or
validation requests, inspect the workbook and report findings without
writing a new file unless the user asks for one.

## Core rules

- Produce a real `.xlsx` workbook. Do not rename CSV, TSV, HTML, JSON,
  or plain text files to `.xlsx`.
- Preserve source data. Keep raw inputs available when appropriate,
  such as a `Source Data` or `Raw Data` sheet, and avoid silently
  replacing user-provided values with summaries.
- Use workbook features that fit the task: multiple sheets, formulas,
  number formats, styles, column widths, freeze panes, filters, charts,
  data validation, named ranges, and notes/comments when they materially
  improve usability.
- Keep formulas as formulas unless the user explicitly asks for static
  values.
- When writing a workbook, reopen and verify the finished file before
  reporting it.
- When writing a workbook, report the final artifact path.

## Creating a new workbook

When creating a workbook from scratch:

1. Choose a sheet structure that matches the user's workflow, such as
   raw data, calculations, summary, charts, and validation sheets.
2. Populate headers and sample or source values in the correct types,
   not just display strings.
3. Add formulas, formatting, widths, freeze panes, filters, validation,
   and charts where useful for the workbook's purpose.
4. Preserve the source data used to produce summaries or charts unless
   the user asks for a presentation-only workbook.
5. Save as `.xlsx` and verify by reopening the file.

## Modifying an existing workbook

When editing an existing `.xlsx`:

1. Open the existing workbook and inspect workbook metadata, sheet
   names, dimensions, relevant ranges, formulas, styles, tables, charts,
   validation rules, and target cells before making changes.
2. Make targeted edits only. Preserve untouched cells, sheets, formulas,
   styles, widths, panes, filters, charts, validation rules, workbook
   properties, and source data where possible.
3. Avoid destructive rebuilds. Do not recreate the workbook from scratch
   unless the file is corrupt or the user explicitly requested a full
   rebuild.
4. If a requested change conflicts with existing workbook structure,
   explain the tradeoff and choose the least destructive edit that
   satisfies the request.
5. Default to a clearly named edited copy. Overwrite the original only
   when the user explicitly asks for that or confirms the overwrite.

## Analyzing or validating a workbook

For read-only workbook analysis:

1. Open the workbook and inspect only the sheets, ranges, formulas,
   styles, validation rules, charts, or metadata needed for the request.
2. Do not save, normalize, or rebuild the workbook as a side effect of
   inspection.
3. Report findings with sheet names, cell/range references, and any
   assumptions or parser limitations that affect confidence.

## Verification

After writing the `.xlsx`, reopen it with an Excel-capable parser or by
inspecting the ZIP/XML package when no dependency is available. Verify:

- Expected workbook and worksheet names.
- Sheet dimensions and important ranges.
- Target cells changed as requested.
- Formulas are present as formula XML or formulas, not only cached
  values.
- Styles, number formats, widths, freeze panes, filters, charts, and
  validation rules that matter to the task.
- Sample values from source data and calculated or summarized outputs.

If verification fails, fix the workbook and verify again before
responding.
