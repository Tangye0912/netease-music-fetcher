"""Reusable full-screen controls, with lazy list rendering and stable selection."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Callable

from prompt_toolkit.data_structures import Point
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import UIContent, UIControl, Window
from prompt_toolkit.layout.margins import ScrollbarMargin
from wcwidth import wcswidth


def clean_text(text: str) -> str:
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", str(text))
    return " ".join("".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch) != "Cc").split())


def clip(text: str, width: int) -> str:
    """Clip on display cells without splitting combining/ZWJ/flag sequences."""
    text = clean_text(text)
    if width <= 0:
        return ""
    if wcswidth(text) <= width:
        return text
    clusters: list[str] = []
    for ch in text:
        regional = 0x1F1E6 <= ord(ch) <= 0x1F1FF
        if clusters and (unicodedata.combining(ch) or ch in "\ufe0f\ufe0e\u200d" or clusters[-1].endswith("\u200d")
                         or 0x1F3FB <= ord(ch) <= 0x1F3FF
                         or (regional and len(clusters[-1]) == 1 and 0x1F1E6 <= ord(clusters[-1]) <= 0x1F1FF)):
            clusters[-1] += ch
        else:
            clusters.append(ch)
    result = ""
    for cluster in clusters:
        if wcswidth(result + cluster) > width - 1:
            break
        result += cluster
    return result + "…"


@dataclass(frozen=True)
class Choice:
    key: str
    title: str
    subtitle: str = ""
    enabled: bool = True


class ChoiceList(UIControl):
    def __init__(self, rows: list[Choice] | None = None, *, multiple: bool = False,
                 activate: Callable[[str], None] | None = None,
                 changed: Callable[[], None] | None = None) -> None:
        self.all_rows = rows or []
        self.rows = self.all_rows[:]
        self.multiple = multiple
        self.activate = activate or (lambda _key: None)
        self.changed = changed or (lambda: None)
        self.selected: set[str] = set()
        self.query = ""
        self.index = 0
        self.height = 10
        self.key_bindings = KeyBindings()
        self.window = Window(self, wrap_lines=False, right_margins=[ScrollbarMargin(display_arrows=True)],
                             style="class:list", cursorline=False)
        for key, delta in (("up", -1), ("down", 1)):
            self.key_bindings.add(key)(lambda event, delta=delta: self.move(delta))
        self.key_bindings.add("pageup")(lambda event: self.move(-max(1, self.height // 2)))
        self.key_bindings.add("pagedown")(lambda event: self.move(max(1, self.height // 2)))
        self.key_bindings.add("home")(lambda event: self.move(-len(self.rows)))
        self.key_bindings.add("end")(lambda event: self.move(len(self.rows)))
        self.key_bindings.add("enter")(lambda event: self.activate(self.current.key) if self.current else None)
        if multiple:
            self.key_bindings.add(" ")(lambda event: self.toggle())
            self.key_bindings.add("c-a")(lambda event: self.select_all())
            self.key_bindings.add("c-u")(lambda event: self.clear_selection())

    def is_focusable(self) -> bool:
        return True

    def get_key_bindings(self) -> KeyBindings:
        return self.key_bindings

    @property
    def current(self) -> Choice | None:
        return self.rows[self.index] if self.rows else None

    def set_rows(self, rows: list[Choice]) -> None:
        key = self.current.key if self.current else None
        self.all_rows = rows
        valid = {row.key for row in rows if row.enabled}
        self.selected.intersection_update(valid)
        self._filter(key)

    def set_query(self, query: str) -> None:
        key = self.current.key if self.current else None
        self.query = query
        self._filter(key)

    def _filter(self, key: str | None) -> None:
        terms = self.query.casefold().split()
        self.rows = [row for row in self.all_rows if all(term in f"{row.key} {row.title} {row.subtitle}".casefold() for term in terms)]
        self.index = next((i for i, row in enumerate(self.rows) if row.key == key), min(self.index, max(0, len(self.rows) - 1)))
        self.changed()

    def move(self, delta: int) -> None:
        self.index = min(max(self.index + delta, 0), max(0, len(self.rows) - 1))
        self.changed()

    def toggle(self) -> None:
        row = self.current
        if row and row.enabled:
            if row.key in self.selected:
                self.selected.remove(row.key)
            else:
                self.selected.add(row.key)
            self.changed()

    def select_all(self) -> None:
        self.selected.update(row.key for row in self.rows if row.enabled)
        self.changed()

    def clear_selection(self) -> None:
        self.selected.clear()
        self.changed()

    def create_content(self, width: int, height: int) -> UIContent:
        self.height = height
        if not self.rows:
            return UIContent(get_line=lambda _i: [("class:muted", clip("  暂无内容 · 可修改输入或筛选条件", width))], line_count=1)

        def line(number: int) -> StyleAndTextTuples:
            index, subline = divmod(number, 2)
            row = self.rows[index]
            focused = index == self.index
            style = "class:focused" if focused else ("class:text" if row.enabled else "class:muted")
            if subline:
                text = "    " + row.subtitle
                style += " class:secondary" if not focused else ""
            else:
                marker = ("[x] " if row.key in self.selected else "[ ] ") if self.multiple else "  "
                text = ("› " if focused else "  ") + marker + row.title
            text = clip(text, width)
            return [(style, text + " " * max(0, width - max(0, wcswidth(text))))]

        return UIContent(get_line=line, line_count=len(self.rows) * 2,
                         cursor_position=Point(x=0, y=self.index * 2), show_cursor=False)
