from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dental_archive.classifier import classify_dicom, classify_regular_file, read_dicom_info
from dental_archive.models import Action, Category
from tests.helpers import write_test_dicom


class ClassifierTests(unittest.TestCase):
    def test_dicom_ct_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "slice001.dcm"
            write_test_dicom(path, modality="CT")
            info = read_dicom_info(path)
            self.assertTrue(info.is_dicom)
            self.assertEqual(info.modality, "CT")
            self.assertEqual(info.patient_name, "Test Patient")
            self.assertEqual(classify_dicom(info).category, Category.CT)

    def test_dicom_xray_modality(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "image.dcm"
            write_test_dicom(path, modality="DX")
            self.assertEqual(classify_dicom(read_dicom_info(path)).category, Category.XRAY)

    def test_regular_image_keywords(self) -> None:
        xray = classify_regular_file(Path("Patient/RVG/tooth_16.jpg"), 100)
        photo = classify_regular_file(Path("Patient/Photos/smile.jpg"), 100)
        unknown = classify_regular_file(Path("Downloads/misc/image01.jpg"), 100)
        self.assertEqual(xray.category, Category.XRAY)
        self.assertEqual(photo.category, Category.PHOTO)
        self.assertEqual(unknown.category, Category.IMAGE_REVIEW)

    def test_cleanup_candidates_are_not_preselected(self) -> None:
        result = classify_regular_file(Path("download.crdownload"), 10)
        self.assertEqual(result.category, Category.JUNK)
        self.assertEqual(result.suggested_action, Action.QUARANTINE)

    def test_zero_byte_is_cleanup_candidate(self) -> None:
        result = classify_regular_file(Path("empty.any"), 0)
        self.assertEqual(result.category, Category.JUNK)


if __name__ == "__main__":
    unittest.main()
