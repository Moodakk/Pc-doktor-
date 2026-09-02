from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from dental_archive.classifier import classify_dicom, classify_regular_file, read_dicom_info
from dental_archive.i18n import set_language
from dental_archive.models import Action, Category
from tests.helpers import write_test_dicom


def setUpModule() -> None:
    set_language("uk", persist=False)


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

    def test_extensionless_jpeg_detected_by_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "export_0012"
            path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 32)
            result = classify_regular_file(path)
            self.assertEqual(result.category, Category.IMAGE_REVIEW)
            self.assertIn("сигнатурою", result.reason)

    def test_wrong_extension_is_reclassified_by_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notes.doc"
            path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 32)
            result = classify_regular_file(path)
            self.assertEqual(result.category, Category.IMAGE_REVIEW)
            self.assertIn("не відповідає вмісту", result.reason)

    def test_docx_zip_container_is_not_a_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.docx"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("word/document.xml", "<xml/>")
            result = classify_regular_file(path)
            self.assertEqual(result.category, Category.DOCUMENT)
            self.assertNotIn("не відповідає", result.reason)

    def test_renamed_dicom_keyword_still_wins_for_content_image(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "RVG"
            folder.mkdir()
            path = folder / "tooth.dat"
            path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 32)
            result = classify_regular_file(path)
            self.assertEqual(result.category, Category.XRAY)

    def test_video_extension_gets_video_category(self) -> None:
        result = classify_regular_file(Path("intraoral.mp4"), 100)
        self.assertEqual(result.category, Category.VIDEO)
        self.assertEqual(result.suggested_action, Action.KEEP)
        self.assertIn("Відеофайл", result.reason)
        for extension in (".mpg", ".3gp", ".flv", ".webm"):
            self.assertEqual(classify_regular_file(Path(f"clip{extension}"), 100).category, Category.VIDEO)

    def test_volume_extensions_go_to_ct(self) -> None:
        for name in ("scan.nrrd", "scan.nii", "scan.mha", "scan.mhd", "scan.vtk"):
            result = classify_regular_file(Path(name), 100)
            self.assertEqual(result.category, Category.CT, name)
            self.assertEqual(result.confidence, "medium", name)
            self.assertEqual(result.suggested_action, Action.COPY, name)

    def test_compressed_nifti_double_extension(self) -> None:
        result = classify_regular_file(Path("volume.nii.gz"), 100)
        self.assertEqual(result.category, Category.CT)
        self.assertIn(".nii.gz", result.reason)

    def test_volume_signature_without_extension(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "export_volume"
            path.write_bytes(b"NRRD0004\n# Complete NRRD file format\n" + b"\x00" * 16)
            result = classify_regular_file(path)
            self.assertEqual(result.category, Category.CT)
            self.assertIn("nrrd", result.reason)

    def test_dicom_structured_report_is_document_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.dcm"
            write_test_dicom(path, modality="SR")
            result = classify_dicom(read_dicom_info(path))
            self.assertEqual(result.category, Category.DICOM_OTHER)
            self.assertIn("DICOM-обгортці", result.reason)

    def test_dicom_encapsulated_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.dcm"
            write_test_dicom(path, modality="OT", sop_class_uid="1.2.840.10008.5.1.4.1.1.104.1")
            info = read_dicom_info(path)
            self.assertEqual(info.sop_class_uid, "1.2.840.10008.5.1.4.1.1.104.1")
            result = classify_dicom(info)
            self.assertEqual(result.category, Category.DICOM_OTHER)
            self.assertIn("PDF", result.reason)

    def test_dicom_ultrasound_and_mri_named_in_reason(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for modality in ("US", "MR"):
                path = Path(directory) / f"{modality.lower()}.dcm"
                write_test_dicom(path, modality=modality)
                result = classify_dicom(read_dicom_info(path))
                self.assertEqual(result.category, Category.DICOM_OTHER)
                self.assertIn(modality, result.reason)


if __name__ == "__main__":
    unittest.main()
