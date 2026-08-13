#!/usr/bin/env python3
"""Shared CSV safety helpers used by history and batch exports."""

from __future__ import annotations

# Leading characters that make spreadsheet apps (Excel, Google Sheets, LibreOffice)
# interpret a cell as a formula rather than literal text.
_FORMULA_PREFIXES = ("=", "+", "-", "@")


def safe_csv_text(value: object) -> str:
    """Return value as text that a spreadsheet will not execute as a formula.

    Values whose first non-whitespace character is one of =, +, - or @
    are prefixed with a single quote, so untrusted song metadata can never
    inject a spreadsheet formula through an exported CSV.
    """
    text = str(value or "")
    candidate = text.lstrip(" \t\r\n")
    if candidate.startswith(_FORMULA_PREFIXES):
        return "'" + text
    return text


__all__ = ["safe_csv_text"]
