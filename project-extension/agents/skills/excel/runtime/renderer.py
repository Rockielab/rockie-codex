"""Render validated XLSX workbooks for the Rockie Excel skill."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import xlsxwriter

try:
    from sanitize import sanitize_cell_value
except ImportError:  # pragma: no cover - module execution path
    from .sanitize import sanitize_cell_value

MAX_SHEETS = 20
INVALID_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")


def _cell_value(cell):
    if isinstance(cell, dict):
        kind = cell.get("type")
        value = cell.get("value")
        if kind == "formula":
            return "formula", value
        return "value", sanitize_cell_value(value)
    return "value", sanitize_cell_value(cell)


def _write_row(sheet, row_index: int, values, header_format=None):
    for col_index, cell in enumerate(values):
        kind, value = _cell_value(cell)
        if kind == "formula":
            formula = str(value or "")
            if not formula.startswith("="):
                formula = "=" + formula
            sheet.write_formula(row_index, col_index, formula)
        else:
            sheet.write(row_index, col_index, value, header_format)


def render_workbook(request: dict, output_path: str | Path) -> dict:
    sheets = request.get("sheets") or []
    if not sheets:
        raise ValueError("request.sheets must contain at least one sheet")
    if len(sheets) > MAX_SHEETS:
        raise ValueError(f"workbook sheet count exceeds {MAX_SHEETS}")

    output = Path(output_path)
    if output.suffix.lower() != ".xlsx":
        raise ValueError("output path must end in .xlsx")
    output.parent.mkdir(parents=True, exist_ok=True)

    workbook = xlsxwriter.Workbook(str(output))
    header_format = workbook.add_format({"bold": True, "bg_color": "#FAF5E7"})

    used_names: set[str] = set()
    for index, sheet_spec in enumerate(sheets, start=1):
        requested_name = str(sheet_spec.get("name") or f"Sheet {index}")
        name = _unique_sheet_name(requested_name, used_names)
        sheet = workbook.add_worksheet(name)
        headers = sheet_spec.get("headers") or []
        rows = sheet_spec.get("rows") or []

        if headers:
            _write_row(sheet, 0, headers, header_format)
        start_row = 1 if headers else 0
        for offset, row in enumerate(rows):
            _write_row(sheet, start_row + offset, row)

        if sheet_spec.get("autofilter") and (headers or rows):
            last_row = max(start_row + len(rows) - 1, 0)
            last_col = max(len(headers), *(len(r) for r in rows), 1) - 1
            sheet.autofilter(0, 0, last_row, last_col)
        freeze = sheet_spec.get("freeze_panes")
        if freeze:
            sheet.freeze_panes(freeze)
        widths = sheet_spec.get("widths") or {}
        for col, width in widths.items():
            sheet.set_column(f"{col}:{col}", float(width))
        for chart_spec in sheet_spec.get("charts") or []:
            _add_chart(workbook, sheet, chart_spec, name)

    workbook.close()
    _verify_xlsx(output)
    return {"ok": True, "output_path": str(output), "sheet_count": len(sheets)}


def _unique_sheet_name(raw: str, used: set[str]) -> str:
    cleaned = INVALID_SHEET_CHARS.sub(" ", raw).strip().strip("'") or "Sheet"
    base = cleaned[:31]
    candidate = base
    suffix = 2
    while candidate.lower() in used:
        tail = f" {suffix}"
        candidate = f"{base[:31 - len(tail)]}{tail}"
        suffix += 1
    used.add(candidate.lower())
    return candidate


def _add_chart(workbook, sheet, chart_spec: dict, sheet_name: str) -> None:
    chart_type = chart_spec.get("type") or "column"
    if chart_type not in {"column", "bar", "line"}:
        raise ValueError("chart type must be column, bar, or line")
    categories = chart_spec.get("categories")
    values = chart_spec.get("values")
    if not categories or not values:
        raise ValueError("chart requires categories and values ranges")
    chart = workbook.add_chart({"type": chart_type})
    chart.add_series(
        {
            "name": chart_spec.get("name") or chart_spec.get("title") or "Series",
            "categories": f"='{sheet_name}'!{categories}",
            "values": f"='{sheet_name}'!{values}",
        }
    )
    if chart_spec.get("title"):
        chart.set_title({"name": str(chart_spec["title"])})
    sheet.insert_chart(chart_spec.get("position") or "E2", chart)


def _verify_xlsx(path: Path) -> None:
    try:
        with ZipFile(path) as zf:
            names = set(zf.namelist())
    except BadZipFile as exc:
        raise ValueError(f"output is not a valid xlsx package: {exc}") from exc
    if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
        raise ValueError("output missing required xlsx package parts")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    try:
        request = json.loads(Path(args.input).read_text())
        result = render_workbook(request, args.output)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
