from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dental_archive.models import Action, Category, ScanItem
from dental_archive.operations import execute_plan, sanitize_component, sha256_file


class OperationTests(unittest.TestCase):
    def _item(self, source_root: Path, file: Path, action: Action) -> ScanItem:
        return ScanItem(
            category=Category.PHOTO,
            display_name=file.name,
            source_root=source_root,
            paths=(file,),
            total_size=file.stat().st_size,
            reason="test",
            action=action,
            selected=True,
        )

    def test_copy_is_verified_and_manifest_written(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source_root = base / "source"
            destination = base / "external"
            source_root.mkdir()
            source = source_root / "photo.jpg"
            source.write_bytes(b"patient-photo")
            summary = execute_plan([self._item(source_root, source, Action.COPY)], destination, trash_function=lambda _path: None)
            self.assertEqual(summary.failed, 0)
            self.assertEqual(summary.succeeded, 1)
            copied = Path(summary.records[0].destination)
            self.assertTrue(copied.exists())
            self.assertEqual(sha256_file(source), sha256_file(copied))
            self.assertTrue(summary.manifest_path and summary.manifest_path.exists())
            payload = json.loads(summary.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["failed"], 0)

    def test_move_trashes_only_after_verified_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source_root = base / "source"
            destination = base / "external"
            source_root.mkdir()
            source = source_root / "scan.jpg"
            source.write_bytes(b"scan-data")
            trashed: list[str] = []

            def fake_trash(path: str) -> None:
                trashed.append(path)
                Path(path).unlink()

            summary = execute_plan([self._item(source_root, source, Action.MOVE)], destination, trash_function=fake_trash)
            self.assertEqual(summary.failed, 0)
            self.assertEqual(trashed, [str(source)])
            self.assertFalse(source.exists())
            self.assertTrue(Path(summary.records[0].destination).exists())

    def test_unchecked_item_is_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source_root = base / "source"
            source_root.mkdir()
            source = source_root / "keep.jpg"
            source.write_bytes(b"keep")
            item = self._item(source_root, source, Action.TRASH)
            item.selected = False
            summary = execute_plan([item], base / "external", trash_function=lambda path: Path(path).unlink())
            self.assertTrue(source.exists())
            self.assertEqual(summary.records, [])

    def test_sanitizes_windows_reserved_name(self) -> None:
        self.assertEqual(sanitize_component("CON"), "_CON")
        self.assertNotIn(":", sanitize_component("Patient: One"))


if __name__ == "__main__":
    unittest.main()
