"""Localization layer: Ukrainian (default) and English.

Every user-visible string is looked up with :func:`tr` by a stable key.
Templates use ``str.format`` placeholders. The active language is detected
from the saved settings first, then the OS locale, and can be switched at
runtime with :func:`set_language`.
"""
from __future__ import annotations

import locale

from .settings import load_settings, save_settings

DEFAULT_LANGUAGE = "uk"
LANGUAGES: tuple[str, ...] = ("uk", "en")

LANGUAGE_NAMES = {"uk": "Українська", "en": "English"}

# key -> (uk, en)
_TABLE: dict[str, tuple[str, str]] = {
    # Categories
    "category.ct_cbct": ("КТ / CBCT", "CT / CBCT"),
    "category.xray": ("Рентгени", "X-rays"),
    "category.patient_photos": ("Фото пацієнтів", "Patient photos"),
    "category.images_review": ("Зображення — перевірити", "Images — review"),
    "category.models_3d": ("3D-моделі / скани", "3D models / scans"),
    "category.documents": ("Документи", "Documents"),
    "category.dicom_other": ("Інший DICOM", "Other DICOM"),
    "category.archives": ("Архіви", "Archives"),
    "category.video": ("Відео", "Video"),
    "category.duplicates": ("Точні дублікати", "Exact duplicates"),
    "category.cleanup_candidates": ("Кандидати на очищення", "Cleanup candidates"),
    "category.other": ("Інше", "Other"),
    # Actions
    "action.keep": ("Залишити", "Keep"),
    "action.copy": ("Копіювати", "Copy"),
    "action.move": ("Перенести", "Move"),
    "action.quarantine": ("У карантин", "Quarantine"),
    "action.trash": ("До Кошика", "To Recycle Bin"),
    # Confidence levels
    "confidence.high": ("висока", "high"),
    "confidence.medium": ("середня", "medium"),
    "confidence.low": ("низька", "low"),
    # Classifier reasons and notes
    "reason.dicom_modality": ("DICOM modality: {modality}", "DICOM modality: {modality}"),
    "reason.dicom_ct_description": ("DICOM: опис вказує на КТ/CBCT", "DICOM: description indicates CT/CBCT"),
    "reason.dicom_xray_description": ("DICOM: опис вказує на рентген", "DICOM: description indicates an X-ray"),
    "reason.dicom_unspecified": ("DICOM modality: невказана", "DICOM modality: unspecified"),
    "reason.dicom_document": (
        "Документ у DICOM-обгортці (modality {modality})",
        "Document in a DICOM wrapper (modality {modality})",
    ),
    "reason.dicom_encapsulated_pdf": ("PDF-документ у DICOM-обгортці", "PDF document in a DICOM wrapper"),
    "reason.dicomdir": ("Індекс DICOMDIR дослідження", "DICOMDIR study index"),
    "reason.empty_file": ("Порожній файл (0 байт)", "Empty file (0 bytes)"),
    "reason.system_temp_file": ("Системний або тимчасовий службовий файл", "System or temporary service file"),
    "reason.temp_extension": ("Незавершений/тимчасовий файл {extension}", "Unfinished/temporary file {extension}"),
    "reason.xray_keyword": ("Назва або папка містить рентген-ознаку", "Name or folder contains an X-ray hint"),
    "reason.photo_keyword": (
        "Назва або папка містить ознаку фото пацієнта",
        "Name or folder contains a patient-photo hint",
    ),
    "reason.plain_image": (
        "Звичайне зображення без достатніх ознак типу",
        "Plain image without enough type hints",
    ),
    "reason.model_3d_content": ("3D-модель ({format})", "3D model ({format})"),
    "reason.document_content": ("Документ ({format})", "Document ({format})"),
    "reason.archive_content": (
        "Архів ({format}); вміст не розпаковувався",
        "Archive ({format}); contents were not extracted",
    ),
    "reason.video_content": ("Відеофайл ({format})", "Video file ({format})"),
    "reason.volume_content": (
        "Об'ємні медичні дані ({format})",
        "Volumetric medical data ({format})",
    ),
    "reason.volume_extension": (
        "Формат об'ємних медичних даних {extension}",
        "Volumetric medical data format {extension}",
    ),
    "note.no_extension": (
        "файл без розширення, вміст визначено за сигнатурою: {format}",
        "file without extension, content detected by signature: {format}",
    ),
    "note.extension_mismatch": (
        "розширення {extension} не відповідає вмісту ({format})",
        "extension {extension} does not match the content ({format})",
    ),
    "note.unknown_extension": (
        "невідоме розширення {extension}, вміст: {format}",
        "unknown extension {extension}, content: {format}",
    ),
    "reason.model_3d_extension": ("Формат 3D-моделі {extension}", "3D model format {extension}"),
    "reason.document_extension": ("Формат документа {extension}", "Document format {extension}"),
    "reason.archive_ct_keywords": (
        "Архів із КТ/рентген-ознаками у назві",
        "Archive with CT/X-ray hints in the name",
    ),
    "reason.archive_extension": (
        "Архів {extension}; вміст не розпаковувався",
        "Archive {extension}; contents were not extracted",
    ),
    "reason.video_extension": ("Відеофайл {extension}", "Video file {extension}"),
    "reason.export_format": ("Службовий/описовий формат {extension}", "Service/descriptive format {extension}"),
    "reason.dcm_unreadable": (
        "Розширення DICOM, але вміст не читається як DICOM",
        "DICOM extension, but the content is not readable as DICOM",
    ),
    "reason.cache_folder": (
        "Файл у папці cache/temp — перевірити вручну",
        "File in a cache/temp folder — check manually",
    ),
    "reason.unknown_type": ("Тип не визначено", "Type not determined"),
    "reason.duplicate": ("Точний SHA-256 дублікат: {original}", "Exact SHA-256 duplicate: {original}"),
    "reason.pydicom_missing": ("pydicom не встановлено", "pydicom is not installed"),
    # Relations
    "link.original_of_duplicate": ("Оригінал цього дубліката", "Original of this duplicate"),
    "link.exact_duplicate": ("Точний дублікат: {path}", "Exact duplicate: {path}"),
    "link.study_same_folder": (
        "Дослідження цього пацієнта в тій самій папці",
        "This patient's study in the same folder",
    ),
    "link.companion_file": ("Супутній файл: {name}", "Companion file: {name}"),
    "link.sidecar": (
        "Той самий базовий файл з іншим розширенням (sidecar)",
        "Same base file with a different extension (sidecar)",
    ),
    "link.series": ("Серія знімків: {label}", "Image series: {label}"),
    "meta.patient_inherited": (
        "успадковано від DICOM-дослідження поруч",
        "inherited from a nearby DICOM study",
    ),
    "meta.patient_inherited_multi": (
        "успадковано від DICOM-досліджень пацієнта поруч",
        "inherited from the patient's nearby DICOM studies",
    ),
    "series.label": ("{prefix} ({count} файлів)", "{prefix} ({count} files)"),
    # Scanner warnings
    "warn.cannot_check": ("Не вдалося перевірити {path}: {error}", "Could not check {path}: {error}"),
    "warn.no_access": ("Немає доступу до {path}: {error}", "No access to {path}: {error}"),
    "warn.missing_folder": ("Папка не існує: {path}", "Folder does not exist: {path}"),
    "warn.cannot_read_size": (
        "Не вдалося прочитати розмір {path}: {error}",
        "Could not read the size of {path}: {error}",
    ),
    "warn.cannot_hash": (
        "Не вдалося порахувати хеш {path}: {error}",
        "Could not compute the hash of {path}: {error}",
    ),
    # Operations
    "op.copy_mismatch": (
        "SHA-256 або розмір копії не збігається з джерелом",
        "SHA-256 or size of the copy does not match the source",
    ),
    "op.file_not_found": ("Файл не знайдено: {path}", "File not found: {path}"),
    "op.same_source_destination": (
        "Джерело і місце призначення збігаються",
        "Source and destination are the same",
    ),
    "op.trashed": ("Переміщено до системного Кошика", "Moved to the system Recycle Bin"),
    "op.copied_already": ("Копія вже існувала і пройшла SHA-256", "Copy already existed and passed SHA-256"),
    "op.copied_verified": ("Копію перевірено SHA-256", "Copy verified with SHA-256"),
    "op.source_trashed": ("; джерело переміщено до Кошика", "; source moved to the Recycle Bin"),
    "op.send2trash_missing": (
        "Send2Trash не встановлено; безпечне переміщення до Кошика недоступне",
        "Send2Trash is not installed; safe move to the Recycle Bin is unavailable",
    ),
    # Scan phases
    "phase.walking": ("Пошук файлів", "Finding files"),
    "phase.classifying": ("Класифікація", "Classifying"),
    "phase.hashing": ("Пошук дублікатів", "Finding duplicates"),
    "phase.linking": ("Побудова зв'язків", "Building relations"),
    "phase.verifying": ("Перевірка архіву", "Verifying archive"),
    # Verification statuses
    "verify.ok": ("OK", "OK"),
    "verify.mismatch": ("Хеш не збігається", "Hash mismatch"),
    "verify.missing": ("Файл відсутній", "File missing"),
    "verify.unreadable": ("Не вдалося прочитати", "Could not read"),
    "verify.no_manifests": (
        "У {path} не знайдено журналів операцій",
        "No operation manifests found in {path}",
    ),
    # Reporting
    "report.title": ("Звіт Dental Archive Manager", "Dental Archive Manager report"),
    "report.generated": ("Створено", "Generated"),
    "report.summary": ("Підсумок", "Summary"),
    "report.items": ("елементів", "items"),
    "report.files": ("файлів", "files"),
    "report.total_size": ("Загальний розмір", "Total size"),
    "report.by_category": ("За категоріями", "By category"),
    "report.by_patient": ("За пацієнтами", "By patient"),
    "report.category": ("Категорія", "Category"),
    "report.patient": ("Пацієнт", "Patient"),
    "report.count": ("Елементів", "Items"),
    "report.size": ("Розмір", "Size"),
    "report.duplicates": ("Дублікати", "Duplicates"),
    "report.reclaimable": ("Можна звільнити (дублікати)", "Reclaimable (duplicates)"),
    "report.junk_size": ("Кандидати на очищення", "Cleanup candidates"),
    "report.warnings": ("Попередження", "Warnings"),
    "report.no_warnings": ("Попереджень немає", "No warnings"),
    "report.unknown_patient": ("(без пацієнта)", "(no patient)"),
    "report.version": ("версія", "version"),
    "csv.category": ("Категорія", "Category"),
    "csv.name": ("Назва", "Name"),
    "csv.patient": ("Пацієнт", "Patient"),
    "csv.patient_id": ("Patient ID", "Patient ID"),
    "csv.study_date": ("Дата дослідження", "Study date"),
    "csv.modality": ("Modality", "Modality"),
    "csv.files": ("Файлів", "Files"),
    "csv.size_bytes": ("Розмір (байт)", "Size (bytes)"),
    "csv.size": ("Розмір", "Size"),
    "csv.confidence": ("Впевненість", "Confidence"),
    "csv.selected": ("Позначено", "Selected"),
    "csv.action": ("Дія", "Action"),
    "csv.suggested_action": ("Рекомендована дія", "Suggested action"),
    "csv.reason": ("Причина", "Reason"),
    "csv.duplicate_of": ("Оригінал дубліката", "Duplicate of"),
    "csv.path": ("Шлях", "Path"),
    "csv.yes": ("так", "yes"),
    "csv.no": ("ні", "no"),
    # UI: header and setup
    "ui.app_title": ("Dental Archive Manager", "Dental Archive Manager"),
    "ui.subtitle": (
        "Офлайн-сортування стоматологічних файлів • без автоматичного видалення",
        "Offline sorting of dental files • no automatic deletion",
    ),
    "ui.language": ("Мова", "Language"),
    "ui.sources": ("Папки-джерела", "Source folders"),
    "ui.add": ("+ Додати", "+ Add"),
    "ui.remove": ("Прибрати", "Remove"),
    "ui.destination": ("Диск / папка призначення", "Destination drive / folder"),
    "ui.choose": ("Обрати…", "Choose…"),
    "ui.detect_duplicates": ("Шукати точні дублікати (SHA-256)", "Find exact duplicates (SHA-256)"),
    "ui.scan": ("Сканувати", "Scan"),
    "ui.cancel": ("Скасувати", "Cancel"),
    "ui.verify_archive": ("Перевірити архів", "Verify archive"),
    # UI: filters and table
    "ui.search": ("Пошук:", "Search:"),
    "ui.category_filter": ("Категорія:", "Category:"),
    "ui.action_filter": ("Дія:", "Action:"),
    "ui.confidence_filter": ("Впевненість:", "Confidence:"),
    "ui.all_categories": ("Усі категорії", "All categories"),
    "ui.all_actions": ("Усі дії", "All actions"),
    "ui.all_confidences": ("Будь-яка", "Any"),
    "ui.only_selected": ("Лише позначені", "Only selected"),
    "ui.check_visible": ("Позначити видимі", "Check visible"),
    "ui.uncheck_visible": ("Зняти видимі", "Uncheck visible"),
    "ui.apply_suggestions": ("Застосувати рекомендації", "Apply recommendations"),
    "ui.col.checked": ("✓", "✓"),
    "ui.col.action": ("Дія", "Action"),
    "ui.col.category": ("Категорія", "Category"),
    "ui.col.name": ("Дослідження / файл", "Study / file"),
    "ui.col.files": ("Файлів", "Files"),
    "ui.col.size": ("Розмір", "Size"),
    "ui.col.patient": ("Пацієнт / дата", "Patient / date"),
    "ui.col.path": ("Джерело", "Source"),
    # UI: details panel
    "ui.details_title": ("Перегляд і деталі", "Preview and details"),
    "ui.select_row": ("Оберіть рядок", "Select a row"),
    "ui.detail.category": ("Категорія: {value}", "Category: {value}"),
    "ui.detail.action": ("Дія: {value}", "Action: {value}"),
    "ui.detail.confidence": ("Впевненість: {value}", "Confidence: {value}"),
    "ui.detail.reason": ("Причина: {value}", "Reason: {value}"),
    "ui.detail.files": ("Файлів: {value}", "Files: {value}"),
    "ui.detail.size": ("Розмір: {value}", "Size: {value}"),
    "ui.detail.patient": ("Пацієнт: {value}", "Patient: {value}"),
    "ui.detail.patient_id": ("Patient ID: {value}", "Patient ID: {value}"),
    "ui.detail.study_date": ("Дата дослідження: {value}", "Study date: {value}"),
    "ui.detail.modality": ("Modality: {value}", "Modality: {value}"),
    "ui.detail.duplicate_of": ("Оригінал дубліката: {value}", "Duplicate of: {value}"),
    "ui.detail.series": ("Серія знімків: {value}", "Image series: {value}"),
    "ui.detail.patient_context": ("Пацієнта визначено: {value}", "Patient determined: {value}"),
    "ui.detail.links": ("Пов'язані елементи ({count}):", "Linked items ({count}):"),
    "ui.detail.links_more": ("… та ще {count}", "… and {count} more"),
    "ui.detail.outside_list": ("(поза списком)", "(outside the list)"),
    "ui.detail.path": ("Шлях:", "Path:"),
    "ui.preview.files": ("{category}\n{count} файл(ів)", "{category}\n{count} file(s)"),
    "ui.preview.slice": ("Зріз {index} з {total}", "Slice {index} of {total}"),
    "ui.preview.unavailable": ("Немає попереднього перегляду\n{error}", "No preview available\n{error}"),
    # UI: actions row
    "ui.for_selected_rows": ("Для виділених рядків:", "For highlighted rows:"),
    "ui.assign": ("Призначити", "Assign"),
    "ui.export_plan": ("Експорт плану", "Export plan"),
    "ui.export_csv": ("Експорт CSV", "Export CSV"),
    "ui.statistics": ("Статистика", "Statistics"),
    "ui.execute_plan": ("Виконати обраний план", "Execute selected plan"),
    # UI: context menu
    "ui.menu.toggle": ("Позначити/зняти", "Check/uncheck"),
    "ui.menu.assign_action": ("Призначити дію", "Assign action"),
    "ui.menu.open_location": ("Відкрити розташування", "Open location"),
    "ui.menu.select_series": ("Позначити всю серію", "Check the whole series"),
    # UI: statuses and dialogs
    "ui.status.add_folders": ("Додайте папки для сканування", "Add folders to scan"),
    "ui.status.items": ("0 елементів", "0 items"),
    "ui.status.scanning": ("Сканування…", "Scanning…"),
    "ui.status.walk": ("Знайдено {count}: {name}", "Found {count}: {name}"),
    "ui.status.phase": ("{phase}: {done}/{total} — {name}", "{phase}: {done}/{total} — {name}"),
    "ui.status.phase_simple": ("{phase}: {name}", "{phase}: {name}"),
    "ui.status.executing": ("Виконання плану…", "Executing the plan…"),
    "ui.status.processed": ("Оброблено {done}/{total}: {name}", "Processed {done}/{total}: {name}"),
    "ui.status.done_operations": (
        "Готово: успішно {succeeded}, помилок {failed}",
        "Done: {succeeded} succeeded, {failed} failed",
    ),
    "ui.status.scan_summary": (
        "Готово: {files} файлів, {size}, {items} груп/елементів за {seconds} с.",
        "Done: {files} files, {size}, {items} groups/items in {seconds} s.",
    ),
    "ui.status.scan_cancelled": ("Сканування скасовано. ", "Scan cancelled. "),
    "ui.status.warnings_suffix": (" Попереджень: {count}.", " Warnings: {count}."),
    "ui.summary_line": (
        "{total} елементів • КТ {ct} • рентген {xray} • фото {photo} • позначено {selected}",
        "{total} items • CT {ct} • X-ray {xray} • photos {photo} • checked {selected}",
    ),
    "ui.msg.no_source_title": ("Немає джерела", "No source"),
    "ui.msg.no_source": ("Спочатку додайте одну або кілька папок.", "First add one or more folders."),
    "ui.msg.scan_warnings_title": (
        "Сканування завершено з попередженнями",
        "Scan finished with warnings",
    ),
    "ui.msg.error_title": ("Помилка", "Error"),
    "ui.msg.no_selection_title": ("Немає виділення", "No selection"),
    "ui.msg.no_selection": (
        "Виділіть один або кілька рядків у таблиці.",
        "Highlight one or more rows in the table.",
    ),
    "ui.msg.no_data_title": ("Немає даних", "No data"),
    "ui.msg.no_data": ("Спочатку виконайте сканування.", "Run a scan first."),
    "ui.msg.open_folder_failed": ("Не вдалося відкрити папку", "Could not open the folder"),
    "ui.msg.save_plan_title": ("Зберегти план", "Save plan"),
    "ui.msg.plan_saved_title": ("План збережено", "Plan saved"),
    "ui.msg.save_csv_title": ("Зберегти CSV", "Save CSV"),
    "ui.msg.csv_saved_title": ("CSV збережено", "CSV saved"),
    "ui.msg.save_report_title": ("Зберегти HTML-звіт", "Save HTML report"),
    "ui.msg.report_saved_title": ("Звіт збережено", "Report saved"),
    "ui.msg.empty_plan_title": ("План порожній", "Plan is empty"),
    "ui.msg.empty_plan": (
        "Позначте галочками файли та призначте їм дію.",
        "Check files and assign an action to them.",
    ),
    "ui.msg.no_destination_title": ("Немає призначення", "No destination"),
    "ui.msg.no_destination": (
        "Оберіть зовнішній диск або папку для архіву й журналу.",
        "Choose an external drive or folder for the archive and log.",
    ),
    "ui.msg.destination_inside_source_title": ("Призначення всередині джерела", "Destination inside source"),
    "ui.msg.destination_inside_source": (
        "Папка призначення знаходиться всередині сканованої папки. Це може створювати повтори при наступному скануванні. Продовжити?",
        "The destination folder is inside a scanned folder. This may create repeats on the next scan. Continue?",
    ),
    "ui.msg.trash_confirm_title": ("Підтвердження очищення", "Cleanup confirmation"),
    "ui.msg.trash_confirm": (
        "{count} елементів буде переміщено до системного Кошика БЕЗ створення копії.\n\nВведіть {word}:",
        "{count} items will be moved to the system Recycle Bin WITHOUT creating a copy.\n\nType {word}:",
    ),
    "ui.msg.trash_word": ("ВИДАЛИТИ", "DELETE"),
    "ui.msg.cancelled_title": ("Скасовано", "Cancelled"),
    "ui.msg.trash_cancelled": ("Видалення скасовано.", "Deletion cancelled."),
    "ui.msg.execute_title": ("Виконати план", "Execute plan"),
    "ui.msg.execute_confirm": (
        "Буде оброблено {count} елементів. Копії перевірятимуться SHA-256. Продовжити?",
        "{count} items will be processed. Copies will be verified with SHA-256. Continue?",
    ),
    "ui.run.title": ("Результат виконання", "Run result"),
    "ui.run.succeeded": ("Успішно: {count}", "Succeeded: {count}"),
    "ui.run.failed": ("Помилок: {count}", "Failed: {count}"),
    "ui.run.manifest": ("Журнал: {path}", "Log: {path}"),
    "ui.run.open_log": ("Відкрити журнал", "Open log"),
    "ui.run.open_destination": ("Відкрити призначення", "Open destination"),
    "ui.run.show_errors": ("Показати помилки", "Show errors"),
    "ui.run.errors_title": ("Помилки виконання", "Run errors"),
    "ui.run.close": ("Закрити", "Close"),
    "ui.choose_source_title": ("Оберіть папку з даними", "Choose a data folder"),
    "ui.choose_destination_title": (
        "Оберіть зовнішній диск або папку призначення",
        "Choose an external drive or destination folder",
    ),
    "ui.choose_archive_title": (
        "Оберіть папку архіву з журналами (_DentalArchive_Logs)",
        "Choose the archive folder with logs (_DentalArchive_Logs)",
    ),
    "ui.verify.running": ("Перевірка архіву…", "Verifying the archive…"),
    "ui.verify.title": ("Перевірка архіву", "Archive verification"),
    "ui.verify.summary": (
        "Перевірено файлів: {total}\nOK: {ok}\nХеш не збігається: {mismatch}\nВідсутні: {missing}\nНечитабельні: {unreadable}",
        "Files checked: {total}\nOK: {ok}\nHash mismatch: {mismatch}\nMissing: {missing}\nUnreadable: {unreadable}",
    ),
    "ui.verify.save": ("Зберегти звіт…", "Save report…"),
    "ui.verify.saved_title": ("Звіт перевірки збережено", "Verification report saved"),
    "ui.stats.title": ("Статистика сканування", "Scan statistics"),
    "ui.stats.save_html": ("Зберегти HTML-звіт…", "Save HTML report…"),
}


def _detect_language() -> str:
    stored = load_settings().get("language")
    if stored in LANGUAGES:
        return str(stored)
    try:
        system = locale.getlocale()[0] or ""
    except (ValueError, TypeError):
        system = ""
    code = system.split("_")[0].split("-")[0].casefold()
    return code if code in LANGUAGES else DEFAULT_LANGUAGE


_current_language = _detect_language()


def get_language() -> str:
    return _current_language


def set_language(code: str, *, persist: bool = True) -> None:
    global _current_language
    if code not in LANGUAGES:
        raise ValueError(f"Unsupported language: {code}")
    _current_language = code
    if persist:
        save_settings({"language": code})


def tr(key: str, **params: object) -> str:
    """Translate ``key`` into the active language, formatting ``params``."""
    entry = _TABLE.get(key)
    if entry is None:
        return key
    template = entry[0] if _current_language == "uk" else entry[1]
    if params:
        try:
            return template.format(**params)
        except (KeyError, IndexError):
            return template
    return template
