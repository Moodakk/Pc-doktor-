from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4


class Category(str, Enum):
    CT = "ct_cbct"
    XRAY = "xray"
    PHOTO = "patient_photos"
    IMAGE_REVIEW = "images_review"
    MODEL_3D = "models_3d"
    DOCUMENT = "documents"
    DICOM_OTHER = "dicom_other"
    ARCHIVE = "archives"
    VIDEO = "video"
    DUPLICATE = "duplicates"
    JUNK = "cleanup_candidates"
    OTHER = "other"

    @property
    def label(self) -> str:
        from .i18n import tr

        return tr(f"category.{self.value}")

    @property
    def folder_name(self) -> str:
        return {
            Category.CT: "01_CT_CBCT",
            Category.XRAY: "02_XRAY",
            Category.PHOTO: "03_PATIENT_PHOTOS",
            Category.IMAGE_REVIEW: "04_IMAGES_REVIEW",
            Category.MODEL_3D: "05_3D_MODELS",
            Category.DOCUMENT: "06_DOCUMENTS",
            Category.DICOM_OTHER: "07_DICOM_OTHER",
            Category.ARCHIVE: "08_ARCHIVES",
            Category.VIDEO: "09_VIDEO",
            Category.DUPLICATE: "90_DUPLICATES",
            Category.JUNK: "91_CLEANUP_CANDIDATES",
            Category.OTHER: "99_OTHER",
        }[self]


class Action(str, Enum):
    KEEP = "keep"
    COPY = "copy"
    MOVE = "move"
    QUARANTINE = "quarantine"
    TRASH = "trash"

    @property
    def label(self) -> str:
        from .i18n import tr

        return tr(f"action.{self.value}")


@dataclass(slots=True)
class DicomInfo:
    is_dicom: bool = False
    modality: str = ""
    study_uid: str = ""
    series_uid: str = ""
    patient_name: str = ""
    patient_id: str = ""
    study_date: str = ""
    study_description: str = ""
    series_description: str = ""
    body_part: str = ""
    sop_class_uid: str = ""
    error: str = ""


@dataclass(slots=True)
class ScanItem:
    category: Category
    display_name: str
    source_root: Path
    paths: tuple[Path, ...]
    total_size: int
    reason: str
    confidence: str = "medium"
    patient_name: str = ""
    patient_id: str = ""
    study_date: str = ""
    modality: str = ""
    suggested_action: Action = Action.KEEP
    action: Action = Action.KEEP
    selected: bool = False
    duplicate_of: str = ""
    links: list[dict[str, str]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    item_id: str = field(default_factory=lambda: uuid4().hex)

    @property
    def file_count(self) -> int:
        return len(self.paths)

    @property
    def primary_path(self) -> Path:
        return self.paths[0]

    def add_link(self, other: "ScanItem", relation: str) -> None:
        if any(link["item_id"] == other.item_id for link in self.links):
            return
        self.links.append({"item_id": other.item_id, "relation": relation})

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["category"] = self.category.value
        data["source_root"] = str(self.source_root)
        data["paths"] = [str(path) for path in self.paths]
        data["suggested_action"] = self.suggested_action.value
        data["action"] = self.action.value
        return data


@dataclass(slots=True)
class OperationRecord:
    item_id: str
    action: str
    source: str
    destination: str = ""
    size: int = 0
    sha256_source: str = ""
    sha256_destination: str = ""
    status: str = "pending"
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
