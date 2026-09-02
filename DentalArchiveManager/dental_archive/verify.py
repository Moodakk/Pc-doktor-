"""Archive verification ("backup check").

Re-hashes every destination file recorded in the operation manifests found in
``<destination>/_DentalArchive_Logs`` and reports OK / mismatch / missing files.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Callable

from .scanner import sha256_file

VerifyProgress = Callable[[int, int, str], None]

STATUS_OK = "ok"
STATUS_MISMATCH = "mismatch"
STATUS_MISSING = "missing"
STATUS_UNREADABLE = "unreadable"

LOG_DIRECTORY_NAME = "_DentalArchive_Logs"


@dataclass(slots=True)
class VerifyRecord:
    destination: str
    expected_sha256: str
    status: str
    message: str = ""


@dataclass(slots=True)
class VerifyReport:
    manifests: list[Path] = field(default_factory=list)
    records: list[VerifyRecord] = field(default_factory=list)
    cancelled: bool = False

    @property
    def total(self) -> int:
        return len(self.records)

    def count(self, status: str) -> int:
        return sum(record.status == status for record in self.records)

    @property
    def ok(self) -> int:
        return self.count(STATUS_OK)

    @property
    def mismatched(self) -> int:
        return self.count(STATUS_MISMATCH)

    @property
    def missing(self) -> int:
        return self.count(STATUS_MISSING)

    @property
    def unreadable(self) -> int:
        return self.count(STATUS_UNREADABLE)


def find_manifests(destination_root: Path) -> list[Path]:
    """Operation manifests written by :func:`operations.execute_plan`, oldest first."""
    log_directory = destination_root / LOG_DIRECTORY_NAME
    if not log_directory.is_dir():
        return []
    return sorted(log_directory.glob("operation_*.json"))


def _load_expected(manifests: list[Path], warnings: list[str]) -> dict[str, str]:
    """Map destination path -> expected SHA-256; later manifests win."""
    expected: dict[str, str] = {}
    for manifest in manifests:
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            warnings.append(f"{manifest}: {exc}")
            continue
        for record in payload.get("records", []):
            if not isinstance(record, dict):
                continue
            destination = str(record.get("destination") or "")
            digest = str(record.get("sha256_destination") or "")
            status = str(record.get("status") or "")
            if destination and digest and status in {"ok", "already_present"}:
                expected[destination] = digest
    return expected


def verify_archive(
    destination_root: Path,
    *,
    manifests: list[Path] | None = None,
    progress: VerifyProgress | None = None,
    cancel_event: Event | None = None,
) -> VerifyReport:
    report = VerifyReport()
    report.manifests = manifests if manifests is not None else find_manifests(destination_root)
    warnings: list[str] = []
    expected = _load_expected(report.manifests, warnings)
    for warning in warnings:
        report.records.append(VerifyRecord(destination="", expected_sha256="", status=STATUS_UNREADABLE, message=warning))

    entries = sorted(expected.items())
    total = len(entries)
    for index, (destination, digest) in enumerate(entries, start=1):
        if cancel_event and cancel_event.is_set():
            report.cancelled = True
            break
        path = Path(destination)
        if not path.is_file():
            record = VerifyRecord(destination, digest, STATUS_MISSING)
        else:
            try:
                actual = sha256_file(path)
                record = VerifyRecord(destination, digest, STATUS_OK if actual == digest else STATUS_MISMATCH)
            except OSError as exc:
                record = VerifyRecord(destination, digest, STATUS_UNREADABLE, message=str(exc))
        report.records.append(record)
        if progress:
            progress(index, total, destination)
    return report


def write_verify_report_text(report: VerifyReport, path: Path) -> None:
    lines = [
        "Dental Archive Manager — verification report",
        f"manifests: {len(report.manifests)}",
        f"total: {report.total}",
        f"ok: {report.ok}",
        f"mismatch: {report.mismatched}",
        f"missing: {report.missing}",
        f"unreadable: {report.unreadable}",
        "",
    ]
    for record in report.records:
        if record.status == STATUS_OK:
            continue
        suffix = f" ({record.message})" if record.message else ""
        lines.append(f"[{record.status}] {record.destination}{suffix}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
