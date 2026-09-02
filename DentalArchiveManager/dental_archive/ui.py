from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from collections import Counter
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from .models import Action, Category, ScanItem
from .operations import execute_plan, human_size
from .scanner import ScanReport, scan_roots

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None
    ImageTk = None


BG = "#f3f6f8"
PANEL = "#ffffff"
NAVY = "#12354a"
TEAL = "#008f95"
TEAL_DARK = "#006d73"
TEXT = "#16313f"
MUTED = "#667985"
RED = "#bb2d3b"


def _open_in_file_manager(path: Path) -> None:
    target = path if path.is_dir() else path.parent
    if sys.platform.startswith("win"):
        os.startfile(str(target))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(target)])
    else:
        subprocess.Popen(["xdg-open", str(target)])


class DentalArchiveApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Dental Archive Manager")
        self.root.geometry("1480x850")
        self.root.minsize(1120, 680)
        self.root.configure(bg=BG)

        self.sources: list[Path] = []
        self.items: list[ScanItem] = []
        self.item_by_id: dict[str, ScanItem] = {}
        self.ui_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.cancel_event = threading.Event()
        self.preview_photo = None

        self.destination_var = tk.StringVar()
        self.search_var = tk.StringVar()
        self.category_var = tk.StringVar(value="Усі категорії")
        self.action_var = tk.StringVar(value=Action.COPY.label)
        self.status_var = tk.StringVar(value="Додайте папки для сканування")
        self.summary_var = tk.StringVar(value="0 елементів")
        self.duplicate_var = tk.BooleanVar(value=True)

        self._configure_style()
        self._build_ui()
        self.root.after(120, self._poll_queue)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=PANEL, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Title.TLabel", background=NAVY, foreground="white", font=("Segoe UI Semibold", 19))
        style.configure("Subtitle.TLabel", background=NAVY, foreground="#c8dbe4", font=("Segoe UI", 10))
        style.configure("Primary.TButton", font=("Segoe UI Semibold", 10), padding=(14, 9), foreground="white", background=TEAL)
        style.map("Primary.TButton", background=[("active", TEAL_DARK), ("disabled", "#9cb8ba")])
        style.configure("Danger.TButton", font=("Segoe UI Semibold", 10), padding=(12, 8), foreground="white", background=RED)
        style.map("Danger.TButton", background=[("active", "#8f1f2a")])
        style.configure("TButton", font=("Segoe UI", 10), padding=(10, 7))
        style.configure("Treeview", background="white", fieldbackground="white", foreground=TEXT, rowheight=30, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", background="#e5edf1", foreground=TEXT, font=("Segoe UI Semibold", 9), padding=6)
        style.map("Treeview", background=[("selected", "#ccebed")], foreground=[("selected", TEXT)])

    def _build_ui(self) -> None:
        header = tk.Frame(self.root, bg=NAVY, height=84)
        header.pack(fill="x")
        header.pack_propagate(False)
        title_block = ttk.Frame(header, style="Panel.TFrame")
        title_block.configure(style="TFrame")
        title_block.pack(side="left", padx=24, pady=14)
        ttk.Label(title_block, text="Dental Archive Manager", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            title_block,
            text="Офлайн-сортування стоматологічних файлів • без автоматичного видалення",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(3, 0))
        offline = tk.Label(header, text="● OFFLINE", bg="#174b5a", fg="#8ff0d0", padx=14, pady=7, font=("Segoe UI Semibold", 9))
        offline.pack(side="right", padx=24)

        setup = ttk.Frame(self.root, style="Panel.TFrame", padding=14)
        setup.pack(fill="x", padx=16, pady=(14, 8))

        source_column = ttk.Frame(setup, style="Panel.TFrame")
        source_column.pack(side="left", fill="both", expand=True)
        ttk.Label(source_column, text="Папки-джерела", style="Panel.TLabel", font=("Segoe UI Semibold", 10)).pack(anchor="w")
        source_row = ttk.Frame(source_column, style="Panel.TFrame")
        source_row.pack(fill="x", pady=(6, 0))
        self.source_list = tk.Listbox(
            source_row,
            height=2,
            bg="#f8fafb",
            fg=TEXT,
            relief="solid",
            borderwidth=1,
            highlightthickness=0,
            font=("Segoe UI", 9),
        )
        self.source_list.pack(side="left", fill="x", expand=True)
        source_buttons = ttk.Frame(source_row, style="Panel.TFrame")
        source_buttons.pack(side="left", padx=(8, 0))
        ttk.Button(source_buttons, text="+ Додати", command=self._add_source).pack(fill="x")
        ttk.Button(source_buttons, text="Прибрати", command=self._remove_source).pack(fill="x", pady=(4, 0))

        destination_column = ttk.Frame(setup, style="Panel.TFrame")
        destination_column.pack(side="left", fill="x", expand=True, padx=(18, 0))
        ttk.Label(destination_column, text="Диск / папка призначення", style="Panel.TLabel", font=("Segoe UI Semibold", 10)).pack(anchor="w")
        destination_row = ttk.Frame(destination_column, style="Panel.TFrame")
        destination_row.pack(fill="x", pady=(6, 0))
        ttk.Entry(destination_row, textvariable=self.destination_var).pack(side="left", fill="x", expand=True, ipady=6)
        ttk.Button(destination_row, text="Обрати…", command=self._choose_destination).pack(side="left", padx=(8, 0))
        ttk.Checkbutton(
            destination_column,
            text="Шукати точні дублікати (SHA-256)",
            variable=self.duplicate_var,
        ).pack(anchor="w", pady=(8, 0))

        scan_buttons = ttk.Frame(setup, style="Panel.TFrame")
        scan_buttons.pack(side="right", padx=(18, 0), anchor="s")
        self.scan_button = ttk.Button(scan_buttons, text="Сканувати", style="Primary.TButton", command=self._start_scan)
        self.scan_button.pack(fill="x")
        self.cancel_button = ttk.Button(scan_buttons, text="Скасувати", command=self.cancel_event.set, state="disabled")
        self.cancel_button.pack(fill="x", pady=(5, 0))

        controls = ttk.Frame(self.root, padding=(16, 4))
        controls.pack(fill="x")
        ttk.Label(controls, text="Пошук:").pack(side="left")
        search = ttk.Entry(controls, textvariable=self.search_var, width=28)
        search.pack(side="left", padx=(6, 12), ipady=4)
        search.bind("<KeyRelease>", lambda _event: self._refresh_tree())
        ttk.Label(controls, text="Категорія:").pack(side="left")
        categories = ["Усі категорії", *(category.label for category in Category)]
        self.category_box = ttk.Combobox(controls, textvariable=self.category_var, values=categories, state="readonly", width=25)
        self.category_box.pack(side="left", padx=(6, 12))
        self.category_box.bind("<<ComboboxSelected>>", lambda _event: self._refresh_tree())
        ttk.Button(controls, text="Позначити видимі", command=lambda: self._set_visible_checked(True)).pack(side="left")
        ttk.Button(controls, text="Зняти видимі", command=lambda: self._set_visible_checked(False)).pack(side="left", padx=(5, 0))
        ttk.Button(controls, text="Застосувати рекомендації", command=self._apply_suggestions).pack(side="left", padx=(5, 0))
        ttk.Label(controls, textvariable=self.summary_var, foreground=MUTED).pack(side="right")

        main = ttk.Panedwindow(self.root, orient="horizontal")
        main.pack(fill="both", expand=True, padx=16, pady=(4, 8))

        table_panel = ttk.Frame(main, style="Panel.TFrame", padding=8)
        detail_panel = ttk.Frame(main, style="Panel.TFrame", padding=12)
        main.add(table_panel, weight=5)
        main.add(detail_panel, weight=2)

        columns = ("checked", "action", "category", "name", "files", "size", "patient", "path")
        self.tree = ttk.Treeview(table_panel, columns=columns, show="headings", selectmode="extended")
        headings = {
            "checked": "✓",
            "action": "Дія",
            "category": "Категорія",
            "name": "Дослідження / файл",
            "files": "Файлів",
            "size": "Розмір",
            "patient": "Пацієнт / дата",
            "path": "Джерело",
        }
        widths = {"checked": 44, "action": 105, "category": 150, "name": 250, "files": 65, "size": 80, "patient": 160, "path": 330}
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], minwidth=40, stretch=column in {"name", "path"})
        yscroll = ttk.Scrollbar(table_panel, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(table_panel, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        table_panel.rowconfigure(0, weight=1)
        table_panel.columnconfigure(0, weight=1)
        self.tree.bind("<Button-1>", self._tree_click)
        self.tree.bind("<space>", lambda _event: self._toggle_selected_rows())
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._show_selected_details())
        self.tree.bind("<Double-1>", lambda _event: self._open_selected_location())

        ttk.Label(detail_panel, text="Перегляд і деталі", style="Panel.TLabel", font=("Segoe UI Semibold", 12)).pack(anchor="w")
        self.preview_label = tk.Label(
            detail_panel,
            text="Оберіть рядок",
            bg="#eef3f5",
            fg=MUTED,
            height=12,
            anchor="center",
            font=("Segoe UI", 10),
        )
        self.preview_label.pack(fill="x", pady=(10, 10))
        self.detail_text = tk.Text(
            detail_panel,
            height=18,
            wrap="word",
            bg=PANEL,
            fg=TEXT,
            relief="flat",
            font=("Segoe UI", 9),
        )
        self.detail_text.pack(fill="both", expand=True)
        self.detail_text.configure(state="disabled")

        action_panel = ttk.Frame(self.root, style="Panel.TFrame", padding=(16, 10))
        action_panel.pack(fill="x", padx=16, pady=(0, 8))
        ttk.Label(action_panel, text="Для виділених рядків:", style="Panel.TLabel").pack(side="left")
        action_values = [action.label for action in Action]
        ttk.Combobox(action_panel, textvariable=self.action_var, values=action_values, state="readonly", width=18).pack(side="left", padx=(8, 5))
        ttk.Button(action_panel, text="Призначити", command=self._assign_action_to_rows).pack(side="left")
        ttk.Button(action_panel, text="Експорт плану", command=self._export_plan).pack(side="left", padx=(8, 0))
        self.execute_button = ttk.Button(action_panel, text="Виконати обраний план", style="Primary.TButton", command=self._start_execution)
        self.execute_button.pack(side="right")

        footer = ttk.Frame(self.root, padding=(16, 2, 16, 10))
        footer.pack(fill="x")
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=300)
        self.progress.pack(side="left", fill="x", expand=True)
        ttk.Label(footer, textvariable=self.status_var, foreground=MUTED).pack(side="left", padx=(12, 0))

    def _add_source(self) -> None:
        selected = filedialog.askdirectory(title="Оберіть папку з даними")
        if not selected:
            return
        path = Path(selected)
        if path not in self.sources:
            self.sources.append(path)
            self.source_list.insert("end", str(path))

    def _remove_source(self) -> None:
        selected = list(self.source_list.curselection())
        for index in reversed(selected):
            self.source_list.delete(index)
            self.sources.pop(index)

    def _choose_destination(self) -> None:
        selected = filedialog.askdirectory(title="Оберіть зовнішній диск або папку призначення")
        if selected:
            self.destination_var.set(selected)

    def _start_scan(self) -> None:
        if not self.sources:
            messagebox.showwarning("Немає джерела", "Спочатку додайте одну або кілька папок.")
            return
        self.cancel_event.clear()
        self.items.clear()
        self.item_by_id.clear()
        self._refresh_tree()
        self.scan_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self.status_var.set("Сканування…")
        source_snapshot = tuple(self.sources)
        detect_duplicates = self.duplicate_var.get()

        def worker() -> None:
            try:
                report = scan_roots(
                    source_snapshot,
                    detect_duplicates=detect_duplicates,
                    cancel_event=self.cancel_event,
                    progress=lambda count, path: self.ui_queue.put(("scan_progress", (count, path))),
                )
                self.ui_queue.put(("scan_done", report))
            except Exception as exc:
                self.ui_queue.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_queue(self) -> None:
        try:
            while True:
                event, payload = self.ui_queue.get_nowait()
                if event == "scan_progress":
                    count, path = payload  # type: ignore[misc]
                    self.status_var.set(f"Знайдено {count}: {Path(path).name}")
                elif event == "scan_done":
                    self._finish_scan(payload)  # type: ignore[arg-type]
                elif event == "operation_progress":
                    completed, total, path = payload  # type: ignore[misc]
                    self.progress.configure(maximum=max(total, 1), value=completed)
                    self.status_var.set(f"Оброблено {completed}/{total}: {Path(path).name}")
                elif event == "operation_done":
                    self._finish_execution(payload)
                elif event == "error":
                    self._set_idle()
                    messagebox.showerror("Помилка", str(payload))
        except queue.Empty:
            pass
        self.root.after(120, self._poll_queue)

    def _finish_scan(self, report: ScanReport) -> None:
        self.items = report.items
        self.item_by_id = {item.item_id: item for item in self.items}
        self._refresh_tree()
        self._set_idle()
        message = f"Готово: {report.files_seen} файлів, {human_size(report.bytes_seen)}, {len(report.items)} груп/елементів."
        if report.cancelled:
            message = "Сканування скасовано. " + message
        if report.warnings:
            message += f" Попереджень: {len(report.warnings)}."
        self.status_var.set(message)
        if report.warnings:
            preview = "\n".join(report.warnings[:12])
            messagebox.showwarning("Сканування завершено з попередженнями", f"{message}\n\n{preview}")

    def _set_idle(self) -> None:
        self.progress.stop()
        self.progress.configure(mode="indeterminate", value=0)
        self.scan_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        self.execute_button.configure(state="normal")

    def _filtered_items(self) -> list[ScanItem]:
        query = self.search_var.get().strip().casefold()
        category_label = self.category_var.get()
        result = []
        for item in self.items:
            if category_label != "Усі категорії" and item.category.label != category_label:
                continue
            haystack = " ".join(
                (
                    item.display_name,
                    item.patient_name,
                    item.patient_id,
                    item.reason,
                    str(item.primary_path),
                )
            ).casefold()
            if query and query not in haystack:
                continue
            result.append(item)
        return result

    def _refresh_tree(self) -> None:
        current_selection = set(self.tree.selection()) if hasattr(self, "tree") else set()
        if not hasattr(self, "tree"):
            return
        self.tree.delete(*self.tree.get_children())
        visible = self._filtered_items()
        for item in visible:
            patient_date = " / ".join(value for value in (item.patient_name or item.patient_id, item.study_date) if value)
            self.tree.insert(
                "",
                "end",
                iid=item.item_id,
                values=(
                    "☑" if item.selected else "☐",
                    item.action.label,
                    item.category.label,
                    item.display_name,
                    item.file_count,
                    human_size(item.total_size),
                    patient_date,
                    str(item.primary_path),
                ),
            )
        for item_id in current_selection:
            if self.tree.exists(item_id):
                self.tree.selection_add(item_id)

        selected = [item for item in self.items if item.selected]
        counts = Counter(item.category for item in self.items)
        ct_count = counts[Category.CT]
        xray_count = counts[Category.XRAY]
        photo_count = counts[Category.PHOTO]
        self.summary_var.set(
            f"{len(self.items)} елементів • КТ {ct_count} • рентген {xray_count} • фото {photo_count} • позначено {len(selected)}"
        )

    def _tree_click(self, event: tk.Event) -> None:
        region = self.tree.identify_region(event.x, event.y)
        column = self.tree.identify_column(event.x)
        row = self.tree.identify_row(event.y)
        if region == "cell" and column == "#1" and row:
            item = self.item_by_id[row]
            item.selected = not item.selected
            self._refresh_tree()
            self.tree.selection_set(row)

    def _toggle_selected_rows(self) -> None:
        rows = self.tree.selection()
        if not rows:
            return
        target = not all(self.item_by_id[row].selected for row in rows)
        for row in rows:
            self.item_by_id[row].selected = target
        self._refresh_tree()

    def _set_visible_checked(self, value: bool) -> None:
        for item in self._filtered_items():
            item.selected = value
        self._refresh_tree()

    def _apply_suggestions(self) -> None:
        for item in self._filtered_items():
            item.action = item.suggested_action
            item.selected = item.suggested_action != Action.KEEP
        self._refresh_tree()

    def _assign_action_to_rows(self) -> None:
        label = self.action_var.get()
        action = next(action for action in Action if action.label == label)
        rows = self.tree.selection()
        if not rows:
            messagebox.showinfo("Немає виділення", "Виділіть один або кілька рядків у таблиці.")
            return
        for row in rows:
            item = self.item_by_id[row]
            item.action = action
            item.selected = action != Action.KEEP
        self._refresh_tree()

    def _show_selected_details(self) -> None:
        rows = self.tree.selection()
        if not rows:
            return
        item = self.item_by_id[rows[0]]
        lines = [
            f"Категорія: {item.category.label}",
            f"Дія: {item.action.label}",
            f"Впевненість: {item.confidence}",
            f"Причина: {item.reason}",
            f"Файлів: {item.file_count}",
            f"Розмір: {human_size(item.total_size)}",
        ]
        if item.patient_name:
            lines.append(f"Пацієнт: {item.patient_name}")
        if item.patient_id:
            lines.append(f"Patient ID: {item.patient_id}")
        if item.study_date:
            lines.append(f"Дата дослідження: {item.study_date}")
        if item.modality:
            lines.append(f"Modality: {item.modality}")
        if item.duplicate_of:
            lines.append(f"Оригінал дубліката: {item.duplicate_of}")
        if item.metadata.get("series"):
            lines.append(f"Серія знімків: {item.metadata['series']}")
        if item.metadata.get("patient_context"):
            lines.append(f"Пацієнта визначено: {item.metadata['patient_context']}")
        if item.links:
            lines.extend(("", f"Пов'язані елементи ({len(item.links)}):"))
            for link in item.links[:10]:
                other = self.item_by_id.get(link["item_id"])
                label = other.display_name if other else "(поза списком)"
                lines.append(f"• {label} — {link['relation']}")
            if len(item.links) > 10:
                lines.append(f"… та ще {len(item.links) - 10}")
        lines.extend(("", "Шлях:", str(item.primary_path)))

        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("1.0", "\n".join(lines))
        self.detail_text.configure(state="disabled")
        self._show_preview(item)

    def _show_preview(self, item: ScanItem) -> None:
        self.preview_photo = None
        path = item.primary_path
        if Image is None or ImageTk is None or path.suffix.casefold() not in {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp"}:
            self.preview_label.configure(image="", text=f"{item.category.label}\n{item.file_count} файл(ів)")
            return
        try:
            with Image.open(path) as image:
                image.thumbnail((360, 260))
                preview = image.convert("RGB").copy()
            self.preview_photo = ImageTk.PhotoImage(preview)
            self.preview_label.configure(image=self.preview_photo, text="")
        except Exception as exc:
            self.preview_label.configure(image="", text=f"Немає попереднього перегляду\n{exc}")

    def _open_selected_location(self) -> None:
        rows = self.tree.selection()
        if rows:
            try:
                _open_in_file_manager(self.item_by_id[rows[0]].primary_path)
            except Exception as exc:
                messagebox.showerror("Не вдалося відкрити папку", str(exc))

    def _export_plan(self) -> None:
        if not self.items:
            messagebox.showinfo("Немає даних", "Спочатку виконайте сканування.")
            return
        filename = filedialog.asksaveasfilename(
            title="Зберегти план",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialfile="dental_archive_plan.json",
        )
        if not filename:
            return
        payload = {
            "sources": [str(path) for path in self.sources],
            "destination": self.destination_var.get(),
            "items": [item.to_dict() for item in self.items],
        }
        Path(filename).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        messagebox.showinfo("План збережено", filename)

    def _start_execution(self) -> None:
        selected = [item for item in self.items if item.selected and item.action != Action.KEEP]
        if not selected:
            messagebox.showinfo("План порожній", "Позначте галочками файли та призначте їм дію.")
            return
        destination_text = self.destination_var.get().strip()
        if not destination_text:
            messagebox.showwarning("Немає призначення", "Оберіть зовнішній диск або папку для архіву й журналу.")
            return
        destination = Path(destination_text)
        try:
            resolved_destination = destination.expanduser().resolve()
            if any(resolved_destination == source.resolve() or resolved_destination.is_relative_to(source.resolve()) for source in self.sources):
                if not messagebox.askyesno(
                    "Призначення всередині джерела",
                    "Папка призначення знаходиться всередині сканованої папки. Це може створювати повтори при наступному скануванні. Продовжити?",
                ):
                    return
        except OSError:
            pass

        direct_trash = [item for item in selected if item.action == Action.TRASH]
        if direct_trash:
            confirmation = simpledialog.askstring(
                "Підтвердження очищення",
                f"{len(direct_trash)} елементів буде переміщено до системного Кошика БЕЗ створення копії.\n\nВведіть ВИДАЛИТИ:",
            )
            if confirmation != "ВИДАЛИТИ":
                messagebox.showinfo("Скасовано", "Видалення скасовано.")
                return
        elif not messagebox.askyesno(
            "Виконати план",
            f"Буде оброблено {len(selected)} елементів. Копії перевірятимуться SHA-256. Продовжити?",
        ):
            return

        self.execute_button.configure(state="disabled")
        self.scan_button.configure(state="disabled")
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0, maximum=sum(item.file_count for item in selected))
        self.status_var.set("Виконання плану…")
        plan_snapshot = tuple(self.items)

        def worker() -> None:
            try:
                summary = execute_plan(
                    plan_snapshot,
                    destination,
                    progress=lambda done, total, path: self.ui_queue.put(("operation_progress", (done, total, path))),
                )
                self.ui_queue.put(("operation_done", summary))
            except Exception as exc:
                self.ui_queue.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_execution(self, summary: object) -> None:
        self._set_idle()
        succeeded = getattr(summary, "succeeded", 0)
        failed = getattr(summary, "failed", 0)
        manifest = getattr(summary, "manifest_path", None)
        self.status_var.set(f"Готово: успішно {succeeded}, помилок {failed}")
        if failed:
            messagebox.showwarning("План виконано з помилками", f"Успішно: {succeeded}\nПомилок: {failed}\nЖурнал: {manifest}")
        else:
            messagebox.showinfo("План виконано", f"Успішно: {succeeded}\nЖурнал: {manifest}")


def run() -> None:
    root = tk.Tk()
    DentalArchiveApp(root)
    root.mainloop()
