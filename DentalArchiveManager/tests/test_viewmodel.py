from __future__ import annotations

import unittest
from pathlib import Path

from dental_archive.i18n import set_language
from dental_archive.models import Action, Category, ScanItem
from dental_archive import viewmodel


def setUpModule() -> None:
    set_language("uk", persist=False)


def make_item(
    name: str,
    category: Category = Category.PHOTO,
    size: int = 10,
    *,
    action: Action = Action.KEEP,
    confidence: str = "high",
    selected: bool = False,
    patient: str = "",
    series: str | None = None,
    files: int = 1,
) -> ScanItem:
    item = ScanItem(
        item_id=name,
        category=category,
        display_name=name,
        source_root=Path("/data"),
        paths=tuple(Path(f"/data/{name}") for _ in range(files)),
        total_size=size,
        reason="r",
        confidence=confidence,
        suggested_action=action,
        action=action,
        selected=selected,
        patient_name=patient,
    )
    if series:
        item.metadata["series"] = series
    return item


class FilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.items = [
            make_item("a.jpg", Category.PHOTO, selected=True, patient="Іваненко"),
            make_item("b.dcm", Category.CT, action=Action.COPY, confidence="medium"),
            make_item("c.tmp", Category.JUNK, action=Action.TRASH, confidence="low"),
        ]

    def test_no_filters_returns_all(self) -> None:
        self.assertEqual(len(viewmodel.filter_items(self.items)), 3)

    def test_category_filter(self) -> None:
        result = viewmodel.filter_items(self.items, category=Category.CT)
        self.assertEqual([item.item_id for item in result], ["b.dcm"])

    def test_action_filter(self) -> None:
        result = viewmodel.filter_items(self.items, action=Action.TRASH)
        self.assertEqual([item.item_id for item in result], ["c.tmp"])

    def test_confidence_filter(self) -> None:
        result = viewmodel.filter_items(self.items, confidence="medium")
        self.assertEqual([item.item_id for item in result], ["b.dcm"])

    def test_only_selected(self) -> None:
        result = viewmodel.filter_items(self.items, only_selected=True)
        self.assertEqual([item.item_id for item in result], ["a.jpg"])

    def test_query_matches_patient_case_insensitive(self) -> None:
        result = viewmodel.filter_items(self.items, query="іване")
        self.assertEqual([item.item_id for item in result], ["a.jpg"])

    def test_combined_filters(self) -> None:
        result = viewmodel.filter_items(self.items, category=Category.PHOTO, only_selected=True, query="a.")
        self.assertEqual(len(result), 1)


class SortTests(unittest.TestCase):
    def test_sort_by_size(self) -> None:
        items = [make_item("big", size=300), make_item("small", size=10), make_item("mid", size=50)]
        result = viewmodel.sort_items(items, "size")
        self.assertEqual([item.item_id for item in result], ["small", "mid", "big"])
        result = viewmodel.sort_items(items, "size", reverse=True)
        self.assertEqual([item.item_id for item in result], ["big", "mid", "small"])

    def test_sort_by_name_case_insensitive(self) -> None:
        items = [make_item("beta"), make_item("Alpha"), make_item("gamma")]
        result = viewmodel.sort_items(items, "name")
        self.assertEqual([item.item_id for item in result], ["Alpha", "beta", "gamma"])

    def test_sort_by_category_uses_enum_order(self) -> None:
        items = [make_item("x", Category.OTHER), make_item("y", Category.CT)]
        result = viewmodel.sort_items(items, "category")
        self.assertEqual([item.item_id for item in result], ["y", "x"])

    def test_sort_by_checked_puts_selected_first(self) -> None:
        items = [make_item("off"), make_item("on", selected=True)]
        result = viewmodel.sort_items(items, "checked")
        self.assertEqual([item.item_id for item in result], ["on", "off"])

    def test_sort_by_files(self) -> None:
        items = [make_item("many", files=5), make_item("one", files=1)]
        result = viewmodel.sort_items(items, "files")
        self.assertEqual([item.item_id for item in result], ["one", "many"])

    def test_sort_is_stable(self) -> None:
        items = [make_item("b", size=10), make_item("a", size=10)]
        result = viewmodel.sort_items(items, "size")
        self.assertEqual([item.item_id for item in result], ["b", "a"])


class HelperTests(unittest.TestCase):
    def test_category_counts(self) -> None:
        items = [make_item("a"), make_item("b"), make_item("c", Category.CT)]
        counts = viewmodel.category_counts(items)
        self.assertEqual(counts[Category.PHOTO], 2)
        self.assertEqual(counts[Category.CT], 1)

    def test_series_members(self) -> None:
        items = [
            make_item("a", series="IMG (3 файли)"),
            make_item("b", series="IMG (3 файли)"),
            make_item("c"),
        ]
        members = viewmodel.series_members(items, "IMG (3 файли)")
        self.assertEqual([item.item_id for item in members], ["a", "b"])

    def test_row_tags(self) -> None:
        self.assertEqual(viewmodel.row_tag(make_item("d", Category.DUPLICATE)), "duplicate")
        self.assertEqual(viewmodel.row_tag(make_item("j", Category.JUNK)), "junk")
        self.assertEqual(viewmodel.row_tag(make_item("c", Category.CT)), "dicom")
        self.assertEqual(viewmodel.row_tag(make_item("r", Category.IMAGE_REVIEW)), "review")
        self.assertEqual(viewmodel.row_tag(make_item("p", Category.PHOTO)), "plain")

    def test_confidence_rank(self) -> None:
        self.assertLess(viewmodel.confidence_rank("high"), viewmodel.confidence_rank("medium"))
        self.assertLess(viewmodel.confidence_rank("medium"), viewmodel.confidence_rank("low"))


if __name__ == "__main__":
    unittest.main()
