"""UI-independent helpers for the table view: filtering, sorting, summaries.

Kept separate from ``ui.py`` so the logic is unit-testable without a display.
"""
from __future__ import annotations

from collections import Counter
from typing import Iterable

from .models import Action, Category, ScanItem

SORTABLE_COLUMNS = ("checked", "action", "category", "name", "files", "size", "patient", "path")

_CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2}


def filter_items(
    items: Iterable[ScanItem],
    *,
    query: str = "",
    category: Category | None = None,
    action: Action | None = None,
    confidence: str | None = None,
    only_selected: bool = False,
) -> list[ScanItem]:
    query = query.strip().casefold()
    result: list[ScanItem] = []
    for item in items:
        if category is not None and item.category != category:
            continue
        if action is not None and item.action != action:
            continue
        if confidence is not None and item.confidence != confidence:
            continue
        if only_selected and not item.selected:
            continue
        if query:
            haystack = " ".join(
                (
                    item.display_name,
                    item.patient_name,
                    item.patient_id,
                    item.reason,
                    str(item.primary_path),
                )
            ).casefold()
            if query not in haystack:
                continue
        result.append(item)
    return result


def sort_items(items: list[ScanItem], column: str, reverse: bool = False) -> list[ScanItem]:
    """Stable sort of scan items by a table column."""
    category_order = {category: index for index, category in enumerate(Category)}
    action_order = {action: index for index, action in enumerate(Action)}

    def key(item: ScanItem):
        if column == "checked":
            return (not item.selected,)
        if column == "action":
            return (action_order[item.action],)
        if column == "category":
            return (category_order[item.category], item.display_name.casefold())
        if column == "files":
            return (item.file_count,)
        if column == "size":
            return (item.total_size,)
        if column == "patient":
            return ((item.patient_name or item.patient_id).casefold(), item.study_date)
        if column == "path":
            return (str(item.primary_path).casefold(),)
        return (item.display_name.casefold(),)

    return sorted(items, key=key, reverse=reverse)


def category_counts(items: Iterable[ScanItem]) -> Counter[Category]:
    return Counter(item.category for item in items)


def confidence_rank(value: str) -> int:
    return _CONFIDENCE_ORDER.get(value, len(_CONFIDENCE_ORDER))


def series_members(items: Iterable[ScanItem], series_label: str) -> list[ScanItem]:
    """All items that belong to the given numbered-series label."""
    return [item for item in items if item.metadata.get("series") == series_label]


def row_tag(item: ScanItem) -> str:
    """Visual grouping tag for a table row."""
    if item.category == Category.DUPLICATE:
        return "duplicate"
    if item.category == Category.JUNK:
        return "junk"
    if item.category in {Category.CT, Category.XRAY, Category.DICOM_OTHER}:
        return "dicom"
    if item.category == Category.IMAGE_REVIEW:
        return "review"
    return "plain"
