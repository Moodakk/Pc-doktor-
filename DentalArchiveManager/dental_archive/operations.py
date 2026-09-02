from __future__ import annotations

import csv
import json
import os
import re
import shutil
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from . import __version__
from .i18n import tr
from .models import Action, OperationRecord, ScanItem
from .scanner import sha256_file

try:
    from send2trash import send2trash
except ImportError:
    send2trash = None


OperationProgress = Callable[[int, int, str], None]
TrashFunction = Callable[[str], None]


@dataclass(slots=True)
class RunSummary:
    records: list[OperationRecord] = field(default_factory=list)
    manifest_path: Path | None = None

    @property
    def succeeded(self) -> int:
        return sum(record.status in {"ok", "already_present"} for record in self.records)

    @property
    def failed(self) -> int:
        return sum(record.status == "error" for record in self.records)


def human_size(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{value} B"


def sanitize_component(value: str, fallback: str = "Unknown") -> str:
    value = value.strip().replace("^", " ")
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    if not value:
        value = fallback
    # Avoid Windows reserved device names.
    if value.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        value = f"_{value}"
    return value[:120]


def _study_folder(item: ScanItem) -> str:
    description = str(item.metadata.get("study_description") or item.metadata.get("series_description") or item.display_name)
    date = item.study_date or "NoDate"
    return sanitize_component(f"{date}_{description}", "Study")


def destination_for(item: ScanItem, source: Path, destination_root: Path, *, quarantine: bool = False) -> Path:
    if quarantine:
        day = datetime.now().strftime("%Y-%m-%d")
        base = destination_root / "_QUARANTINE" / day / item.category.folder_name
    else:
        base = destination_root / "DentalArchive" / item.category.folder_name

    if item.patient_name or item.patient_id or item.modality:
        patient = sanitize_component(item.patient_name or item.patient_id or source.parent.name, "UnknownPatient")
        if item.patient_id and item.patient_id.casefold() not in patient.casefold():
            patient = sanitize_component(f"{patient}_{item.patient_id}")
        base = base / patient / _study_folder(item)
        try:
            common_parent = Path(os.path.commonpath([str(path.parent) for path in item.paths]))
            relative = source.relative_to(common_parent)
        except (ValueError, OSError):
            relative = Path(source.name)
        return base / relative

    try:
        relative = source.relative_to(item.source_root)
    except ValueError:
        relative = Path(source.name)
    return base / sanitize_component(item.source_root.name, "Source") / relative


def _unique_destination(path: Path, source_hash: str, source_size: int) -> tuple[Path, bool]:
    if not path.exists():
        return path, False
    if path.is_file() and path.stat().st_size == source_size and sha256_file(path) == source_hash:
        return path, True
    counter = 2
    while True:
        candidate = path.with_name(f"{path.stem}__{counter}{path.suffix}")
        if not candidate.exists():
            return candidate, False
        if candidate.is_file() and candidate.stat().st_size == source_size and sha256_file(candidate) == source_hash:
            return candidate, True
        counter += 1


def copy_verified(source: Path, requested_destination: Path) -> tuple[Path, str, str, bool]:
    source_hash = sha256_file(source)
    destination, already_present = _unique_destination(requested_destination, source_hash, source.stat().st_size)
    if already_present:
        return destination, source_hash, source_hash, True

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.partial")
    if temporary.exists():
        temporary.unlink()
    try:
        shutil.copy2(source, temporary)
        destination_hash = sha256_file(temporary)
        if destination_hash != source_hash or temporary.stat().st_size != source.stat().st_size:
            raise IOError(tr("op.copy_mismatch"))
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination, source_hash, destination_hash, False


def _write_manifest(
    summary: RunSummary,
    destination_root: Path,
    started_at: datetime,
    sources: list[str],
) -> Path:
    log_directory = destination_root / "_DentalArchive_Logs"
    log_directory.mkdir(parents=True, exist_ok=True)
    stamp = started_at.strftime("%Y%m%d_%H%M%S")
    manifest = log_directory / f"operation_{stamp}.json"
    action_totals = Counter(record.action for record in summary.records)
    payload = {
        "app": "Dental Archive Manager",
        "app_version": __version__,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "sources": sources,
        "destination": str(destination_root),
        "action_totals": dict(sorted(action_totals.items())),
        "records": [record.to_dict() for record in summary.records],
        "succeeded": summary.succeeded,
        "failed": summary.failed,
    }
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_manifest_csv(summary, log_directory / f"operation_{stamp}.csv")
    return manifest


def _write_manifest_csv(summary: RunSummary, path: Path) -> None:
    # UTF-8 with BOM so Excel opens Cyrillic text correctly.
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=";")
        writer.writerow(
            ["item_id", "action", "status", "source", "destination", "size", "sha256_source", "sha256_destination", "message"]
        )
        for record in summary.records:
            writer.writerow(
                [
                    record.item_id,
                    record.action,
                    record.status,
                    record.source,
                    record.destination,
                    record.size,
                    record.sha256_source,
                    record.sha256_destination,
                    record.message,
                ]
            )


def execute_plan(
    items: Iterable[ScanItem],
    destination_root: Path,
    *,
    progress: OperationProgress | None = None,
    trash_function: TrashFunction | None = None,
    sources: Iterable[Path] | None = None,
) -> RunSummary:
    selected = [item for item in items if item.selected and item.action != Action.KEEP]
    destination_root = destination_root.expanduser().resolve()
    destination_root.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now()
    summary = RunSummary()

    if trash_function is None:
        if send2trash is None:
            raise RuntimeError(tr("op.send2trash_missing"))
        trash_function = send2trash

    total_files = sum(item.file_count for item in selected)
    completed = 0
    for item in selected:
        for source in item.paths:
            record = OperationRecord(item_id=item.item_id, action=item.action.value, source=str(source), size=0)
            try:
                if not source.exists() or not source.is_file():
                    raise FileNotFoundError(tr("op.file_not_found", path=source))
                record.size = source.stat().st_size

                if item.action == Action.TRASH:
                    trash_function(str(source))
                    record.status = "ok"
                    record.message = tr("op.trashed")
                else:
                    destination = destination_for(
                        item,
                        source,
                        destination_root,
                        quarantine=item.action == Action.QUARANTINE,
                    )
                    try:
                        if source.resolve() == destination.resolve():
                            raise ValueError(tr("op.same_source_destination"))
                    except FileNotFoundError:
                        pass
                    copied_to, source_hash, destination_hash, already_present = copy_verified(source, destination)
                    record.destination = str(copied_to)
                    record.sha256_source = source_hash
                    record.sha256_destination = destination_hash
                    record.status = "already_present" if already_present else "ok"
                    record.message = tr("op.copied_already") if already_present else tr("op.copied_verified")

                    if item.action in {Action.MOVE, Action.QUARANTINE}:
                        trash_function(str(source))
                        record.message += tr("op.source_trashed")
            except Exception as exc:  # Continue the batch and preserve a complete audit trail.
                record.status = "error"
                record.message = str(exc)
            summary.records.append(record)
            completed += 1
            if progress:
                progress(completed, total_files, str(source))

    source_list = sorted({str(source) for source in sources}) if sources else sorted({str(item.source_root) for item in selected})
    summary.manifest_path = _write_manifest(summary, destination_root, started_at, source_list)
    return summary
