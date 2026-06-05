"""Excel cell sanitization helpers."""

from __future__ import annotations

FORMULA_PREFIXES = ("=", "+", "-", "@")


def sanitize_cell_value(value, *, explicit_formula: bool = False):
    """Return a value safe to write to an XLSX cell.

    Spreadsheet apps can treat strings beginning with formula prefixes as
    executable formulas when opened. User-provided strings are forced to text
    unless the caller explicitly marks the cell as a formula.
    """
    if explicit_formula or not isinstance(value, str):
        return value
    if value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value
