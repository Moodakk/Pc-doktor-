from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dental_archive.models import Category
from dental_archive.scanner import scan_roots
from tests.helpers import write_test_dicom

JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 32


class StudyContextTests(unittest.TestCase):
    def test_photo_next_to_study_inherits_patient(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patient = root / "Ivanov"
            (patient / "CT").mkdir(parents=True)
            write_test_dicom(patient / "CT" / "slice001.dcm", modality="CT")
            (patient / "CT" / "smile.jpg").write_bytes(JPEG_BYTES)

            report = scan_roots([root], detect_duplicates=False)
            study = next(item for item in report.items if item.category == Category.CT)
            photo = next(item for item in report.items if item.primary_path.name == "smile.jpg")

            self.assertEqual(photo.patient_name, study.patient_name)
            self.assertTrue(any(link["item_id"] == study.item_id for link in photo.links))
            self.assertTrue(any(link["item_id"] == photo.item_id for link in study.links))
            self.assertIn("patient_context", photo.metadata)

    def test_sibling_folder_is_linked_via_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patient = root / "Petrenko"
            (patient / "DICOM").mkdir(parents=True)
            (patient / "Docs").mkdir()
            write_test_dicom(patient / "DICOM" / "ct.dcm", modality="CT")
            (patient / "Docs" / "plan.pdf").write_bytes(b"%PDF-1.4 test")

            report = scan_roots([root], detect_duplicates=False)
            study = next(item for item in report.items if item.category == Category.CT)
            document = next(item for item in report.items if item.primary_path.name == "plan.pdf")

            self.assertTrue(any(link["item_id"] == study.item_id for link in document.links))
            self.assertEqual(document.patient_name, study.patient_name)

    def test_unrelated_file_not_linked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "PatientA").mkdir()
            (root / "Elsewhere").mkdir()
            write_test_dicom(root / "PatientA" / "ct.dcm", modality="CT")
            (root / "Elsewhere" / "note.pdf").write_bytes(b"%PDF-1.4 test")

            report = scan_roots([root], detect_duplicates=False)
            document = next(item for item in report.items if item.primary_path.name == "note.pdf")
            self.assertEqual(document.links, [])
            self.assertEqual(document.patient_name, "")


class SidecarTests(unittest.TestCase):
    def test_same_stem_files_are_linked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scan.stl").write_bytes(b"solid tooth\n facet normal 0 0 0\n")
            (root / "scan.pdf").write_bytes(b"%PDF-1.4 report")

            report = scan_roots([root], detect_duplicates=False)
            model = next(item for item in report.items if item.primary_path.suffix == ".stl")
            document = next(item for item in report.items if item.primary_path.suffix == ".pdf")
            self.assertTrue(any(link["item_id"] == document.item_id for link in model.links))
            self.assertTrue(any(link["item_id"] == model.item_id for link in document.links))


class SeriesTests(unittest.TestCase):
    def test_numbered_images_become_series(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in range(1, 5):
                (root / f"IMG_{index:03d}.jpg").write_bytes(JPEG_BYTES + bytes([index]))
            (root / "single.jpg").write_bytes(JPEG_BYTES + b"\xaa")

            report = scan_roots([root], detect_duplicates=False)
            members = [item for item in report.items if item.primary_path.name.startswith("IMG_")]
            single = next(item for item in report.items if item.primary_path.name == "single.jpg")

            self.assertEqual(len(members), 4)
            for member in members:
                self.assertIn("series", member.metadata)
                self.assertIn("4 файлів", member.metadata["series"])
            self.assertNotIn("series", single.metadata)

    def test_duplicates_are_linked_to_original(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a").mkdir()
            (root / "b").mkdir()
            (root / "a" / "scan.stl").write_bytes(b"same-model")
            (root / "b" / "scan-copy.stl").write_bytes(b"same-model")

            report = scan_roots([root], detect_duplicates=True)
            duplicate = next(item for item in report.items if item.category == Category.DUPLICATE)
            original = next(item for item in report.items if item.category != Category.DUPLICATE)
            self.assertTrue(any(link["item_id"] == original.item_id for link in duplicate.links))
            self.assertTrue(any(link["item_id"] == duplicate.item_id for link in original.links))


if __name__ == "__main__":
    unittest.main()
