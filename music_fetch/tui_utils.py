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

ANSI_RESET = "\x1b[0m"
ANSI_BOLD = "\x1b[1m"

DARK_THEME: dict[str, str] = {
    "title": "\x1b[96m",
    "text": "\x1b[97m",
    "muted": "\x1b[90m",
    "success": "\x1b[92m",
    "failure": "\x1b[91m",
    "warning": "\x1b[93m",
    "metadata": "\x1b[93m",
    "status_bg": "\x1b[48;5;30m",
    "status_text": "\x1b[97m",
    "dialog_bg": "#242830",
    "dialog_text": "#f4f4f4",
    "dialog_muted": "#697386",
    "dialog_focus": "#5ad4e6",
    "dialog_focus_text": "#20242b",
    "progress_accent": "#a8e063",
    "progress_track": "#3d4450",
    "progress_current": "#ffd166",
}

LIGHT_THEME: dict[str, str] = {
    "title": "\x1b[38;5;30m",
    "text": "\x1b[38;5;236m",
    "muted": "\x1b[38;5;244m",
    "success": "\x1b[38;5;28m",
    "failure": "\x1b[38;5;124m",
    "warning": "\x1b[38;5;130m",
    "metadata": "\x1b[38;5;130m",
    "status_bg": "\x1b[48;5;30m",
    "status_text": "\x1b[97m",
    "dialog_bg": "#f6f8fa",
    "dialog_text": "#20242b",
    "dialog_muted": "#6b7280",
    "dialog_focus": "#007c91",
    "dialog_focus_text": "#ffffff",
    "progress_accent": "#2e7d32",
    "progress_track": "#d0d7de",
    "progress_current": "#9a6700",
}

_ACTIVE_THEME_NAME = "dark"
_ACTIVE_THEME = DARK_THEME

# Upper bound for rendered content width. Wider terminals use the extra room
# (resizing the window helps), but we stop at this cap to avoid absurd layouts.
MAX_CONTENT_WIDTH = 160

def _build_dialog_style(theme: dict[str, str]) -> Style:
    return Style.from_dict(
        {
            "dialog": f"bg:{theme['dialog_bg']}",
            "dialog.body": f"bg:{theme['dialog_bg']} {theme['dialog_text']}",
            "dialog frame-label": f"{theme['dialog_focus']} bold",
            "checkbox": theme["dialog_muted"],
            "checkbox-selected": f"{theme['dialog_focus']} bold",
            "button": theme["dialog_muted"],
            "button.focused": (
                f"bg:{theme['dialog_focus']} {theme['dialog_focus_text']} bold"
            ),
        }
    )


def _build_progress_style(theme: dict[str, str]) -> Style:
    return Style.from_dict(
        {
            "progressbar": f"bg:{theme['dialog_bg']}",
            "title": f"{theme['dialog_focus']} bold",
            "label": theme["dialog_text"],
            "percentage": f"{theme['progress_current']} bold",
            "bar": theme["dialog_muted"],
            "bar-a": theme["dialog_focus"],
            "bar-b": f"{theme['progress_accent']} bold",
            "bar-c": theme["progress_track"],
            "current": theme["progress_current"],
            "total": theme["dialog_muted"],
            "time-elapsed": theme["dialog_muted"],
            "time-left": theme["dialog_muted"],
        }
    )


DIALOG_STYLE = _build_dialog_style(_ACTIVE_THEME)
PROGRESS_STYLE = _build_progress_style(_ACTIVE_THEME)


def set_theme(name: str) -> str:
    """Activate a terminal palette and return its normalized name."""
    normalized = str(name or "").strip().lower()
    if normalized not in {"dark", "light"}:
        normalized = "dark"
    theme = LIGHT_THEME if normalized == "light" else DARK_THEME
    global _ACTIVE_THEME_NAME, _ACTIVE_THEME, DIALOG_STYLE, PROGRESS_STYLE
    _ACTIVE_THEME_NAME = normalized
    _ACTIVE_THEME = theme
    DIALOG_STYLE = _build_dialog_style(theme)
    PROGRESS_STYLE = _build_progress_style(theme)
    return normalized


def get_theme_name() -> str:
    return _ACTIVE_THEME_NAME


def _theme_color(role: str) -> str:
    return _ACTIVE_THEME[role]


def _ansi(color: str, text: str) -> str:
    return f"{color}{text}{ANSI_RESET}"


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
    _safe_print_formatted(_ansi(_theme_color("success") + ANSI_BOLD, f"✓ {text}"))


def print_error(text: str) -> None:
    _safe_print_formatted(_ansi(_theme_color("failure") + ANSI_BOLD, f"✕ {text}"))


def print_warning(text: str) -> None:
    _safe_print_formatted(_ansi(_theme_color("warning"), f"! {text}"))


def print_status(items: Sequence[tuple[str, str]]) -> None:
    """Render compact application state as a full-width cyan status band."""
    width = min(shutil.get_terminal_size((80, 24)).columns, MAX_CONTENT_WIDTH)
    content = "  " + "  │  ".join(f"{label}: {value}" for label, value in items) + "  "
    content = _truncate_to_width(content, width)
    content += " " * max(width - _display_width(content), 0)
    _safe_print_formatted(
        _ansi(_theme_color("status_bg") + _theme_color("status_text") + ANSI_BOLD, content)
    )


def print_header(text: str) -> None:
    width = min(shutil.get_terminal_size((80, 24)).columns, MAX_CONTENT_WIDTH)
    label = _truncate_to_width(str(text), max(width - 4, 1))
    label_width = _display_width(label) + 2
    remaining = max(width - label_width, 0)
    left = remaining // 2
    right = remaining - left
    print_info("")
    print_info(_ansi(_theme_color("title") + ANSI_BOLD, "─" * left + f" {label} " + "─" * right))


def clear_screen() -> None:
    _safe_print_formatted("\x1b[2J\x1b[H")


def ask(message: str, default: str = "") -> str:
    """Prompt for one line of text; empty input falls back to default.

    The default is shown as a hint instead of pre-filling the buffer, so
    typing replaces it instead of appending to it.
    """
    hint = f"（默认：{default}）" if default else ""
    prompt_text = (
        _ansi(_theme_color("title") + ANSI_BOLD, "› ")
        + _ansi(_theme_color("text") + ANSI_BOLD, message)
        + (_ansi(_theme_color("muted"), hint) if hint else "")
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
    prompt_text = _ansi(_theme_color("title") + ANSI_BOLD, "› ") + _ansi(
        _theme_color("text") + ANSI_BOLD, message
    ) + _ansi(_theme_color("muted"), hint) + "\n"
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
    print_info(_ansi(_theme_color("title") + ANSI_BOLD, top))
    option_width = max(box_width - 8, 1)
    for index, option in enumerate(options, start=1):
        text = str(option)
        if _display_width(text) > option_width:
            text = _truncate_to_width(text, max(option_width - 1, 1)) + "…"
        padding = " " * max(option_width - _display_width(text), 0)
        line = (
            _ansi(_theme_color("muted"), "│ ")
            + _ansi(_theme_color("metadata") + ANSI_BOLD, f"{index:02d}")
            + "  "
            + _ansi(_theme_color("text"), text + padding)
            + _ansi(_theme_color("muted"), " │")
        )
        print_info(line)
    print_info(_ansi(_theme_color("title") + ANSI_BOLD, "└" + "─" * inner_width + "┘"))
    footer = "  输入序号确认 · Ctrl+C 返回"
    if shortcuts:
        footer += " · " + " · ".join(f"{key} {options[choice - 1]}" for key, choice in shortcuts.items())
    print_info(_ansi(_theme_color("muted"), footer))
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
    print_info(_ansi(_theme_color("title") + ANSI_BOLD, top))
    for label, value in rows:
        text = f"{label}：{value}"
        if _display_width(text) > inner_width - 2:
            text = _truncate_to_width(text, max(inner_width - 3, 1)) + "…"
        body = _ansi(_theme_color("metadata") + ANSI_BOLD, label) + _ansi(
            _theme_color("text"), f"：{value}"
        )
        padding = " " * max(inner_width - 2 - _display_width(text), 0)
        print_info(
            _ansi(_theme_color("muted"), "│ ")
            + body
            + padding
            + _ansi(_theme_color("muted"), " │")
        )
    print_info(_ansi(_theme_color("title") + ANSI_BOLD, "└" + "─" * inner_width + "┘"))


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
        parts = [_ansi(_theme_color("muted"), "│ ")]
        for index in range(columns):
            cell = cells[index] if index < len(cells) else ""
            color = _theme_color("title") + ANSI_BOLD if header else (
                _theme_color("metadata") if index == 0 else _theme_color("text")
            )
            parts.append(_ansi(color, fmt_cell(str(cell), cell_widths[index])))
            parts.append(_ansi(_theme_color("muted"), " │" if index == columns - 1 else " │ "))
        return "".join(parts)

    def border(left: str, join: str, right: str, color: Optional[str] = None) -> str:
        line = left + join.join("─" * (col_width + 2) for col_width in cell_widths) + right
        return _ansi(color or _theme_color("muted"), line)

    print_info(border("┌", "┬", "┐", _theme_color("title")))
    print_info(fmt_row(headers, header=True))
    print_info(border("├", "┼", "┤"))
    truncated = False
    for row in rows:
        for index, cell in enumerate(row):
            if index < columns and _display_width(str(cell)) > cell_widths[index]:
                truncated = True
        print_info(fmt_row(row))
    print_info(border("└", "┴", "┘", _theme_color("title")))
    if truncated:
        print_info(_ansi(_theme_color("muted"), "（窗口较窄，部分内容已截断；加宽终端窗口可查看完整信息）"))


__all__ = [
    "DIALOG_STYLE",
    "DARK_THEME",
    "LIGHT_THEME",
    "PROGRESS_STYLE",
    "ask",
    "ask_int",
    "ask_required",
    "input_multiline",
    "get_theme_name",
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
    "set_theme",
    "spinner",
]
