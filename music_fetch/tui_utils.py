#!/usr/bin/env python3
"""Small terminal UI helpers built on prompt_toolkit."""

from __future__ import annotations

import shutil
from typing import Optional, Sequence

from prompt_toolkit import ANSI, prompt, print_formatted_text
from prompt_toolkit.shortcuts import checkboxlist_dialog
from wcwidth import wcswidth

COLOR_RESET = "\x1b[0m"
COLOR_RED = "\x1b[31m"
COLOR_GREEN = "\x1b[32m"
COLOR_YELLOW = "\x1b[33m"
COLOR_CYAN = "\x1b[36m"
COLOR_BOLD = "\x1b[1m"


def _ansi(color: str, text: str) -> str:
    return f"{color}{text}{COLOR_RESET}"


def print_info(text: str) -> None:
    print_formatted_text(ANSI(text))


def print_success(text: str) -> None:
    print_formatted_text(ANSI(_ansi(COLOR_GREEN, text)))


def print_error(text: str) -> None:
    print_formatted_text(ANSI(_ansi(COLOR_RED, text)))


def print_warning(text: str) -> None:
    print_formatted_text(ANSI(_ansi(COLOR_YELLOW, text)))


def print_header(text: str) -> None:
    width = min(shutil.get_terminal_size((80, 24)).columns, 100)
    print_info("")
    print_info(_ansi(COLOR_CYAN + COLOR_BOLD, f"─ {text} " + "─" * max(width - len(text) - 4, 0)))


def clear_screen() -> None:
    print_formatted_text(ANSI("\x1b[2J\x1b[H"))


def ask(message: str, default: str = "") -> str:
    """Prompt for one line of text; empty input falls back to default.

    The default is shown as a hint instead of pre-filling the buffer, so
    typing replaces it instead of appending to it.
    """
    hint = f"（默认：{default}）" if default else ""
    value = prompt(f"{message}{hint} ").strip()
    return value or default


def ask_required(message: str, default: str = "") -> str:
    while True:
        value = ask(message, default=default)
        if value:
            return value
        print_warning("输入不能为空。")


def input_multiline(message: str) -> str:
    """Prompt for multi-line text (paste-friendly); Esc+Enter submits."""
    return prompt(f"{message}（粘贴多行内容，完成后按 Esc 再回车提交；留空直接回车返回）\n", multiline=True)


def ask_int(message: str, default: int, minimum: int, maximum: int) -> int:
    while True:
        raw = ask(f"{message} [{minimum}-{maximum}]", default=str(default))
        try:
            value = int(raw)
        except ValueError:
            print_warning(f"请输入 {minimum}-{maximum} 之间的整数。")
            continue
        if minimum <= value <= maximum:
            return value
        print_warning(f"请输入 {minimum}-{maximum} 之间的整数。")


def confirm(message: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        raw = ask(f"{message} ({hint})").lower()
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print_warning("请输入 y 或 n。")


def menu(title: str, options: Sequence[str], prompt_text: str = "请选择") -> int:
    """Print a numbered menu and return the selected index (1-based input).

    Long options are truncated to the terminal width so a single over-long
    song name / path never wraps the whole menu.  Raises KeyboardInterrupt
    when the user presses Ctrl-C.
    """
    print_header(title)
    width = max(shutil.get_terminal_size((80, 24)).columns - 6, 10)
    for index, option in enumerate(options, start=1):
        text = str(option)
        if _display_width(text) > width:
            text = _truncate_to_width(text, max(width - 1, 1)) + "…"
        print_info(f"  {index}. {text}")
    print_info("")
    while True:
        raw = ask(f"{prompt_text} [1-{len(options)}]").strip()
        if raw.isdigit():
            choice = int(raw)
            if 1 <= choice <= len(options):
                return choice
        print_warning(f"请输入 1-{len(options)} 之间的数字。")


def multiselect(title: str, entries: Sequence[tuple[str, bool]], text: str = "") -> list[int]:
    """Open a checkbox multi-select dialog; return the selected indexes.

    *entries* are (label, checked) pairs.  Space toggles a row, Enter
    confirms, Esc cancels (returns []).
    """
    if not entries:
        print_warning("没有可选项目。")
        return []
    labels = [label for label, _checked in entries]
    values: list[tuple[str, str]] = [(label, label) for label in labels]
    default_values = [label for label, checked in entries if checked]
    selected: list[str] | None = checkboxlist_dialog(
        title=title,
        text=text,
        values=values,
        default_values=default_values,
        ok_text="确定",
        cancel_text="取消",
    ).run()
    if selected is None:
        return []
    return [index for index, label in enumerate(labels) if label in selected]


def render_qr_ascii(text: str) -> str:
    """Render a compact QR code that fits a normal terminal window.

    Uses the same trick as bili-hardcore (Dense1x2): half-block characters
    (▀▄█) squeeze two module rows into one line, with a minimal 1-module
    quiet zone — a typical login QR is about 31 columns by 16 lines.

    On a real terminal the QR gets a black background so it stays
    scannable on both light and dark themes.
    """
    import sys

    import qrcode

    qr = qrcode.QRCode(border=1)
    qr.add_data(text)
    qr.make(fit=True)
    modcount = qr.modules_count
    border = qr.border
    tty = bool(getattr(sys.stdout, "isatty", lambda: False)())
    # Light module = white block on black background; dark module = black
    # cell.  This keeps contrast correct on any terminal theme.
    codes = ["█", "▄", "▀", " "] if tty else [" ", "▀", "▄", "█"]

    def module_at(x: int, y: int) -> int:
        if tty and border and max(x, y) >= modcount + border:
            return 1
        if min(x, y) < 0 or max(x, y) >= modcount:
            return 0
        return int(qr.modules[x][y])

    lines: list[str] = []
    for row in range(-border, modcount + border, 2):
        if tty:
            if row < modcount + border - 1:
                line = "\x1b[48;5;232m"
            else:
                line = ""
            line += "\x1b[38;5;255m"
        else:
            line = ""
        for col in range(-border, modcount + border):
            pos = module_at(row, col) + (module_at(row + 1, col) << 1)
            line += codes[pos]
        if tty:
            line += "\x1b[0m"
        lines.append(line)
    return "\n".join(lines)


def _display_width(text: str) -> int:
    """Terminal display width (CJK wide chars count as 2)."""
    try:
        width = wcswidth(text)
    except Exception:  # pragma: no cover - defensive
        width = -1
    return width if width >= 0 else len(text)


def _truncate_to_width(text: str, max_width: int) -> str:
    """Truncate *text* so its display width fits within *max_width*."""
    out = ""
    used = 0
    for ch in text:
        ch_width = _display_width(ch)
        if used + ch_width > max_width:
            break
        out += ch
        used += ch_width
    return out


def print_table(headers: Sequence[str], rows: Sequence[Sequence[str]], max_width: int = 100) -> None:
    """Print a simple aligned text table with truncated cells.

    Uses wcwidth so CJK full-width characters align correctly in a terminal.
    """
    width = min(shutil.get_terminal_size((80, 24)).columns, max_width)
    columns = len(headers)
    header_widths = [_display_width(str(h)) for h in headers]
    cell_widths = list(header_widths)
    for row in rows:
        for index, cell in enumerate(row):
            if index < columns:
                cell_widths[index] = max(cell_widths[index], _display_width(str(cell)))
    # Shrink the widest columns so the total fits the terminal.  Columns are
    # joined by two spaces, so the rendered width is sum(cell_widths) + 2*(n-1).
    total = sum(cell_widths) + (columns - 1) * 2
    while total > width and max(cell_widths) > 8:
        widest = max(range(columns), key=lambda i: cell_widths[i])
        cell_widths[widest] -= 1
        total = sum(cell_widths) + (columns - 1) * 2

    def fmt_cell(cell: str, col_width: int) -> str:
        disp = _display_width(cell)
        if disp <= col_width:
            return cell + " " * (col_width - disp)
        body = _truncate_to_width(cell, max(col_width - 1, 1))
        return body + "…" + " " * (col_width - _display_width(body) - 1)

    def fmt_row(cells: Sequence[str]) -> str:
        parts = []
        for index, cell in enumerate(cells):
            if index >= columns:
                break
            parts.append(fmt_cell(str(cell), cell_widths[index]))
        return "  ".join(parts).rstrip()

    # Header row is drawn in cyan + bold so the table reads clearly even in a
    # plain terminal.
    print_info(_ansi(COLOR_CYAN + COLOR_BOLD, fmt_row(headers)))
    print_info("─" * min(total, width))
    for row in rows:
        print_info(fmt_row(row))


__all__ = [
    "ask",
    "ask_int",
    "ask_required",
    "input_multiline",
    "clear_screen",
    "confirm",
    "menu",
    "multiselect",
    "print_error",
    "print_header",
    "print_info",
    "print_success",
    "print_table",
    "print_warning",
    "render_qr_ascii",
]
