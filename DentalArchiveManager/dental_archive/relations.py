"""Logical relations between scanned items.

After classification every file is still an isolated row. This module builds
the connections a clinician expects to see:

- photos, documents, models and archives found inside (or next to) a DICOM
  study folder are linked to that study and inherit the patient context;
- files with the same base name in the same folder are linked as companions
  (e.g. ``scan.stl`` + ``scan.pdf``);
- numbered shots in the same folder (``IMG_001.jpg`` … ``IMG_047.jpg``) are
  recognised as one series.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from .models import Category, ScanItem

# How many reverse links a study item may accumulate before we stop adding
# them (a CT folder can contain hundreds of companion files).
_MAX_REVERSE_LINKS = 30
_SERIES_PATTERN = re.compile(r"^(.*?)(\d{1,6})$")
_IMAGE_CATEGORIES = {Category.XRAY, Category.PHOTO, Category.IMAGE_REVIEW}


def _is_dicom_study(item: ScanItem) -> bool:
    return "modalities" in item.metadata


def _patient_key(item: ScanItem) -> str:
    return f"{item.patient_id.casefold()}|{item.patient_name.casefold()}"


def _study_context_folders(items: list[ScanItem]) -> dict[Path, list[ScanItem]]:
    """Map folders to the DICOM studies whose files live in or under them."""
    folders: dict[Path, list[ScanItem]] = defaultdict(list)
    for item in items:
        if not _is_dicom_study(item):
            continue
        candidates: set[Path] = set()
        for path in item.paths:
            parent = path.parent
            candidates.add(parent)
            # One level up covers the common "patient folder" layout where
            # photos live in a sibling folder of the DICOM series. The scan
            # root itself is never a patient context: it may contain many
            # unrelated folders.
            if parent != item.source_root and parent.parent != item.source_root:
                candidates.add(parent.parent)
        for folder in candidates:
            if item not in folders[folder]:
                folders[folder].append(item)
    return folders


def _inherit_patient(item: ScanItem, study: ScanItem, context_name: str) -> None:
    if item.patient_name or item.patient_id:
        return
    item.patient_name = study.patient_name
    item.patient_id = study.patient_id
    if not item.study_date:
        item.study_date = study.study_date
    item.metadata.setdefault("study_description", context_name)
    item.metadata["patient_context"] = "успадковано від DICOM-дослідження поруч"


def _link_study_context(items: list[ScanItem]) -> None:
    folders = _study_context_folders(items)
    if not folders:
        return
    for item in items:
        if _is_dicom_study(item) or item.file_count != 1:
            continue
        ancestors = [item.primary_path.parent, *item.primary_path.parent.parents]
        studies: list[ScanItem] | None = None
        for ancestor in ancestors:
            if ancestor in folders:
                studies = [study for study in folders[ancestor] if study is not item]
                break
            if ancestor == item.source_root:
                break
        if not studies:
            continue

        if len(studies) == 1:
            study = studies[0]
            context_name = (
                str(item.metadata.get("study_description", "")).strip()
                or str(study.metadata.get("study_description", "")).strip()
                or str(study.metadata.get("series_description", "")).strip()
                or item.primary_path.parent.name
            )
            item.add_link(study, "Дослідження цього пацієнта в тій самій папці")
            if len(study.links) < _MAX_REVERSE_LINKS:
                study.add_link(item, f"Супутній файл: {item.display_name}")
            _inherit_patient(item, study, context_name)
            continue

        # Several studies share the folder: connect only when they clearly
        # belong to the same patient, and inherit just the patient identity.
        keys = {_patient_key(study) for study in studies}
        if len(keys) != 1 or keys == {"|"}:
            continue
        for study in studies[:5]:
            item.add_link(study, "Дослідження цього пацієнта в тій самій папці")
            if len(study.links) < _MAX_REVERSE_LINKS:
                study.add_link(item, f"Супутній файл: {item.display_name}")
        if not (item.patient_name or item.patient_id):
            item.patient_name = studies[0].patient_name
            item.patient_id = studies[0].patient_id
            item.metadata.setdefault("study_description", item.primary_path.parent.name)
            item.metadata["patient_context"] = "успадковано від DICOM-досліджень пацієнта поруч"


def _link_sidecars(items: list[ScanItem]) -> None:
    groups: dict[tuple[Path, str], list[ScanItem]] = defaultdict(list)
    for item in items:
        if item.file_count != 1:
            continue
        stem = item.primary_path.stem.casefold()
        if not stem:
            continue
        groups[(item.primary_path.parent, stem)].append(item)

    for group in groups.values():
        if len(group) < 2 or len(group) > 6:
            continue
        extensions = {item.primary_path.suffix.casefold() for item in group}
        if len(extensions) < 2:
            continue
        for item in group:
            for other in group:
                if other is not item:
                    item.add_link(other, "Той самий базовий файл з іншим розширенням (sidecar)")


def _link_numbered_series(items: list[ScanItem]) -> None:
    groups: dict[tuple[Path, str, str], list[tuple[int, ScanItem]]] = defaultdict(list)
    for item in items:
        if item.file_count != 1 or item.category not in _IMAGE_CATEGORIES:
            continue
        match = _SERIES_PATTERN.match(item.primary_path.stem)
        if not match:
            continue
        prefix, number = match.groups()
        key = (item.primary_path.parent, prefix.casefold(), item.primary_path.suffix.casefold())
        groups[key].append((int(number), item))

    for (folder, prefix, _), members in groups.items():
        if len(members) < 3:
            continue
        members.sort(key=lambda pair: pair[0])
        label = f"{prefix.strip(' _-') or folder.name} ({len(members)} файлів)"
        first = members[0][1]
        for _, member in members:
            member.metadata["series"] = label
        for index, (_, member) in enumerate(members[1:]):
            member.add_link(first, f"Серія знімків: {label}")
            if index < 10:
                first.add_link(member, f"Серія знімків: {label}")


def link_related_items(items: list[ScanItem]) -> None:
    """Build logical links between already classified scan items in place."""
    _link_study_context(items)
    _link_sidecars(items)
    _link_numbered_series(items)
