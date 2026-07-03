"""
Shared QComboBox builder utilities.

Used by both UiSettingsDialog and BatchRuntimeSettingsDialog to avoid
duplicating combo-box creation, value selection, and data extraction
in two places.
"""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox



__all__ = ['build_value_combo', 'build_options_combo', 'combo_int_value', 'set_combo_value']
def build_value_combo(min_value: int, max_value: int, suffix: str) -> QComboBox:
    """Build a combo spanning every integer in [min_value, max_value]."""
    combo = QComboBox()
    for value in range(min_value, max_value + 1):
        combo.addItem(f"{value} {suffix}", value)
    combo.setEditable(False)
    combo.setMinimumWidth(220)
    combo.setMinimumContentsLength(12)
    combo.view().setMinimumWidth(240)
    return combo


def build_options_combo(values: tuple[int, ...], suffix: str) -> QComboBox:
    """Build a combo from a fixed tuple of integer options."""
    combo = QComboBox()
    for value in values:
        combo.addItem(f"{value} {suffix}", int(value))
    combo.setEditable(False)
    combo.setMinimumWidth(180)
    combo.view().setMinimumWidth(200)
    return combo


def set_combo_value(combo: QComboBox, value: int) -> None:
    """Select the entry whose user-data matches value, or the nearest match."""
    index = combo.findData(value)
    if index >= 0:
        combo.setCurrentIndex(index)
        return
    nearest_index = 0
    nearest_distance: int | None = None
    for idx in range(combo.count()):
        item_data = combo.itemData(idx)
        try:
            item_value = int(item_data)
        except (TypeError, ValueError):
            continue
        distance = abs(item_value - int(value))
        if nearest_distance is None or distance < nearest_distance:
            nearest_distance = distance
            nearest_index = idx
    combo.setCurrentIndex(nearest_index)


def combo_int_value(combo: QComboBox, fallback: int) -> int:
    """Return the integer user-data of the current selection."""
    data = combo.currentData()
    try:
        return int(data)
    except (TypeError, ValueError):
        return fallback
