from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

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
TEMP_EXTENSIONS = {".tmp", ".temp", ".part", ".crdownload", ".download", ".dmp", ".chk"}
JUNK_FILENAMES = {"thumbs.db", "desktop.ini", ".ds_store"}

CT_MODALITIES = {"CT", "CBCT"}
XRAY_MODALITIES = {"DX", "CR", "DR", "IO", "PX", "RF", "XA", "MG", "OP", "PAN"}

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
        return DicomInfo(is_dicom=looks_like_dicom(path), error="pydicom не встановлено")

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
    )


def classify_dicom(info: DicomInfo) -> FileClassification:
    modality = info.modality.upper()
    descriptions = f"{info.study_description} {info.series_description}".casefold()
    if modality in CT_MODALITIES or contains_keyword(descriptions, CT_KEYWORDS):
        return FileClassification(Category.CT, f"DICOM modality: {modality or 'CT/CBCT description'}", "high", Action.COPY)
    if modality in XRAY_MODALITIES or contains_keyword(descriptions, XRAY_KEYWORDS):
        return FileClassification(Category.XRAY, f"DICOM modality: {modality or 'рентген-опис'}", "high", Action.COPY)
    return FileClassification(Category.DICOM_OTHER, f"DICOM modality: {modality or 'невказана'}", "high", Action.COPY)


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
        return FileClassification(Category.JUNK, "Порожній файл (0 байт)", "high", Action.QUARANTINE)
    if name in JUNK_FILENAMES or name.startswith("~$"):
        return FileClassification(Category.JUNK, "Системний або тимчасовий службовий файл", "high", Action.QUARANTINE)
    if extension in TEMP_EXTENSIONS:
        return FileClassification(Category.JUNK, f"Незавершений/тимчасовий файл {extension}", "high", Action.QUARANTINE)

    if extension in IMAGE_EXTENSIONS:
        if contains_keyword(text, XRAY_KEYWORDS):
            return FileClassification(Category.XRAY, "Назва або папка містить рентген-ознаку", "medium", Action.COPY)
        if contains_keyword(text, PHOTO_KEYWORDS):
            return FileClassification(Category.PHOTO, "Назва або папка містить ознаку фото пацієнта", "medium", Action.COPY)
        return FileClassification(
            Category.IMAGE_REVIEW,
            "Звичайне зображення без достатніх ознак типу",
            "low",
            Action.COPY,
        )

    if extension in MODEL_EXTENSIONS:
        return FileClassification(Category.MODEL_3D, f"Формат 3D-моделі {extension}", "high", Action.COPY)
    if extension in DOCUMENT_EXTENSIONS:
        return FileClassification(Category.DOCUMENT, f"Формат документа {extension}", "high", Action.COPY)
    if extension in ARCHIVE_EXTENSIONS:
        if contains_keyword(text, CT_KEYWORDS | XRAY_KEYWORDS):
            return FileClassification(Category.ARCHIVE, "Архів із КТ/рентген-ознаками у назві", "medium", Action.COPY)
        return FileClassification(Category.ARCHIVE, f"Архів {extension}; вміст не розпаковувався", "medium", Action.COPY)

    # Export formats commonly found near scanners and dental software.
    if extension in {".xml", ".json", ".html", ".htm"}:
        return FileClassification(Category.DOCUMENT, f"Службовий/описовий формат {extension}", "medium", Action.COPY)

    if re.search(r"(?:cache|temp|tmp)", text) and extension not in {".dcm", ".dicom"}:
        return FileClassification(Category.JUNK, "Файл у папці cache/temp — перевірити вручну", "low", Action.KEEP)

    return FileClassification(Category.OTHER, "Тип не визначено", "low", Action.KEEP)
