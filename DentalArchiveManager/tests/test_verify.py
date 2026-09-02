from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from dental_archive.models import Action, Category, ScanItem
from dental_archive.operations import execute_plan
from dental_archive.verify import (
    STATUS_MISMATCH,
    STATUS_MISSING,
    STATUS_OK,
    find_manifests,
    verify_archive,
    write_verify_report_text,
)


def _run_copy(base: Path, names: list[str]) -> Path:
    source_root = base / "source"
    source_root.mkdir(exist_ok=True)
    items = []
    for name in names:
        source = source_root / name
        source.write_bytes(f"content-{name}".encode())
        items.append(
            ScanItem(
                category=Category.PHOTO,
                display_name=name,
                source_root=source_root,
                paths=(source,),
                total_size=source.stat().st_size,
                reason="test",
                action=Action.COPY,
                selected=True,
            )
        )
    destination = base / "dest"
    execute_plan(items, destination, trash_function=lambda _path: None)
    return destination.resolve()


class VerifyTests(unittest.TestCase):
    def test_all_ok_after_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = _run_copy(Path(directory), ["a.jpg", "b.jpg"])
            manifests = find_manifests(destination)
            self.assertEqual(len(manifests), 1)
            report = verify_archive(destination)
            self.assertEqual(report.total, 2)
            self.assertEqual(report.ok, 2)
            self.assertEqual(report.mismatched, 0)
            self.assertEqual(report.missing, 0)

    def test_detects_tampered_and_missing_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = _run_copy(Path(directory), ["a.jpg", "b.jpg", "c.jpg"])
            report = verify_archive(destination)
            copies = sorted(record.destination for record in report.records)
            Path(copies[0]).write_bytes(b"tampered!")
            Path(copies[1]).unlink()

            report = verify_archive(destination)
            statuses = {Path(record.destination).name: record.status for record in report.records}
            self.assertEqual(report.total, 3)
            self.assertEqual(report.mismatched, 1)
            self.assertEqual(report.missing, 1)
            self.assertEqual(report.ok, 1)
            self.assertIn(STATUS_MISMATCH, statuses.values())
            self.assertIn(STATUS_MISSING, statuses.values())
            self.assertIn(STATUS_OK, statuses.values())

            target = Path(directory) / "verify.txt"
            write_verify_report_text(report, target)
            text = target.read_text(encoding="utf-8")
            self.assertIn("mismatch: 1", text)
            self.assertIn("missing: 1", text)

    def test_progress_and_cancel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = _run_copy(Path(directory), ["a.jpg", "b.jpg", "c.jpg"])
            cancel = threading.Event()
            seen: list[str] = []

            def progress(done: int, total: int, path: str) -> None:
                seen.append(path)
                cancel.set()

            report = verify_archive(destination, progress=progress, cancel_event=cancel)
            self.assertTrue(report.cancelled)
            self.assertEqual(len(seen), 1)

    def test_no_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = verify_archive(Path(directory))
            self.assertEqual(report.manifests, [])
            self.assertEqual(report.total, 0)


if __name__ == "__main__":
    unittest.main()
