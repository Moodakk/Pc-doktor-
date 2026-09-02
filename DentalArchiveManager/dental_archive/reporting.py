"""Scan report exports: CSV table and a self-contained offline HTML summary."""
from __future__ import annotations

import csv
import html
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

from . import __version__
from .i18n import tr
from .models import Category, ScanItem
from .operations import human_size


@dataclass(slots=True)
class CategoryStats:
    items: int = 0
    files: int = 0
    size: int = 0


@dataclass(slots=True)
class ScanStatistics:
    total_items: int = 0
    total_files: int = 0
    total_size: int = 0
    by_category: dict[Category, CategoryStats] = field(default_factory=dict)
    by_patient: dict[str, CategoryStats] = field(default_factory=dict)
    duplicate_items: int = 0
    reclaimable_bytes: int = 0
    junk_bytes: int = 0
    warnings: list[str] = field(default_factory=list)


def build_statistics(items: Iterable[ScanItem], warnings: Iterable[str] = ()) -> ScanStatistics:
    stats = ScanStatistics(warnings=list(warnings))
    for item in items:
        stats.total_items += 1
        stats.total_files += item.file_count
        stats.total_size += item.total_size

        category = stats.by_category.setdefault(item.category, CategoryStats())
        category.items += 1
        category.files += item.file_count
        category.size += item.total_size

        patient = item.patient_name or item.patient_id
        if patient:
            entry = stats.by_patient.setdefault(patient, CategoryStats())
            entry.items += 1
            entry.files += item.file_count
            entry.size += item.total_size

        if item.category == Category.DUPLICATE:
            stats.duplicate_items += 1
            stats.reclaimable_bytes += item.total_size
        if item.category == Category.JUNK:
            stats.junk_bytes += item.total_size
    return stats


def write_scan_csv(items: Iterable[ScanItem], path: Path) -> None:
    """One row per scan item; UTF-8 with BOM so Excel opens it correctly."""
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=";")
        writer.writerow(
            [
                tr("csv.category"),
                tr("csv.name"),
                tr("csv.patient"),
                tr("csv.patient_id"),
                tr("csv.study_date"),
                tr("csv.modality"),
                tr("csv.files"),
                tr("csv.size_bytes"),
                tr("csv.size"),
                tr("csv.confidence"),
                tr("csv.selected"),
                tr("csv.action"),
                tr("csv.suggested_action"),
                tr("csv.reason"),
                tr("csv.duplicate_of"),
                tr("csv.path"),
            ]
        )
        for item in items:
            writer.writerow(
                [
                    item.category.label,
                    item.display_name,
                    item.patient_name,
                    item.patient_id,
                    item.study_date,
                    item.modality,
                    item.file_count,
                    item.total_size,
                    human_size(item.total_size),
                    tr(f"confidence.{item.confidence}"),
                    tr("csv.yes") if item.selected else tr("csv.no"),
                    item.action.label,
                    item.suggested_action.label,
                    item.reason,
                    item.duplicate_of,
                    str(item.primary_path),
                ]
            )


_HTML_STYLE = """
body { font-family: 'Segoe UI', Arial, sans-serif; margin: 24px; color: #16313f; background: #f3f6f8; }
h1 { color: #12354a; font-size: 22px; }
h2 { color: #12354a; font-size: 16px; margin-top: 28px; }
table { border-collapse: collapse; background: #fff; min-width: 420px; }
th, td { border: 1px solid #d7e2e8; padding: 6px 12px; text-align: left; font-size: 13px; }
th { background: #e5edf1; }
td.num { text-align: right; }
.summary { background: #fff; border: 1px solid #d7e2e8; padding: 12px 16px; display: inline-block; }
.footer { margin-top: 32px; color: #667985; font-size: 12px; }
ul.warnings { background: #fff; border: 1px solid #d7e2e8; padding: 12px 28px; font-size: 13px; }
"""


def write_html_report(
    items: Iterable[ScanItem],
    path: Path,
    *,
    warnings: Iterable[str] = (),
    generated_at: datetime | None = None,
) -> None:
    """Self-contained offline HTML summary (no external assets)."""
    stats = build_statistics(items, warnings)
    moment = (generated_at or datetime.now()).isoformat(timespec="seconds")

    def row(cells: list[str], numeric_from: int = 1) -> str:
        rendered = []
        for index, cell in enumerate(cells):
            klass = ' class="num"' if index >= numeric_from else ""
            rendered.append(f"<td{klass}>{html.escape(cell)}</td>")
        return "<tr>" + "".join(rendered) + "</tr>"

    category_rows = "".join(
        row([category.label, str(entry.items), str(entry.files), human_size(entry.size)])
        for category, entry in sorted(stats.by_category.items(), key=lambda pair: list(Category).index(pair[0]))
    )
    patient_rows = "".join(
        row([patient, str(entry.items), str(entry.files), human_size(entry.size)])
        for patient, entry in sorted(stats.by_patient.items(), key=lambda pair: pair[0].casefold())
    )
    if not patient_rows:
        patient_rows = row([tr("report.unknown_patient"), "0", "0", human_size(0)])

    if stats.warnings:
        warning_block = "<ul class=\"warnings\">" + "".join(
            f"<li>{html.escape(warning)}</li>" for warning in stats.warnings
        ) + "</ul>"
    else:
        warning_block = f"<p>{html.escape(tr('report.no_warnings'))}</p>"

    header_cells = (
        f"<th>{html.escape(tr('report.category'))}</th><th>{html.escape(tr('report.count'))}</th>"
        f"<th>{html.escape(tr('report.files'))}</th><th>{html.escape(tr('report.size'))}</th>"
    )
    patient_header_cells = (
        f"<th>{html.escape(tr('report.patient'))}</th><th>{html.escape(tr('report.count'))}</th>"
        f"<th>{html.escape(tr('report.files'))}</th><th>{html.escape(tr('report.size'))}</th>"
    )

    document = f"""<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="utf-8">
<title>{html.escape(tr('report.title'))}</title>
<style>{_HTML_STYLE}</style>
</head>
<body>
<h1>{html.escape(tr('report.title'))}</h1>
<p>{html.escape(tr('report.generated'))}: {html.escape(moment)}</p>
<div class="summary">
{stats.total_items} {html.escape(tr('report.items'))} • {stats.total_files} {html.escape(tr('report.files'))} • {html.escape(tr('report.total_size'))}: {html.escape(human_size(stats.total_size))}<br>
{html.escape(tr('report.duplicates'))}: {stats.duplicate_items} • {html.escape(tr('report.reclaimable'))}: {html.escape(human_size(stats.reclaimable_bytes))}<br>
{html.escape(tr('report.junk_size'))}: {html.escape(human_size(stats.junk_bytes))}
</div>
<h2>{html.escape(tr('report.by_category'))}</h2>
<table><tr>{header_cells}</tr>{category_rows}</table>
<h2>{html.escape(tr('report.by_patient'))}</h2>
<table><tr>{patient_header_cells}</tr>{patient_rows}</table>
<h2>{html.escape(tr('report.warnings'))}</h2>
{warning_block}
<p class="footer">Dental Archive Manager • {html.escape(tr('report.version'))} {html.escape(__version__)}</p>
</body>
</html>
"""
    path.write_text(document, encoding="utf-8")


def summary_by_category(items: Iterable[ScanItem]) -> dict[Category, int]:
    counts: dict[Category, int] = defaultdict(int)
    for item in items:
        counts[item.category] += 1
    return dict(counts)
