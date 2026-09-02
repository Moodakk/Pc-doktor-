from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from dental_archive.i18n import set_language
from dental_archive.models import Action, Category, ScanItem
from dental_archive.operations import execute_plan
from dental_archive.reporting import build_statistics, write_html_report, write_scan_csv


def setUpModule() -> None:
    set_language("uk", persist=False)


def make_item(
    name: str,
    category: Category = Category.PHOTO,
    size: int = 1000,
    patient: str = "",
    selected: bool = False,
) -> ScanItem:
    return ScanItem(
        category=category,
        display_name=name,
        source_root=Path("/data"),
        paths=(Path("/data") / name,),
        total_size=size,
        reason="test reason",
        patient_name=patient,
        selected=selected,
    )


class StatisticsTests(unittest.TestCase):
    def test_aggregates_by_category_and_patient(self) -> None:
        items = [
            make_item("a.jpg", Category.PHOTO, 100, patient="Alpha"),
            make_item("b.jpg", Category.PHOTO, 200, patient="Alpha"),
            make_item("c.dcm", Category.CT, 5000, patient="Beta"),
            make_item("d.jpg", Category.DUPLICATE, 300),
            make_item("junk.tmp", Category.JUNK, 50),
        ]
        stats = build_statistics(items, ["warning-1"])
        self.assertEqual(stats.total_items, 5)
        self.assertEqual(stats.total_size, 5650)
        self.assertEqual(stats.by_category[Category.PHOTO].items, 2)
        self.assertEqual(stats.by_category[Category.PHOTO].size, 300)
        self.assertEqual(stats.by_patient["Alpha"].items, 2)
        self.assertEqual(stats.duplicate_items, 1)
        self.assertEqual(stats.reclaimable_bytes, 300)
        self.assertEqual(stats.junk_bytes, 50)
        self.assertEqual(stats.warnings, ["warning-1"])


class CsvExportTests(unittest.TestCase):
    def test_writes_utf8_bom_and_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "scan.csv"
            write_scan_csv([make_item("smile.jpg", patient="Пацієнт Один", selected=True)], target)
            raw = target.read_bytes()
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
            with target.open("r", encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.reader(stream, delimiter=";"))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0][0], "Категорія")
            self.assertIn("smile.jpg", rows[1])
            self.assertIn("Пацієнт Один", rows[1])


class HtmlReportTests(unittest.TestCase):
    def test_html_is_self_contained_and_escaped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "report.html"
            items = [
                make_item("a.jpg", Category.PHOTO, 100, patient="<Alpha> & Co"),
                make_item("dup.jpg", Category.DUPLICATE, 400),
            ]
            write_html_report(items, target, warnings=["<b>warn</b>"])
            text = target.read_text(encoding="utf-8")
            self.assertIn("<!DOCTYPE html>", text)
            self.assertNotIn("<Alpha>", text)
            self.assertIn("&lt;Alpha&gt; &amp; Co", text)
            self.assertNotIn("<b>warn</b>", text)
            self.assertIn("&lt;b&gt;warn&lt;/b&gt;", text)
            self.assertNotIn("http://", text)
            self.assertNotIn("https://", text)


class ManifestTests(unittest.TestCase):
    def test_manifest_contains_version_sources_and_totals(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source_root = base / "source"
            source_root.mkdir()
            source = source_root / "photo.jpg"
            source.write_bytes(b"data")
            item = ScanItem(
                category=Category.PHOTO,
                display_name="photo.jpg",
                source_root=source_root,
                paths=(source,),
                total_size=4,
                reason="test",
                action=Action.COPY,
                selected=True,
            )
            summary = execute_plan([item], base / "dest", trash_function=lambda _path: None, sources=[source_root])
            payload = json.loads(summary.manifest_path.read_text(encoding="utf-8"))
            self.assertIn("app_version", payload)
            self.assertEqual(payload["sources"], [str(source_root)])
            self.assertEqual(payload["destination"], str((base / "dest").resolve()))
            self.assertEqual(payload["action_totals"], {"copy": 1})
            csv_twin = summary.manifest_path.with_suffix(".csv")
            self.assertTrue(csv_twin.exists())
            with csv_twin.open("r", encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.reader(stream, delimiter=";"))
            self.assertEqual(rows[0][0], "item_id")
            self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main()
