from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dental_archive.models import Category
from dental_archive.scanner import scan_roots
from tests.helpers import write_test_dicom


class ScannerTests(unittest.TestCase):
    def test_groups_dicom_study_and_classifies_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            study = write_test_dicom(root / "ct001.dcm", modality="CT")
            write_test_dicom(root / "ct002.dcm", modality="CT", study_uid=study)
            (root / "Photos").mkdir()
            (root / "Photos" / "smile.jpg").write_bytes(b"photo")
            (root / "RTG").mkdir()
            (root / "RTG" / "bitewing.png").write_bytes(b"xray")

            report = scan_roots([root], detect_duplicates=False)
            categories = [item.category for item in report.items]
            self.assertEqual(categories.count(Category.CT), 1)
            ct_item = next(item for item in report.items if item.category == Category.CT)
            self.assertEqual(ct_item.file_count, 2)
            self.assertIn(Category.PHOTO, categories)
            self.assertIn(Category.XRAY, categories)

    def test_marks_exact_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a").mkdir()
            (root / "b").mkdir()
            (root / "a" / "scan.stl").write_bytes(b"same-model")
            (root / "b" / "scan-copy.stl").write_bytes(b"same-model")
            report = scan_roots([root], detect_duplicates=True)
            duplicates = [item for item in report.items if item.category == Category.DUPLICATE]
            self.assertEqual(len(duplicates), 1)
            self.assertTrue(duplicates[0].duplicate_of)


if __name__ == "__main__":
    unittest.main()
