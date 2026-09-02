from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from dental_archive.i18n import set_language
from dental_archive.models import Category
from dental_archive.scanner import ScanPhase, scan_roots
from tests.helpers import write_test_dicom


def setUpModule() -> None:
    set_language("uk", persist=False)


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
            self.assertGreater(report.files_hashed, 0)
            self.assertGreaterEqual(report.elapsed_seconds, 0.0)

    def test_same_prefix_different_tail_is_not_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shared_prefix = b"P" * (70 * 1024)
            (root / "one.png").write_bytes(shared_prefix + b"tail-one")
            (root / "two.png").write_bytes(shared_prefix + b"tail-two")
            report = scan_roots([root], detect_duplicates=True)
            self.assertGreater(report.files_hashed, 0)
            duplicates = [item for item in report.items if item.category == Category.DUPLICATE]
            self.assertEqual(duplicates, [])

    def test_dicomdir_attaches_to_study_group(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "DICOM_MEDIA"
            series = media / "SERIES1"
            series.mkdir(parents=True)
            study = write_test_dicom(series / "ct001.dcm", modality="CT")
            write_test_dicom(series / "ct002.dcm", modality="CT", study_uid=study)
            write_test_dicom(media / "DICOMDIR", modality="", sop_class_uid="1.2.840.10008.1.3.10")

            report = scan_roots([root], detect_duplicates=False)
            dicom_items = [item for item in report.items if "modalities" in item.metadata]
            self.assertEqual(len(dicom_items), 1)
            self.assertEqual(dicom_items[0].category, Category.CT)
            names = {path.name for path in dicom_items[0].paths}
            self.assertIn("DICOMDIR", names)
            self.assertEqual(dicom_items[0].file_count, 3)

    def test_parallel_and_sequential_paths_agree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in range(70):
                (root / f"IMG_{index:03d}.jpg").write_bytes(b"\xff\xd8\xff\xe0" + bytes([index]) * 8)
            (root / "dup1.stl").write_bytes(b"identical")
            (root / "dup2.stl").write_bytes(b"identical")
            study = write_test_dicom(root / "ct1.dcm", modality="CT")
            write_test_dicom(root / "ct2.dcm", modality="CT", study_uid=study)

            parallel = scan_roots([root], detect_duplicates=True, max_workers=4)
            sequential = scan_roots([root], detect_duplicates=True, max_workers=1)
            self.assertEqual(
                [(item.category, item.display_name, item.paths) for item in parallel.items],
                [(item.category, item.display_name, item.paths) for item in sequential.items],
            )
            self.assertEqual(parallel.files_seen, sequential.files_seen)
            self.assertEqual(parallel.bytes_seen, sequential.bytes_seen)

    def test_cancel_event_stops_hashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in range(6):
                (root / f"copy_{index}.stl").write_bytes(b"solid tooth\n facet normal 0 0 0\n")
            cancel = threading.Event()
            hashed: list[str] = []

            def phase_progress(phase: str, done: int, total: int | None, detail: str) -> None:
                if phase == ScanPhase.HASHING:
                    hashed.append(detail)
                    cancel.set()

            report = scan_roots([root], detect_duplicates=True, cancel_event=cancel, phase_progress=phase_progress)
            self.assertTrue(report.cancelled)
            duplicates = [item for item in report.items if item.category == Category.DUPLICATE]
            self.assertEqual(duplicates, [])


if __name__ == "__main__":
    unittest.main()
