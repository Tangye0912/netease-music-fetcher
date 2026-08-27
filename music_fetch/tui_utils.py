#!/usr/bin/env python3
"""Small terminal UI helpers built on prompt_toolkit."""

from __future__ import annotations

import re
import shutil
import sys
import threading
from contextlib import contextmanager
from typing import Iterator, Optional, Sequence

from prompt_toolkit import ANSI, prompt, print_formatted_text
from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.keys import Keys
from prompt_toolkit.shortcuts import checkboxlist_dialog
from prompt_toolkit.styles import Style
from wcwidth import wcswidth

COLOR_RESET = "\x1b[0m"
COLOR_RED = "\x1b[91m"
COLOR_GREEN = "\x1b[92m"
COLOR_YELLOW = "\x1b[93m"
COLOR_CYAN = "\x1b[96m"
COLOR_WHITE = "\x1b[97m"
COLOR_DIM = "\x1b[90m"
COLOR_BOLD = "\x1b[1m"
COLOR_STATUS_BG = "\x1b[48;5;30m"

# Upper bound for rendered content width. Wider terminals use the extra room
# (resizing the window helps), but we stop at this cap to avoid absurd layouts.
MAX_CONTENT_WIDTH = 160

# Bili-hardcore-inspired palette: cyan focus, yellow metadata, green/red
# state, muted gray chrome, and a charcoal dialog canvas.  The actual font is
# controlled by the user's terminal; these styles provide the visual hierarchy.
DIALOG_STYLE = Style.from_dict(
    {
        "dialog": "bg:#242830",
        "dialog.body": "bg:#242830 #f4f4f4",
        "dialog frame-label": "#5ad4e6 bold",
        "checkbox": "#697386",
        "checkbox-selected": "#5ad4e6 bold",
        "button": "#697386",
        "button.focused": "bg:#5ad4e6 #20242b bold",
    }
)

PROGRESS_STYLE = Style.from_dict(
    {
        "progressbar": "bg:#242830",
        "title": "#5ad4e6 bold",
        "label": "#f4f4f4",
        "percentage": "#ffd166 bold",
        "bar": "#697386",
        "bar-a": "#5ad4e6",
        "bar-b": "#a8e063 bold",
        "bar-c": "#3d4450",
        "current": "#ffd166",
        "total": "#9aa4b2",
        "time-elapsed": "#9aa4b2",
        "time-left": "#9aa4b2",
    }
)


def _ansi(color: str, text: str) -> str:
    return f"{color}{text}{COLOR_RESET}"


_ANSI_STRIP_RE = re.compile(r"\x1b\[[0-9;]*m")


def _safe_print_formatted(text: str) -> None:
    """Render prompt_toolkit formatted text; fall back to plain print when no
    interactive console is available (CI runners, piped stdout, headless)."""
    try:
        print_formatted_text(ANSI(text))
    except Exception:
        # Strip ANSI escape codes for the plain-text fallback.
        plain = _ANSI_STRIP_RE.sub("", text)
        print(plain)


def print_info(text: str) -> None:
    _safe_print_formatted(text)


def print_success(text: str) -> None:
    _safe_print_formatted(_ansi(COLOR_GREEN + COLOR_BOLD, f"✓ {text}"))


def print_error(text: str) -> None:
    _safe_print_formatted(_ansi(COLOR_RED + COLOR_BOLD, f"✕ {text}"))


def print_warning(text: str) -> None:
    _safe_print_formatted(_ansi(COLOR_YELLOW, f"! {text}"))


def print_status(items: Sequence[tuple[str, str]]) -> None:
    """Render compact application state as a full-width cyan status band."""
    width = min(shutil.get_terminal_size((80, 24)).columns, MAX_CONTENT_WIDTH)
    content = "  " + "  │  ".join(f"{label}: {value}" for label, value in items) + "  "
    content = _truncate_to_width(content, width)
    content += " " * max(width - _display_width(content), 0)
    _safe_print_formatted(_ansi(COLOR_STATUS_BG + COLOR_WHITE + COLOR_BOLD, content))


def print_header(text: str) -> None:
    width = min(shutil.get_terminal_size((80, 24)).columns, MAX_CONTENT_WIDTH)
    label = _truncate_to_width(str(text), max(width - 4, 1))
    label_width = _display_width(label) + 2
    remaining = max(width - label_width, 0)
    left = remaining // 2
    right = remaining - left
    print_info("")
    print_info(_ansi(COLOR_CYAN + COLOR_BOLD, "─" * left + f" {label} " + "─" * right))


def clear_screen() -> None:
    _safe_print_formatted("\x1b[2J\x1b[H")


def ask(message: str, default: str = "") -> str:
    """Prompt for one line of text; empty input falls back to default.

    The default is shown as a hint instead of pre-filling the buffer, so
    typing replaces it instead of appending to it.
    """
    hint = f"（默认：{default}）" if default else ""
    prompt_text = (
        _ansi(COLOR_CYAN + COLOR_BOLD, "› ")
        + _ansi(COLOR_WHITE + COLOR_BOLD, message)
        + (_ansi(COLOR_DIM, hint) if hint else "")
        + " "
    )
    value = prompt(ANSI(prompt_text)).strip()
    return value or default


def ask_required(message: str, default: str = "") -> str:
    while True:
        value = ask(message, default=default)
        if value:
            return value
        print_warning("输入不能为空。")


def input_multiline(message: str) -> str:
    """Prompt for multi-line text (paste-friendly); Esc+Enter submits."""
    hint = "（粘贴多行内容，完成后按 Esc 再回车提交；留空直接回车返回）"
    prompt_text = _ansi(COLOR_CYAN + COLOR_BOLD, "› ") + _ansi(
        COLOR_WHITE + COLOR_BOLD, message
    ) + _ansi(COLOR_DIM, hint) + "\n"
    return prompt(ANSI(prompt_text), multiline=True)


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


def menu(
    title: str,
    options: Sequence[str],
    prompt_text: str = "请选择",
    shortcuts: Optional[dict[str, int]] = None,
) -> int:
    """Print a numbered menu and return the selected index (1-based input).

    Long options are truncated to the terminal width so a single over-long
    song name / path never wraps the whole menu.  *shortcuts* maps single
    keystrokes to 1-based choices (e.g. {"q": 10} for quit) and are shown in
    the footer.  Raises KeyboardInterrupt when the user presses Ctrl-C.
    """
    terminal_width = min(shutil.get_terminal_size((80, 24)).columns, MAX_CONTENT_WIDTH)
    box_width = max(terminal_width, 12)
    inner_width = max(box_width - 2, 1)
    title_text = _truncate_to_width(str(title), max(inner_width - 4, 1))
    title_label = f" {title_text} "
    title_remaining = max(inner_width - _display_width(title_label), 0)
    top = "┌" + "─" * (title_remaining // 2) + title_label + "─" * (
        title_remaining - title_remaining // 2
    ) + "┐"
    print_info("")
    print_info(_ansi(COLOR_CYAN + COLOR_BOLD, top))
    option_width = max(box_width - 8, 1)
    for index, option in enumerate(options, start=1):
        text = str(option)
        if _display_width(text) > option_width:
            text = _truncate_to_width(text, max(option_width - 1, 1)) + "…"
        padding = " " * max(option_width - _display_width(text), 0)
        line = (
            _ansi(COLOR_DIM, "│ ")
            + _ansi(COLOR_YELLOW + COLOR_BOLD, f"{index:02d}")
            + "  "
            + _ansi(COLOR_WHITE, text + padding)
            + _ansi(COLOR_DIM, " │")
        )
        print_info(line)
    print_info(_ansi(COLOR_CYAN + COLOR_BOLD, "└" + "─" * inner_width + "┘"))
    footer = "  输入序号确认 · Ctrl+C 返回"
    if shortcuts:
        footer += " · " + " · ".join(f"{key} {options[choice - 1]}" for key, choice in shortcuts.items())
    print_info(_ansi(COLOR_DIM, footer))
    while True:
        raw = ask(f"{prompt_text} [1-{len(options)}]").strip()
        if shortcuts and raw and raw.lower() in shortcuts:
            return shortcuts[raw.lower()]
        if raw.isdigit():
            choice = int(raw)
            if 1 <= choice <= len(options):
                return choice
        print_warning(f"请输入 1-{len(options)} 之间的数字。")


def print_panel(
    title: str,
    rows: Sequence[tuple[str, str]],
    max_width: int = MAX_CONTENT_WIDTH,
) -> None:
    """Print a bordered info card with a centered title and key-value rows."""
    terminal_width = min(shutil.get_terminal_size((80, 24)).columns, max_width)
    width = max(terminal_width, 20)
    inner_width = max(width - 2, 1)
    title_text = f" {_truncate_to_width(str(title), max(inner_width - 4, 1))} "
    remaining = max(inner_width - _display_width(title_text), 0)
    top = "┌" + "─" * (remaining // 2) + title_text + "─" * (
        remaining - remaining // 2
    ) + "┐"
    print_info(_ansi(COLOR_CYAN + COLOR_BOLD, top))
    for label, value in rows:
        text = f"{label}：{value}"
        if _display_width(text) > inner_width - 2:
            text = _truncate_to_width(text, max(inner_width - 3, 1)) + "…"
        body = _ansi(COLOR_YELLOW + COLOR_BOLD, label) + _ansi(COLOR_WHITE, f"：{value}")
        padding = " " * max(inner_width - 2 - _display_width(text), 0)
        print_info(_ansi(COLOR_DIM, "│ ") + body + padding + _ansi(COLOR_DIM, " │"))
    print_info(_ansi(COLOR_CYAN + COLOR_BOLD, "└" + "─" * inner_width + "┘"))


# ASCII-only frames: braille spinners crash on GBK-codepage Windows consoles
# (UnicodeEncodeError), so keep the animation safe everywhere.
_SPINNER_FRAMES = ("|", "/", "-", "\\")


@contextmanager
def spinner(message: str, delay: float = 0.12) -> Iterator[None]:
    """Animate a one-line spinner while the wrapped block runs.

    The raw stdout writes are safe to mix with prompt_toolkit output because
    the spinner owns its line and clears it on exit.
    """
    stop = threading.Event()

    def _run() -> None:
        index = 0
        while not stop.is_set():
            sys.stdout.write(f"\r{_SPINNER_FRAMES[index % len(_SPINNER_FRAMES)]} {message}  ")
            sys.stdout.flush()
            index += 1
            stop.wait(delay)

    worker = threading.Thread(target=_run, daemon=True)
    sys.stdout.write(f"\r{_SPINNER_FRAMES[0]} {message}  ")
    sys.stdout.flush()
    worker.start()
    try:
        yield
    finally:
        stop.set()
        worker.join(timeout=1)
        sys.stdout.write("\r" + " " * min(len(message) + 16, 80) + "\r")
        sys.stdout.flush()


def _bind_escape_to_cancel(dialog: Application[list[str] | None]) -> None:
    """Make Esc close a Prompt Toolkit multi-select with a canceled result."""
    bindings = KeyBindings()

    @bindings.add(Keys.Escape, eager=True)
    def _cancel(event: KeyPressEvent) -> None:
        event.app.exit(result=None)

    if dialog.key_bindings is None:
        dialog.key_bindings = bindings
    else:
        dialog.key_bindings = merge_key_bindings([dialog.key_bindings, bindings])


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
    dialog = checkboxlist_dialog(
        title=title,
        text=text,
        values=values,
        default_values=default_values,
        ok_text="确定",
        cancel_text="取消",
        style=DIALOG_STYLE,
    )
    _bind_escape_to_cancel(dialog)
    selected: list[str] | None = dialog.run()
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


def print_table(headers: Sequence[str], rows: Sequence[Sequence[str]], max_width: int = MAX_CONTENT_WIDTH) -> None:
    """Print a bordered, aligned table with truncated cells.

    Uses wcwidth so CJK full-width characters align correctly in a terminal.
    """
    if not headers:
        return
    width = min(shutil.get_terminal_size((80, 24)).columns, max_width)
    columns = len(headers)
    header_widths = [_display_width(str(h)) for h in headers]
    cell_widths = list(header_widths)
    for row in rows:
        for index, cell in enumerate(row):
            if index < columns:
                cell_widths[index] = max(cell_widths[index], _display_width(str(cell)))
    # Box rows are: │ cell │ cell │, adding three characters per column plus
    # one final border. Shrink data-heavy columns while keeping headers intact.
    minimums = [max(header_width, 3) for header_width in header_widths]
    total = sum(cell_widths) + columns * 3 + 1
    while total > width and any(cell_widths[i] > minimums[i] for i in range(columns)):
        widest = max(
            (i for i in range(columns) if cell_widths[i] > minimums[i]),
            key=lambda i: cell_widths[i] - minimums[i],
        )
        cell_widths[widest] -= 1
        total = sum(cell_widths) + columns * 3 + 1

    def fmt_cell(cell: str, col_width: int) -> str:
        disp = _display_width(cell)
        if disp <= col_width:
            return cell + " " * (col_width - disp)
        body = _truncate_to_width(cell, max(col_width - 1, 1))
        return body + "…" + " " * (col_width - _display_width(body) - 1)

    def fmt_row(cells: Sequence[str], header: bool = False) -> str:
        parts = [_ansi(COLOR_DIM, "│ ")]
        for index in range(columns):
            cell = cells[index] if index < len(cells) else ""
            color = COLOR_CYAN + COLOR_BOLD if header else (
                COLOR_YELLOW if index == 0 else COLOR_WHITE
            )
            parts.append(_ansi(color, fmt_cell(str(cell), cell_widths[index])))
            parts.append(_ansi(COLOR_DIM, " │" if index == columns - 1 else " │ "))
        return "".join(parts)

    def border(left: str, join: str, right: str, color: str = COLOR_DIM) -> str:
        line = left + join.join("─" * (col_width + 2) for col_width in cell_widths) + right
        return _ansi(color, line)

    print_info(border("┌", "┬", "┐", COLOR_CYAN))
    print_info(fmt_row(headers, header=True))
    print_info(border("├", "┼", "┤"))
    truncated = False
    for row in rows:
        for index, cell in enumerate(row):
            if index < columns and _display_width(str(cell)) > cell_widths[index]:
                truncated = True
        print_info(fmt_row(row))
    print_info(border("└", "┴", "┘", COLOR_CYAN))
    if truncated:
        print_info(_ansi(COLOR_DIM, "（窗口较窄，部分内容已截断；加宽终端窗口可查看完整信息）"))


__all__ = [
    "DIALOG_STYLE",
    "PROGRESS_STYLE",
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
    "print_panel",
    "print_status",
    "print_success",
    "print_table",
    "print_warning",
    "render_qr_ascii",
    "spinner",
]
