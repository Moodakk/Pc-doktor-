from __future__ import annotations

import hashlib
import os
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Callable, Iterable

from .classifier import classify_dicom, classify_regular_file, read_dicom_info
from .i18n import tr
from .models import Action, Category, DicomInfo, ScanItem
from .relations import MAX_REVERSE_LINKS, link_related_items


ProgressCallback = Callable[[int, str], None]
# phase, done, total (None when unknown), detail
PhaseProgressCallback = Callable[[str, int, "int | None", str], None]


class ScanPhase:
    WALKING = "walking"
    CLASSIFYING = "classifying"
    HASHING = "hashing"
    LINKING = "linking"


SKIP_DIRECTORY_NAMES = {
    "$recycle.bin",
    "system volume information",
    "windowsapps",
    "recovery",
    ".git",
    ".venv",
    "node_modules",
}

# Below this file count the pool overhead is not worth it.
_PARALLEL_THRESHOLD = 64
_PREFIX_LENGTH = 64 * 1024


@dataclass(slots=True)
class ScanReport:
    items: list[ScanItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    files_seen: int = 0
    bytes_seen: int = 0
    files_hashed: int = 0
    elapsed_seconds: float = 0.0
    cancelled: bool = False


def _worker_count() -> int:
    return min(8, max(2, os.cpu_count() or 2))


def sha256_file(path: Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_prefix(path: Path, length: int = _PREFIX_LENGTH) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        digest.update(stream.read(length))
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
                        warnings.append(tr("warn.cannot_check", path=entry.path, error=exc))
        except (OSError, PermissionError) as exc:
            warnings.append(tr("warn.no_access", path=current, error=exc))


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


def _is_dicomdir(path: Path) -> bool:
    return path.name.casefold() == "dicomdir"


def _attach_dicomdirs(
    groups: dict[str, list[tuple[Path, Path, int, DicomInfo]]],
    dicomdirs: list[tuple[Path, Path, int, DicomInfo]],
) -> None:
    """Attach each DICOMDIR index file to the study group it describes.

    A DICOMDIR sits at the root of a DICOM media folder; the study it indexes
    lives in the same folder or below it. When several groups match, the one
    with the most files wins. Without a match the DICOMDIR stays standalone.
    """
    for record in dicomdirs:
        root, path, _size, info = record
        folder = path.parent
        best_key = ""
        best_count = 0
        for key, records in sorted(groups.items()):
            if records[0][0] != root:
                continue
            matching = sum(1 for other in records if folder in other[1].parents)
            if matching and len(records) > best_count:
                best_key = key
                best_count = len(records)
        if best_key:
            groups[best_key].append(record)
        else:
            groups[_dicom_group_key(root, path, info)].append(record)


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


def _hash_many(
    entries: list[tuple[ScanItem, Callable[[Path], str]]],
    warnings: list[str],
    cancel_event: Event | None,
    on_done: Callable[[ScanItem, str], None],
    progress_tick: Callable[[ScanItem], None],
    max_workers: int,
) -> bool:
    """Hash files in a pool, deterministically collecting results in order.

    Returns True when cancelled.
    """

    def compute(entry: tuple[ScanItem, Callable[[Path], str]]) -> tuple[ScanItem, str, str]:
        item, hash_function = entry
        if cancel_event and cancel_event.is_set():
            return item, "", "cancelled"
        try:
            return item, hash_function(item.primary_path), ""
        except OSError as exc:
            return item, "", str(exc)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(compute, entry) for entry in entries]
        for future in futures:
            item, digest, error = future.result()
            if cancel_event and cancel_event.is_set():
                for pending in futures:
                    pending.cancel()
                return True
            if error:
                warnings.append(tr("warn.cannot_hash", path=item.primary_path, error=error))
            else:
                on_done(item, digest)
            progress_tick(item)
    return bool(cancel_event and cancel_event.is_set())


def _mark_exact_duplicates(
    items: list[ScanItem],
    report: ScanReport,
    progress: ProgressCallback | None,
    cancel_event: Event | None,
    phase_progress: PhaseProgressCallback | None,
    max_workers: int,
) -> bool:
    """Detect exact duplicates; returns True when cancelled."""
    size_groups: dict[int, list[ScanItem]] = defaultdict(list)
    for item in items:
        if item.file_count == 1 and item.total_size > 0 and item.category not in {Category.JUNK, Category.DICOM_OTHER}:
            size_groups[item.total_size].append(item)

    candidates = [item for group in size_groups.values() if len(group) > 1 for item in group]
    candidates.sort(key=lambda item: (item.total_size, str(item.primary_path).casefold()))
    if not candidates:
        return False

    completed = 0
    total = len(candidates)

    def tick(item: ScanItem) -> None:
        nonlocal completed
        completed += 1
        report.files_hashed += 1
        if progress:
            progress(completed, tr("phase.hashing") + f": {item.primary_path.name}")
        if phase_progress:
            phase_progress(ScanPhase.HASHING, completed, total, item.primary_path.name)

    # Stage 1: cheap prefix hashes narrow the candidate set.
    prefix_groups: dict[tuple[int, str], list[ScanItem]] = defaultdict(list)
    cancelled = _hash_many(
        [(item, _sha256_prefix) for item in candidates],
        report.warnings,
        cancel_event,
        lambda item, digest: prefix_groups[(item.total_size, digest)].append(item),
        tick,
        max_workers,
    )
    if cancelled:
        return True

    # Stage 2: full hashes only where the prefixes collide.
    finalists = [item for group in prefix_groups.values() if len(group) > 1 for item in group]
    finalists.sort(key=lambda item: (item.total_size, str(item.primary_path).casefold()))
    total = len(candidates) + len(finalists)

    hash_groups: dict[tuple[int, str], list[ScanItem]] = defaultdict(list)

    def store_full(item: ScanItem, digest: str) -> None:
        item.metadata["sha256"] = digest
        hash_groups[(item.total_size, digest)].append(item)

    cancelled = _hash_many(
        [(item, sha256_file) for item in finalists],
        report.warnings,
        cancel_event,
        store_full,
        tick,
        max_workers,
    )
    if cancelled:
        return True

    for duplicates in hash_groups.values():
        if len(duplicates) < 2:
            continue
        original = min(duplicates, key=lambda item: str(item.primary_path).casefold())
        for duplicate in duplicates:
            if duplicate is original:
                continue
            duplicate.category = Category.DUPLICATE
            duplicate.duplicate_of = str(original.primary_path)
            duplicate.reason = tr("reason.duplicate", original=original.primary_path)
            duplicate.confidence = "high"
            duplicate.suggested_action = Action.QUARANTINE
            duplicate.add_link(original, tr("link.original_of_duplicate"))
            if len(original.links) < MAX_REVERSE_LINKS:
                original.add_link(duplicate, tr("link.exact_duplicate", path=duplicate.primary_path))
    return False


def _classify_one(
    entry: tuple[Path, Path, int],
    cancel_event: Event | None,
) -> tuple[Path, Path, int, DicomInfo | None, ScanItem | None]:
    root, path, size = entry
    if cancel_event and cancel_event.is_set():
        return root, path, size, None, None
    dicom_info = read_dicom_info(path)
    if dicom_info.is_dicom:
        return root, path, size, dicom_info, None
    classification = classify_regular_file(path, size)
    item = ScanItem(
        category=classification.category,
        display_name=path.name,
        source_root=root,
        paths=(path,),
        total_size=size,
        reason=classification.reason,
        confidence=classification.confidence,
        suggested_action=classification.suggested_action,
    )
    return root, path, size, None, item


def scan_roots(
    roots: Iterable[Path],
    *,
    detect_duplicates: bool = True,
    progress: ProgressCallback | None = None,
    cancel_event: Event | None = None,
    phase_progress: PhaseProgressCallback | None = None,
    max_workers: int | None = None,
) -> ScanReport:
    started = time.monotonic()
    report = ScanReport()
    workers = max_workers or _worker_count()
    dicom_groups: dict[str, list[tuple[Path, Path, int, DicomInfo]]] = defaultdict(list)
    dicomdir_records: list[tuple[Path, Path, int, DicomInfo]] = []
    regular_items: list[ScanItem] = []

    clean_roots: list[Path] = []
    for root in roots:
        resolved = root.expanduser().resolve()
        if not resolved.exists() or not resolved.is_dir():
            report.warnings.append(tr("warn.missing_folder", path=resolved))
            continue
        if resolved not in clean_roots:
            clean_roots.append(resolved)

    # Phase 1: walk the trees and collect (root, path, size) entries.
    entries: list[tuple[Path, Path, int]] = []
    for root in clean_roots:
        for path in _iter_files(root, report.warnings, cancel_event):
            if cancel_event and cancel_event.is_set():
                report.cancelled = True
                break
            try:
                size = path.stat().st_size
            except OSError as exc:
                report.warnings.append(tr("warn.cannot_read_size", path=path, error=exc))
                continue
            entries.append((root, path, size))
            if phase_progress:
                phase_progress(ScanPhase.WALKING, len(entries), None, path.name)
        if report.cancelled:
            break

    # Phase 2: classify every file (in a pool for larger scans).
    def consume(result: tuple[Path, Path, int, DicomInfo | None, ScanItem | None]) -> None:
        root, path, size, dicom_info, item = result
        report.files_seen += 1
        report.bytes_seen += size
        if progress:
            progress(report.files_seen, str(path))
        if phase_progress:
            phase_progress(ScanPhase.CLASSIFYING, report.files_seen, len(entries), path.name)
        if dicom_info is not None:
            record = (root, path, size, dicom_info)
            if _is_dicomdir(path):
                dicomdir_records.append(record)
            else:
                dicom_groups[_dicom_group_key(root, path, dicom_info)].append(record)
        elif item is not None:
            regular_items.append(item)

    if not report.cancelled:
        if len(entries) >= _PARALLEL_THRESHOLD:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for result in pool.map(lambda entry: _classify_one(entry, cancel_event), entries, chunksize=16):
                    if cancel_event and cancel_event.is_set():
                        report.cancelled = True
                        break
                    consume(result)
        else:
            for entry in entries:
                if cancel_event and cancel_event.is_set():
                    report.cancelled = True
                    break
                consume(_classify_one(entry, cancel_event))

    _attach_dicomdirs(dicom_groups, dicomdir_records)
    report.items = _build_dicom_items(dicom_groups) + regular_items
    if detect_duplicates and not report.cancelled:
        if _mark_exact_duplicates(report.items, report, progress, cancel_event, phase_progress, workers):
            report.cancelled = True
    if phase_progress:
        phase_progress(ScanPhase.LINKING, 0, None, "")
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
    report.elapsed_seconds = time.monotonic() - started
    return report
