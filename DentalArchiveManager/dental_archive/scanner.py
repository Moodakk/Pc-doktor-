from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Callable, Iterable

from .classifier import classify_dicom, classify_regular_file, read_dicom_info
from .models import Action, Category, DicomInfo, ScanItem
from .relations import link_related_items


ProgressCallback = Callable[[int, str], None]

SKIP_DIRECTORY_NAMES = {
    "$recycle.bin",
    "system volume information",
    "windowsapps",
    "recovery",
    ".git",
    ".venv",
    "node_modules",
}


@dataclass(slots=True)
class ScanReport:
    items: list[ScanItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    files_seen: int = 0
    bytes_seen: int = 0
    cancelled: bool = False


def sha256_file(path: Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_files(root: Path, warnings: list[str], cancel_event: Event | None) -> Iterable[Path]:
    stack = [root]
    while stack:
        if cancel_event and cancel_event.is_set():
            return
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if cancel_event and cancel_event.is_set():
                        return
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name.casefold() not in SKIP_DIRECTORY_NAMES:
                                stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            yield Path(entry.path)
                    except OSError as exc:
                        warnings.append(f"Не вдалося перевірити {entry.path}: {exc}")
        except (OSError, PermissionError) as exc:
            warnings.append(f"Немає доступу до {current}: {exc}")


def _dicom_group_key(root: Path, path: Path, info: DicomInfo) -> str:
    if info.study_uid:
        return f"{root}|study|{info.study_uid}"
    # DICOM without a Study UID is grouped only inside its immediate folder.
    return f"{root}|folder|{path.parent}"


def _best_text(values: Iterable[str]) -> str:
    for value in values:
        value = value.strip()
        if value:
            return value
    return ""


def _build_dicom_items(
    groups: dict[str, list[tuple[Path, Path, int, DicomInfo]]],
) -> list[ScanItem]:
    result: list[ScanItem] = []
    priority = {Category.CT: 3, Category.XRAY: 2, Category.DICOM_OTHER: 1}

    for records in groups.values():
        root = records[0][0]
        paths = tuple(record[1] for record in records)
        infos = [record[3] for record in records]
        classifications = [classify_dicom(info) for info in infos]
        classification = max(classifications, key=lambda item: priority[item.category])
        patient_name = _best_text(info.patient_name for info in infos)
        patient_id = _best_text(info.patient_id for info in infos)
        study_date = _best_text(info.study_date for info in infos)
        study_description = _best_text(info.study_description for info in infos)
        series_description = _best_text(info.series_description for info in infos)
        modalities = sorted({info.modality for info in infos if info.modality})
        modality = ", ".join(modalities)
        fallback = paths[0].parent.name or paths[0].name
        display_name = " — ".join(
            value for value in (patient_name or patient_id or fallback, study_date, study_description or series_description) if value
        )

        result.append(
            ScanItem(
                category=classification.category,
                display_name=display_name,
                source_root=root,
                paths=tuple(sorted(paths, key=lambda path: str(path).casefold())),
                total_size=sum(record[2] for record in records),
                reason=classification.reason,
                confidence="high",
                patient_name=patient_name,
                patient_id=patient_id,
                study_date=study_date,
                modality=modality,
                suggested_action=Action.COPY,
                metadata={
                    "study_uid": _best_text(info.study_uid for info in infos),
                    "study_description": study_description,
                    "series_description": series_description,
                    "modalities": modalities,
                },
            )
        )
    return result


def _mark_exact_duplicates(items: list[ScanItem], warnings: list[str], progress: ProgressCallback | None) -> None:
    size_groups: dict[int, list[ScanItem]] = defaultdict(list)
    for item in items:
        if item.file_count == 1 and item.total_size > 0 and item.category not in {Category.JUNK, Category.DICOM_OTHER}:
            size_groups[item.total_size].append(item)

    hash_groups: dict[tuple[int, str], list[ScanItem]] = defaultdict(list)
    candidates = [group for group in size_groups.values() if len(group) > 1]
    completed = 0
    for group in candidates:
        for item in group:
            try:
                digest = sha256_file(item.primary_path)
                item.metadata["sha256"] = digest
                hash_groups[(item.total_size, digest)].append(item)
            except OSError as exc:
                warnings.append(f"Не вдалося порахувати хеш {item.primary_path}: {exc}")
            completed += 1
            if progress:
                progress(completed, f"Пошук дублікатів: {item.primary_path.name}")

    for duplicates in hash_groups.values():
        if len(duplicates) < 2:
            continue
        original = min(duplicates, key=lambda item: str(item.primary_path).casefold())
        for duplicate in duplicates:
            if duplicate is original:
                continue
            duplicate.category = Category.DUPLICATE
            duplicate.duplicate_of = str(original.primary_path)
            duplicate.reason = f"Точний SHA-256 дублікат: {original.primary_path}"
            duplicate.confidence = "high"
            duplicate.suggested_action = Action.QUARANTINE
            duplicate.add_link(original, "Оригінал цього дубліката")
            original.add_link(duplicate, f"Точний дублікат: {duplicate.primary_path}")


def scan_roots(
    roots: Iterable[Path],
    *,
    detect_duplicates: bool = True,
    progress: ProgressCallback | None = None,
    cancel_event: Event | None = None,
) -> ScanReport:
    report = ScanReport()
    dicom_groups: dict[str, list[tuple[Path, Path, int, DicomInfo]]] = defaultdict(list)
    regular_items: list[ScanItem] = []

    clean_roots: list[Path] = []
    for root in roots:
        resolved = root.expanduser().resolve()
        if not resolved.exists() or not resolved.is_dir():
            report.warnings.append(f"Папка не існує: {resolved}")
            continue
        if resolved not in clean_roots:
            clean_roots.append(resolved)

    for root in clean_roots:
        for path in _iter_files(root, report.warnings, cancel_event):
            if cancel_event and cancel_event.is_set():
                report.cancelled = True
                break
            try:
                size = path.stat().st_size
            except OSError as exc:
                report.warnings.append(f"Не вдалося прочитати розмір {path}: {exc}")
                continue

            report.files_seen += 1
            report.bytes_seen += size
            if progress:
                progress(report.files_seen, str(path))

            dicom_info = read_dicom_info(path)
            if dicom_info.is_dicom:
                key = _dicom_group_key(root, path, dicom_info)
                dicom_groups[key].append((root, path, size, dicom_info))
                continue

            classification = classify_regular_file(path, size)
            regular_items.append(
                ScanItem(
                    category=classification.category,
                    display_name=path.name,
                    source_root=root,
                    paths=(path,),
                    total_size=size,
                    reason=classification.reason,
                    confidence=classification.confidence,
                    suggested_action=classification.suggested_action,
                )
            )
        if report.cancelled:
            break

    report.items = _build_dicom_items(dicom_groups) + regular_items
    if detect_duplicates and not report.cancelled:
        _mark_exact_duplicates(report.items, report.warnings, progress)
    link_related_items(report.items)

    category_order = {category: index for index, category in enumerate(Category)}
    report.items.sort(
        key=lambda item: (
            category_order[item.category],
            item.patient_name.casefold(),
            item.display_name.casefold(),
            str(item.primary_path).casefold(),
        )
    )
    return report
