"""Content-based file type detection.

Determines the real format of a file from magic-byte signatures instead of
trusting the file extension. This lets the classifier recognise files with a
missing or wrong extension and flag extension/content mismatches.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path


class Kind:
    IMAGE = "image"
    DOCUMENT = "document"
    ARCHIVE = "archive"
    MODEL_3D = "model_3d"
    VIDEO = "video"


@dataclass(frozen=True, slots=True)
class SniffResult:
    format_name: str
    kind: str


_HEADER_SIZE = 512

# (format_name, kind, offset, signature bytes)
_SIGNATURES: tuple[tuple[str, str, int, bytes], ...] = (
    ("jpeg", Kind.IMAGE, 0, b"\xff\xd8\xff"),
    ("png", Kind.IMAGE, 0, b"\x89PNG\r\n\x1a\n"),
    ("gif", Kind.IMAGE, 0, b"GIF87a"),
    ("gif", Kind.IMAGE, 0, b"GIF89a"),
    ("bmp", Kind.IMAGE, 0, b"BM"),
    ("tiff", Kind.IMAGE, 0, b"II*\x00"),
    ("tiff", Kind.IMAGE, 0, b"MM\x00*"),
    ("pdf", Kind.DOCUMENT, 0, b"%PDF"),
    ("rtf", Kind.DOCUMENT, 0, b"{\\rtf"),
    ("ole2", Kind.DOCUMENT, 0, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"),
    ("zip", Kind.ARCHIVE, 0, b"PK\x03\x04"),
    ("rar", Kind.ARCHIVE, 0, b"Rar!\x1a\x07"),
    ("7z", Kind.ARCHIVE, 0, b"7z\xbc\xaf\x27\x1c"),
    ("gzip", Kind.ARCHIVE, 0, b"\x1f\x8b"),
    ("bzip2", Kind.ARCHIVE, 0, b"BZh"),
    ("xz", Kind.ARCHIVE, 0, b"\xfd7zXZ\x00"),
    ("tar", Kind.ARCHIVE, 257, b"ustar"),
    ("ply", Kind.MODEL_3D, 0, b"ply\n"),
    ("ply", Kind.MODEL_3D, 0, b"ply\r\n"),
    ("vrml", Kind.MODEL_3D, 0, b"#VRML"),
    ("avi", Kind.VIDEO, 8, b"AVI "),
    ("mkv", Kind.VIDEO, 0, b"\x1a\x45\xdf\xa3"),
    ("wmv", Kind.VIDEO, 0, b"\x30\x26\xb2\x75"),
)

# Which sniffed formats are legitimate for each extension. An extension whose
# real content matches any listed format is *not* a mismatch (e.g. .docx is a
# ZIP container, .tif and .tiff are the same format).
EXTENSION_FORMATS: dict[str, frozenset[str]] = {
    ".jpg": frozenset({"jpeg"}),
    ".jpeg": frozenset({"jpeg"}),
    ".png": frozenset({"png"}),
    ".gif": frozenset({"gif"}),
    ".bmp": frozenset({"bmp"}),
    ".tif": frozenset({"tiff"}),
    ".tiff": frozenset({"tiff"}),
    ".webp": frozenset({"webp"}),
    ".heic": frozenset({"heif"}),
    ".heif": frozenset({"heif"}),
    ".pdf": frozenset({"pdf"}),
    ".rtf": frozenset({"rtf"}),
    ".doc": frozenset({"ole2"}),
    ".xls": frozenset({"ole2"}),
    ".docx": frozenset({"zip"}),
    ".xlsx": frozenset({"zip"}),
    ".odt": frozenset({"zip"}),
    ".zip": frozenset({"zip"}),
    ".rar": frozenset({"rar"}),
    ".7z": frozenset({"7z"}),
    ".gz": frozenset({"gzip"}),
    ".tgz": frozenset({"gzip"}),
    ".tar": frozenset({"tar"}),
    ".stl": frozenset({"stl"}),
    ".ply": frozenset({"ply"}),
    ".wrl": frozenset({"vrml"}),
    ".vrml": frozenset({"vrml"}),
    ".3mf": frozenset({"zip"}),
    ".mp4": frozenset({"mp4"}),
    ".m4v": frozenset({"mp4"}),
    ".mov": frozenset({"mp4"}),
    ".avi": frozenset({"avi"}),
    ".mkv": frozenset({"mkv"}),
    ".wmv": frozenset({"wmv"}),
}


def _sniff_riff(header: bytes) -> SniffResult | None:
    if header.startswith(b"RIFF") and len(header) >= 12:
        if header[8:12] == b"WEBP":
            return SniffResult("webp", Kind.IMAGE)
        if header[8:12] == b"AVI ":
            return SniffResult("avi", Kind.VIDEO)
    return None


def _sniff_iso_media(header: bytes) -> SniffResult | None:
    # MP4/MOV/HEIC share the ISO base media container: "ftyp" at offset 4.
    if len(header) >= 12 and header[4:8] == b"ftyp":
        brand = header[8:12]
        if brand in {b"heic", b"heix", b"hevc", b"mif1", b"msf1"}:
            return SniffResult("heif", Kind.IMAGE)
        return SniffResult("mp4", Kind.VIDEO)
    return None


def _sniff_stl(header: bytes, size: int) -> SniffResult | None:
    # Binary STL: 80-byte header + uint32 triangle count; the file size must
    # match 84 + 50 * count exactly, which makes false positives unlikely.
    if size >= 84 and len(header) >= 84:
        (count,) = struct.unpack_from("<I", header, 80)
        if size == 84 + count * 50:
            return SniffResult("stl", Kind.MODEL_3D)
    # ASCII STL: starts with "solid" and mentions "facet" in the header.
    if header[:5].lower() == b"solid" and b"facet" in header.lower():
        return SniffResult("stl", Kind.MODEL_3D)
    return None


def sniff_format(path: Path, size: int | None = None) -> SniffResult | None:
    """Detect the real file format from its first bytes.

    Returns None when the content is unreadable or does not match any known
    signature (plain text and unknown binary formats stay undetected).
    """
    try:
        if size is None:
            size = path.stat().st_size
        if size <= 0:
            return None
        with path.open("rb") as stream:
            header = stream.read(_HEADER_SIZE)
    except OSError:
        return None
    if not header:
        return None

    for result in (_sniff_riff(header), _sniff_iso_media(header), _sniff_stl(header, size)):
        if result:
            return result

    for format_name, kind, offset, signature in _SIGNATURES:
        if header[offset : offset + len(signature)] == signature:
            # "BM" alone is too weak: confirm the BMP size field is plausible.
            if format_name == "bmp":
                if len(header) < 6:
                    continue
                (declared,) = struct.unpack_from("<I", header, 2)
                if declared != size:
                    continue
            return SniffResult(format_name, kind)
    return None


def extension_matches(extension: str, sniffed: SniffResult) -> bool:
    """True when the sniffed content is legitimate for the given extension."""
    expected = EXTENSION_FORMATS.get(extension)
    return expected is not None and sniffed.format_name in expected
