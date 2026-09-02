from __future__ import annotations

import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

from dental_archive.filetype import Kind, extension_matches, sniff_format

JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 32
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
PDF_BYTES = b"%PDF-1.7\n%%EOF\n"


def binary_stl(triangles: int = 2) -> bytes:
    return b"\x00" * 80 + struct.pack("<I", triangles) + b"\x00" * (50 * triangles)


class FiletypeTests(unittest.TestCase):
    def _write(self, directory: str, name: str, payload: bytes) -> Path:
        path = Path(directory) / name
        path.write_bytes(payload)
        return path

    def test_detects_common_formats(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cases = {
                "photo.bin": (JPEG_BYTES, "jpeg", Kind.IMAGE),
                "graph.bin": (PNG_BYTES, "png", Kind.IMAGE),
                "report.bin": (PDF_BYTES, "pdf", Kind.DOCUMENT),
                "model.bin": (binary_stl(), "stl", Kind.MODEL_3D),
                "solid.bin": (b"solid tooth\n facet normal 0 0 0\n", "stl", Kind.MODEL_3D),
                "movie.bin": (b"FLV\x01" + b"\x00" * 16, "flv", Kind.VIDEO),
                "stream.bin": (b"\x00\x00\x01\xba" + b"\x00" * 16, "mpeg", Kind.VIDEO),
                "clip.bin": (b"\x1a\x45\xdf\xa3" + b"\x00" * 16, "matroska", Kind.VIDEO),
                "volume.bin": (b"NRRD0004\ntype: short\n", "nrrd", Kind.VOLUME),
                "mesh.bin": (b"# vtk DataFile Version 3.0\n", "vtk", Kind.VOLUME),
                "meta.bin": (b"ObjectType = Image\nNDims = 3\n", "metaimage", Kind.VOLUME),
            }
            for name, (payload, expected_format, expected_kind) in cases.items():
                result = sniff_format(self._write(directory, name, payload))
                self.assertIsNotNone(result, name)
                self.assertEqual(result.format_name, expected_format, name)
                self.assertEqual(result.kind, expected_kind, name)

    def test_detects_nifti_volume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            header = bytearray(352)
            header[0:4] = struct.pack("<I", 348)
            header[344:348] = b"n+1\x00"
            result = sniff_format(self._write(directory, "brain.bin", bytes(header)))
            self.assertIsNotNone(result)
            self.assertEqual(result.format_name, "nifti")
            self.assertEqual(result.kind, Kind.VOLUME)
            self.assertTrue(extension_matches(".nii", result))

    def test_detects_zip_container(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "container.bin"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("content.txt", "data")
            result = sniff_format(path)
            self.assertEqual(result.format_name, "zip")
            self.assertEqual(result.kind, Kind.ARCHIVE)

    def test_plain_text_stays_undetected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write(directory, "notes.txt", b"Just some plain notes.")
            self.assertIsNone(sniff_format(path))

    def test_missing_file_is_safe(self) -> None:
        self.assertIsNone(sniff_format(Path("does/not/exist.jpg")))

    def test_extension_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            jpeg = sniff_format(self._write(directory, "a.bin", JPEG_BYTES))
            self.assertTrue(extension_matches(".jpg", jpeg))
            self.assertFalse(extension_matches(".png", jpeg))
            self.assertFalse(extension_matches("", jpeg))
            with zipfile.ZipFile(Path(directory) / "report.docx", "w") as archive:
                archive.writestr("word/document.xml", "<xml/>")
            docx = sniff_format(Path(directory) / "report.docx")
            self.assertTrue(extension_matches(".docx", docx))

    def test_matroska_accepted_for_mkv_and_webm(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = sniff_format(self._write(directory, "clip.bin", b"\x1a\x45\xdf\xa3" + b"\x00" * 16))
            self.assertTrue(extension_matches(".mkv", result))
            self.assertTrue(extension_matches(".webm", result))
            self.assertFalse(extension_matches(".mp4", result))


if __name__ == "__main__":
    unittest.main()
