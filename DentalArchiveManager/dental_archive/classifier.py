from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .filetype import Kind, SniffResult, extension_matches, sniff_format
from .i18n import tr
from .models import Action, Category, DicomInfo

try:
    import pydicom
    from pydicom.errors import InvalidDicomError
except ImportError:  # The app still starts and explains how to enable deep DICOM scan.
    pydicom = None

    class InvalidDicomError(Exception):
        pass


IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".gif",
    ".tif",
    ".tiff",
    ".webp",
    ".heic",
    ".heif",
}
MODEL_EXTENSIONS = {".stl", ".obj", ".ply", ".off", ".3mf", ".wrl", ".vrml"}
DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".csv",
    ".txt",
    ".rtf",
    ".odt",
}
ARCHIVE_EXTENSIONS = {".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".iso"}
VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".avi", ".mkv", ".wmv", ".mpg", ".mpeg", ".3gp", ".flv", ".webm"}
VOLUME_EXTENSIONS = {".nii", ".nrrd", ".mha", ".mhd", ".vtk"}
TEMP_EXTENSIONS = {".tmp", ".temp", ".part", ".crdownload", ".download", ".dmp", ".chk"}
JUNK_FILENAMES = {"thumbs.db", "desktop.ini", ".ds_store"}

KNOWN_EXTENSIONS = (
    IMAGE_EXTENSIONS
    | MODEL_EXTENSIONS
    | DOCUMENT_EXTENSIONS
    | ARCHIVE_EXTENSIONS
    | VIDEO_EXTENSIONS
    | VOLUME_EXTENSIONS
    | {".xml", ".json", ".html", ".htm", ".dcm", ".dicom"}
)

CT_MODALITIES = {"CT", "CBCT"}
XRAY_MODALITIES = {"DX", "CR", "DR", "IO", "PX", "RF", "XA", "MG", "OP", "PAN"}
# Modalities that wrap documents/reports rather than images.
DOCUMENT_MODALITIES = {"SR", "DOC", "KO"}
ENCAPSULATED_PDF_SOP_CLASS = "1.2.840.10008.5.1.4.1.1.104.1"
MEDIA_DIRECTORY_SOP_CLASS = "1.2.840.10008.1.3.10"

XRAY_KEYWORDS = {
    "xray",
    "x-ray",
    "rentgen",
    "рентген",
    "rtg",
    "rvg",
    "bitewing",
    "periapical",
    "intraoral x",
    "opg",
    "ortho",
    "panorama",
    "panoramic",
    "ceph",
    "cephalometric",
    "telerentgen",
}
CT_KEYWORDS = {"cbct", "dicom", "cone beam", "tomograph", "томограф", "кт ", "ct scan"}
PHOTO_KEYWORDS = {
    "photo",
    "photos",
    "foto",
    "фото",
    "patient",
    "пацієнт",
    "pacient",
    "intraoral",
    "extraoral",
    "before",
    "after",
    "smile",
    "portrait",
    "occlusal",
}


@dataclass(frozen=True, slots=True)
class FileClassification:
    category: Category
    reason: str
    confidence: str
    suggested_action: Action = Action.KEEP


def normalized_path_text(path: Path) -> str:
    return " ".join(part.casefold().replace("_", " ").replace("-", " ") for part in path.parts)


def contains_keyword(text: str, keywords: set[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def looks_like_dicom(path: Path) -> bool:
    if path.suffix.casefold() in {".dcm", ".dicom"} or path.name.casefold() == "dicomdir":
        return True
    try:
        if path.stat().st_size < 132:
            return False
        with path.open("rb") as stream:
            stream.seek(128)
            return stream.read(4) == b"DICM"
    except OSError:
        return False


def read_dicom_info(path: Path) -> DicomInfo:
    if pydicom is None:
        return DicomInfo(is_dicom=looks_like_dicom(path), error=tr("reason.pydicom_missing"))

    # Do not probe every arbitrary file with force=True; it is slow and may produce false positives.
    candidate = looks_like_dicom(path) or path.suffix == ""
    if not candidate:
        return DicomInfo()

    tags = [
        "Modality",
        "StudyInstanceUID",
        "SeriesInstanceUID",
        "PatientName",
        "PatientID",
        "StudyDate",
        "StudyDescription",
        "SeriesDescription",
        "BodyPartExamined",
        "SOPClassUID",
    ]
    try:
        dataset = pydicom.dcmread(
            str(path),
            stop_before_pixels=True,
            specific_tags=tags,
            force=path.suffix == "" and not looks_like_dicom(path),
        )
    except (InvalidDicomError, OSError, ValueError) as exc:
        return DicomInfo(error=str(exc))

    # A forced parse without meaningful DICOM identifiers is not accepted as DICOM.
    if not any(hasattr(dataset, tag) for tag in ("SOPClassUID", "Modality", "StudyInstanceUID")):
        return DicomInfo()

    def value(name: str) -> str:
        raw = getattr(dataset, name, "")
        return str(raw).strip()

    return DicomInfo(
        is_dicom=True,
        modality=value("Modality").upper(),
        study_uid=value("StudyInstanceUID"),
        series_uid=value("SeriesInstanceUID"),
        patient_name=value("PatientName").replace("^", " ").strip(),
        patient_id=value("PatientID"),
        study_date=value("StudyDate"),
        study_description=value("StudyDescription"),
        series_description=value("SeriesDescription"),
        body_part=value("BodyPartExamined"),
        sop_class_uid=value("SOPClassUID"),
    )


def classify_dicom(info: DicomInfo) -> FileClassification:
    modality = info.modality.upper()
    descriptions = f"{info.study_description} {info.series_description}".casefold()
    if modality in CT_MODALITIES:
        return FileClassification(Category.CT, tr("reason.dicom_modality", modality=modality), "high", Action.COPY)
    if contains_keyword(descriptions, CT_KEYWORDS):
        return FileClassification(Category.CT, tr("reason.dicom_ct_description"), "high", Action.COPY)
    if modality in XRAY_MODALITIES:
        return FileClassification(Category.XRAY, tr("reason.dicom_modality", modality=modality), "high", Action.COPY)
    if contains_keyword(descriptions, XRAY_KEYWORDS):
        return FileClassification(Category.XRAY, tr("reason.dicom_xray_description"), "high", Action.COPY)
    if info.sop_class_uid == ENCAPSULATED_PDF_SOP_CLASS:
        return FileClassification(Category.DICOM_OTHER, tr("reason.dicom_encapsulated_pdf"), "high", Action.COPY)
    if info.sop_class_uid == MEDIA_DIRECTORY_SOP_CLASS:
        return FileClassification(Category.DICOM_OTHER, tr("reason.dicomdir"), "high", Action.COPY)
    if modality in DOCUMENT_MODALITIES:
        return FileClassification(
            Category.DICOM_OTHER, tr("reason.dicom_document", modality=modality), "high", Action.COPY
        )
    if modality:
        return FileClassification(Category.DICOM_OTHER, tr("reason.dicom_modality", modality=modality), "high", Action.COPY)
    return FileClassification(Category.DICOM_OTHER, tr("reason.dicom_unspecified"), "high", Action.COPY)


def _join_reason(base: str, note: str) -> str:
    return f"{base}; {note}" if note else base


def _classify_image(text: str, note: str = "") -> FileClassification:
    if contains_keyword(text, XRAY_KEYWORDS):
        return FileClassification(Category.XRAY, _join_reason(tr("reason.xray_keyword"), note), "medium", Action.COPY)
    if contains_keyword(text, PHOTO_KEYWORDS):
        return FileClassification(Category.PHOTO, _join_reason(tr("reason.photo_keyword"), note), "medium", Action.COPY)
    return FileClassification(
        Category.IMAGE_REVIEW,
        _join_reason(tr("reason.plain_image"), note),
        "low",
        Action.COPY,
    )


def _classify_by_content(sniffed: SniffResult, text: str, note: str) -> FileClassification:
    if sniffed.kind == Kind.IMAGE:
        return _classify_image(text, note)
    if sniffed.kind == Kind.MODEL_3D:
        return FileClassification(
            Category.MODEL_3D, _join_reason(tr("reason.model_3d_content", format=sniffed.format_name), note), "medium", Action.COPY
        )
    if sniffed.kind == Kind.DOCUMENT:
        return FileClassification(
            Category.DOCUMENT, _join_reason(tr("reason.document_content", format=sniffed.format_name), note), "medium", Action.COPY
        )
    if sniffed.kind == Kind.ARCHIVE:
        return FileClassification(
            Category.ARCHIVE,
            _join_reason(tr("reason.archive_content", format=sniffed.format_name), note),
            "medium",
            Action.COPY,
        )
    if sniffed.kind == Kind.VOLUME:
        return FileClassification(
            Category.CT, _join_reason(tr("reason.volume_content", format=sniffed.format_name), note), "medium", Action.COPY
        )
    return FileClassification(
        Category.VIDEO, _join_reason(tr("reason.video_content", format=sniffed.format_name), note), "medium", Action.KEEP
    )


def classify_regular_file(path: Path, size: int | None = None) -> FileClassification:
    name = path.name.casefold()
    extension = path.suffix.casefold()
    text = normalized_path_text(path)
    if size is None:
        try:
            size = path.stat().st_size
        except OSError:
            size = -1

    if size == 0:
        return FileClassification(Category.JUNK, tr("reason.empty_file"), "high", Action.QUARANTINE)
    if name in JUNK_FILENAMES or name.startswith("~$"):
        return FileClassification(Category.JUNK, tr("reason.system_temp_file"), "high", Action.QUARANTINE)
    if extension in TEMP_EXTENSIONS:
        return FileClassification(Category.JUNK, tr("reason.temp_extension", extension=extension), "high", Action.QUARANTINE)

    # Compressed NIfTI volumes carry a double extension, so check the name first.
    if name.endswith(".nii.gz"):
        return FileClassification(Category.CT, tr("reason.volume_extension", extension=".nii.gz"), "medium", Action.COPY)

    # The real content decides when the extension is missing, unknown or lies.
    sniffed = sniff_format(path, size if size >= 0 else None)
    if sniffed and not extension_matches(extension, sniffed):
        if not extension:
            note = tr("note.no_extension", format=sniffed.format_name)
        elif extension in KNOWN_EXTENSIONS:
            note = tr("note.extension_mismatch", extension=extension, format=sniffed.format_name)
        else:
            note = tr("note.unknown_extension", extension=extension, format=sniffed.format_name)
        return _classify_by_content(sniffed, text, note)

    if extension in IMAGE_EXTENSIONS:
        return _classify_image(text)

    if extension in MODEL_EXTENSIONS:
        return FileClassification(Category.MODEL_3D, tr("reason.model_3d_extension", extension=extension), "high", Action.COPY)
    if extension in VOLUME_EXTENSIONS:
        return FileClassification(Category.CT, tr("reason.volume_extension", extension=extension), "medium", Action.COPY)
    if extension in DOCUMENT_EXTENSIONS:
        return FileClassification(Category.DOCUMENT, tr("reason.document_extension", extension=extension), "high", Action.COPY)
    if extension in ARCHIVE_EXTENSIONS:
        if contains_keyword(text, CT_KEYWORDS | XRAY_KEYWORDS):
            return FileClassification(Category.ARCHIVE, tr("reason.archive_ct_keywords"), "medium", Action.COPY)
        return FileClassification(Category.ARCHIVE, tr("reason.archive_extension", extension=extension), "medium", Action.COPY)
    if extension in VIDEO_EXTENSIONS:
        return FileClassification(Category.VIDEO, tr("reason.video_extension", extension=extension), "medium", Action.KEEP)

    # Export formats commonly found near scanners and dental software.
    if extension in {".xml", ".json", ".html", ".htm"}:
        return FileClassification(Category.DOCUMENT, tr("reason.export_format", extension=extension), "medium", Action.COPY)

    if extension in {".dcm", ".dicom"}:
        return FileClassification(Category.OTHER, tr("reason.dcm_unreadable"), "low", Action.KEEP)

    if re.search(r"(?:cache|temp|tmp)", text) and extension not in {".dcm", ".dicom"}:
        return FileClassification(Category.JUNK, tr("reason.cache_folder"), "low", Action.KEEP)

    return FileClassification(Category.OTHER, tr("reason.unknown_type"), "low", Action.KEEP)
