from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import __version__, viewmodel
from .filetype import Kind, sniff_format
from .i18n import LANGUAGES, get_language, set_language, tr
from .models import Action, Category, ScanItem
from .operations import RunSummary, execute_plan, human_size
from .reporting import build_statistics, write_html_report, write_scan_csv
from .scanner import ScanReport, scan_roots
from .settings import load_settings, save_settings
from .verify import VerifyReport, verify_archive, write_verify_report_text

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None
    ImageTk = None

try:  # Optional: enables DICOM slice previews when available.
    import numpy
except ImportError:
    numpy = None

try:
    import pydicom
except ImportError:
    pydicom = None


BG = "#f3f6f8"
PANEL = "#ffffff"
NAVY = "#12354a"
TEAL = "#008f95"
TEAL_DARK = "#006d73"
TEXT = "#16313f"
MUTED = "#667985"
RED = "#bb2d3b"

ROW_COLORS = {
    "duplicate": "#fdecec",
    "junk": "#fff4e2",
    "dicom": "#e9f3fa",
    "review": "#f4eefb",
}

LANGUAGE_NAMES = {"uk": "Українська", "en": "English"}

CONFIDENCE_LEVELS = ("high", "medium", "low")

DICOM_CATEGORIES = {Category.CT, Category.XRAY, Category.DICOM_OTHER}


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
        self.last_report: ScanReport | None = None
        self.ui_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.cancel_event = threading.Event()
        self.preview_photo = None

        self.filter_category: Category | None = None
        self.filter_action: Action | None = None
        self.filter_confidence: str | None = None
        self.sort_column: str | None = None
        self.sort_reverse = False
        self.assign_action: Action = Action.COPY
        self._search_job: str | None = None
        self._progress_mode = ""
        self._busy = False

        self.destination_var = tk.StringVar()
        self.search_var = tk.StringVar()
        self.status_var = tk.StringVar()
        self.summary_var = tk.StringVar()
        self.duplicate_var = tk.BooleanVar(value=True)
        self.only_selected_var = tk.BooleanVar(value=False)

        stored = load_settings()
        self.destination_var.set(str(stored.get("last_destination", "")))
        for text in stored.get("last_sources", []) or []:
            path = Path(text)
            if path.is_dir() and path not in self.sources:
                self.sources.append(path)

        self.status_var.set(tr("ui.status.add_folders"))
        self.summary_var.set(tr("ui.status.items"))

        self._configure_style()
        self._build_ui()
        self.root.after(120, self._poll_queue)

    # ------------------------------------------------------------------ setup

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

    def _rebuild_ui(self) -> None:
        for child in self.root.winfo_children():
            child.destroy()
        self.preview_photo = None
        self.status_var.set(tr("ui.status.add_folders"))
        self._build_ui()
        self._refresh_tree()

    def _build_ui(self) -> None:
        header = tk.Frame(self.root, bg=NAVY, height=84)
        header.pack(fill="x")
        header.pack_propagate(False)
        title_block = ttk.Frame(header, style="Panel.TFrame")
        title_block.configure(style="TFrame")
        title_block.pack(side="left", padx=24, pady=14)
        ttk.Label(title_block, text=tr("ui.app_title"), style="Title.TLabel").pack(anchor="w")
        ttk.Label(title_block, text=tr("ui.subtitle"), style="Subtitle.TLabel").pack(anchor="w", pady=(3, 0))
        offline = tk.Label(header, text="● OFFLINE", bg="#174b5a", fg="#8ff0d0", padx=14, pady=7, font=("Segoe UI Semibold", 9))
        offline.pack(side="right", padx=24)
        language_block = tk.Frame(header, bg=NAVY)
        language_block.pack(side="right", padx=(0, 4))
        tk.Label(language_block, text=tr("ui.language"), bg=NAVY, fg="#c8dbe4", font=("Segoe UI", 9)).pack(side="left", padx=(0, 6))
        self.language_box = ttk.Combobox(
            language_block,
            values=[LANGUAGE_NAMES[code] for code in LANGUAGES],
            state="readonly",
            width=11,
        )
        self.language_box.current(LANGUAGES.index(get_language()))
        self.language_box.pack(side="left")
        self.language_box.bind("<<ComboboxSelected>>", self._on_language_selected)

        setup = ttk.Frame(self.root, style="Panel.TFrame", padding=14)
        setup.pack(fill="x", padx=16, pady=(14, 8))

        source_column = ttk.Frame(setup, style="Panel.TFrame")
        source_column.pack(side="left", fill="both", expand=True)
        ttk.Label(source_column, text=tr("ui.sources"), style="Panel.TLabel", font=("Segoe UI Semibold", 10)).pack(anchor="w")
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
        for path in self.sources:
            self.source_list.insert("end", str(path))
        source_buttons = ttk.Frame(source_row, style="Panel.TFrame")
        source_buttons.pack(side="left", padx=(8, 0))
        ttk.Button(source_buttons, text=tr("ui.add"), command=self._add_source).pack(fill="x")
        ttk.Button(source_buttons, text=tr("ui.remove"), command=self._remove_source).pack(fill="x", pady=(4, 0))

        destination_column = ttk.Frame(setup, style="Panel.TFrame")
        destination_column.pack(side="left", fill="x", expand=True, padx=(18, 0))
        ttk.Label(destination_column, text=tr("ui.destination"), style="Panel.TLabel", font=("Segoe UI Semibold", 10)).pack(anchor="w")
        destination_row = ttk.Frame(destination_column, style="Panel.TFrame")
        destination_row.pack(fill="x", pady=(6, 0))
        ttk.Entry(destination_row, textvariable=self.destination_var).pack(side="left", fill="x", expand=True, ipady=6)
        ttk.Button(destination_row, text=tr("ui.choose"), command=self._choose_destination).pack(side="left", padx=(8, 0))
        ttk.Checkbutton(destination_column, text=tr("ui.detect_duplicates"), variable=self.duplicate_var).pack(anchor="w", pady=(8, 0))

        scan_buttons = ttk.Frame(setup, style="Panel.TFrame")
        scan_buttons.pack(side="right", padx=(18, 0), anchor="s")
        self.scan_button = ttk.Button(scan_buttons, text=tr("ui.scan"), style="Primary.TButton", command=self._start_scan)
        self.scan_button.pack(fill="x")
        self.cancel_button = ttk.Button(scan_buttons, text=tr("ui.cancel"), command=self.cancel_event.set, state="disabled")
        self.cancel_button.pack(fill="x", pady=(5, 0))

        controls = ttk.Frame(self.root, padding=(16, 4))
        controls.pack(fill="x")
        ttk.Label(controls, text=tr("ui.search")).pack(side="left")
        search = ttk.Entry(controls, textvariable=self.search_var, width=24)
        search.pack(side="left", padx=(6, 12), ipady=4)
        search.bind("<KeyRelease>", self._on_search_changed)

        ttk.Label(controls, text=tr("ui.category_filter")).pack(side="left")
        self._category_choices: list[Category | None] = [None, *Category]
        self.category_box = ttk.Combobox(controls, state="readonly", width=24)
        self.category_box.pack(side="left", padx=(6, 10))
        self.category_box.bind("<<ComboboxSelected>>", self._on_category_selected)

        ttk.Label(controls, text=tr("ui.action_filter")).pack(side="left")
        self._action_choices: list[Action | None] = [None, *Action]
        self.action_filter_box = ttk.Combobox(
            controls,
            state="readonly",
            width=15,
            values=[tr("ui.all_actions"), *(action.label for action in Action)],
        )
        self.action_filter_box.current(self._action_choices.index(self.filter_action))
        self.action_filter_box.pack(side="left", padx=(6, 10))
        self.action_filter_box.bind("<<ComboboxSelected>>", self._on_action_filter_selected)

        ttk.Label(controls, text=tr("ui.confidence_filter")).pack(side="left")
        self._confidence_choices: list[str | None] = [None, *CONFIDENCE_LEVELS]
        self.confidence_box = ttk.Combobox(
            controls,
            state="readonly",
            width=12,
            values=[tr("ui.all_confidences"), *(tr(f"confidence.{level}") for level in CONFIDENCE_LEVELS)],
        )
        self.confidence_box.current(self._confidence_choices.index(self.filter_confidence))
        self.confidence_box.pack(side="left", padx=(6, 10))
        self.confidence_box.bind("<<ComboboxSelected>>", self._on_confidence_selected)

        ttk.Checkbutton(controls, text=tr("ui.only_selected"), variable=self.only_selected_var, command=self._refresh_tree).pack(side="left")
        ttk.Label(controls, textvariable=self.summary_var, foreground=MUTED).pack(side="right")

        bulk_row = ttk.Frame(self.root, padding=(16, 0, 16, 4))
        bulk_row.pack(fill="x")
        ttk.Button(bulk_row, text=tr("ui.check_visible"), command=lambda: self._set_visible_checked(True)).pack(side="left")
        ttk.Button(bulk_row, text=tr("ui.uncheck_visible"), command=lambda: self._set_visible_checked(False)).pack(side="left", padx=(5, 0))
        ttk.Button(bulk_row, text=tr("ui.apply_suggestions"), command=self._apply_suggestions).pack(side="left", padx=(5, 0))

        main = ttk.Panedwindow(self.root, orient="horizontal")
        main.pack(fill="both", expand=True, padx=16, pady=(4, 8))

        table_panel = ttk.Frame(main, style="Panel.TFrame", padding=8)
        detail_panel = ttk.Frame(main, style="Panel.TFrame", padding=12)
        main.add(table_panel, weight=5)
        main.add(detail_panel, weight=2)

        columns = viewmodel.SORTABLE_COLUMNS
        self.tree = ttk.Treeview(table_panel, columns=columns, show="headings", selectmode="extended")
        widths = {"checked": 44, "action": 105, "category": 150, "name": 250, "files": 65, "size": 80, "patient": 160, "path": 330}
        for column in columns:
            self.tree.heading(column, text=self._heading_text(column), command=lambda c=column: self._sort_by(c))
            self.tree.column(column, width=widths[column], minwidth=40, stretch=column in {"name", "path"})
        for tag, color in ROW_COLORS.items():
            self.tree.tag_configure(tag, background=color)
        yscroll = ttk.Scrollbar(table_panel, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(table_panel, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        table_panel.rowconfigure(0, weight=1)
        table_panel.columnconfigure(0, weight=1)
        self.tree.bind("<Button-1>", self._tree_click)
        self.tree.bind("<Button-3>", self._show_context_menu)
        self.tree.bind("<space>", lambda _event: self._toggle_selected_rows())
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._show_selected_details())
        self.tree.bind("<Double-1>", lambda _event: self._open_selected_location())

        ttk.Label(detail_panel, text=tr("ui.details_title"), style="Panel.TLabel", font=("Segoe UI Semibold", 12)).pack(anchor="w")
        self.preview_label = tk.Label(
            detail_panel,
            text=tr("ui.select_row"),
            bg="#eef3f5",
            fg=MUTED,
            height=12,
            anchor="center",
            compound="top",
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
        ttk.Label(action_panel, text=tr("ui.for_selected_rows"), style="Panel.TLabel").pack(side="left")
        self._assign_choices = list(Action)
        self.assign_box = ttk.Combobox(
            action_panel,
            values=[action.label for action in Action],
            state="readonly",
            width=18,
        )
        self.assign_box.current(self._assign_choices.index(self.assign_action))
        self.assign_box.pack(side="left", padx=(8, 5))
        self.assign_box.bind("<<ComboboxSelected>>", self._on_assign_selected)
        ttk.Button(action_panel, text=tr("ui.assign"), command=self._assign_action_to_rows).pack(side="left")
        ttk.Button(action_panel, text=tr("ui.export_plan"), command=self._export_plan).pack(side="left", padx=(8, 0))
        ttk.Button(action_panel, text=tr("ui.export_csv"), command=self._export_csv).pack(side="left", padx=(5, 0))
        ttk.Button(action_panel, text=tr("ui.statistics"), command=self._show_statistics).pack(side="left", padx=(5, 0))
        self.verify_button = ttk.Button(action_panel, text=tr("ui.verify_archive"), command=self._start_verify)
        self.verify_button.pack(side="left", padx=(5, 0))
        self.execute_button = ttk.Button(action_panel, text=tr("ui.execute_plan"), style="Primary.TButton", command=self._start_execution)
        self.execute_button.pack(side="right")

        footer = ttk.Frame(self.root, padding=(16, 2, 16, 10))
        footer.pack(fill="x")
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=300)
        self.progress.pack(side="left", fill="x", expand=True)
        ttk.Label(footer, textvariable=self.status_var, foreground=MUTED).pack(side="left", padx=(12, 0))

        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label=tr("ui.menu.toggle"), command=self._toggle_selected_rows)
        assign_menu = tk.Menu(self.context_menu, tearoff=0)
        for action in Action:
            assign_menu.add_command(label=action.label, command=lambda a=action: self._assign_action(a))
        self.context_menu.add_cascade(label=tr("ui.menu.assign_action"), menu=assign_menu)
        self.context_menu.add_command(label=tr("ui.menu.open_location"), command=self._open_selected_location)
        self.context_menu.add_command(label=tr("ui.menu.select_series"), command=self._select_series)
        self._series_menu_index = self.context_menu.index("end")

        self._update_category_values()

    # ------------------------------------------------------------- translation

    def _heading_text(self, column: str) -> str:
        text = tr(f"ui.col.{column}")
        if column == self.sort_column:
            text += " ▼" if self.sort_reverse else " ▲"
        return text

    def _on_language_selected(self, _event: object) -> None:
        code = LANGUAGES[self.language_box.current()]
        if code != get_language():
            set_language(code)
            self._rebuild_ui()

    # -------------------------------------------------------------- source rows

    def _add_source(self) -> None:
        selected = filedialog.askdirectory(title=tr("ui.choose_source_title"))
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
        selected = filedialog.askdirectory(title=tr("ui.choose_destination_title"))
        if selected:
            self.destination_var.set(selected)

    # ------------------------------------------------------------------- scan

    def _start_scan(self) -> None:
        if not self.sources:
            messagebox.showwarning(tr("ui.msg.no_source_title"), tr("ui.msg.no_source"))
            return
        self.cancel_event.clear()
        self.items.clear()
        self.item_by_id.clear()
        self.last_report = None
        self._refresh_tree()
        self._set_busy(True)
        self.status_var.set(tr("ui.status.scanning"))
        save_settings({"last_sources": [str(path) for path in self.sources]})
        source_snapshot = tuple(self.sources)
        detect_duplicates = self.duplicate_var.get()

        def worker() -> None:
            try:
                report = scan_roots(
                    source_snapshot,
                    detect_duplicates=detect_duplicates,
                    cancel_event=self.cancel_event,
                    phase_progress=lambda phase, done, total, detail: self.ui_queue.put(
                        ("phase_progress", (phase, done, total, detail))
                    ),
                )
                self.ui_queue.put(("scan_done", report))
            except Exception as exc:
                self.ui_queue.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_queue(self) -> None:
        try:
            while True:
                event, payload = self.ui_queue.get_nowait()
                if event == "phase_progress":
                    phase, done, total, detail = payload  # type: ignore[misc]
                    self._update_phase_progress(str(phase), int(done), total, str(detail))
                elif event == "scan_done":
                    self._finish_scan(payload)  # type: ignore[arg-type]
                elif event == "operation_progress":
                    completed, total, path = payload  # type: ignore[misc]
                    self._set_progress_determinate(int(completed), max(int(total), 1))
                    self.status_var.set(tr("ui.status.processed", done=completed, total=total, name=Path(str(path)).name))
                elif event == "operation_done":
                    self._finish_execution(payload)  # type: ignore[arg-type]
                elif event == "verify_progress":
                    completed, total, path = payload  # type: ignore[misc]
                    self._set_progress_determinate(int(completed), max(int(total), 1))
                    self.status_var.set(tr("ui.status.processed", done=completed, total=total, name=Path(str(path)).name))
                elif event == "verify_done":
                    self._finish_verify(payload)  # type: ignore[arg-type]
                elif event == "error":
                    self._set_busy(False)
                    messagebox.showerror(tr("ui.msg.error_title"), str(payload))
        except queue.Empty:
            pass
        self.root.after(120, self._poll_queue)

    def _update_phase_progress(self, phase: str, done: int, total: int | None, detail: str) -> None:
        phase_label = tr(f"phase.{phase}")
        name = Path(detail).name if detail else ""
        if total:
            self._set_progress_determinate(done, total)
            self.status_var.set(tr("ui.status.phase", phase=phase_label, done=done, total=total, name=name))
        else:
            self._set_progress_indeterminate()
            if phase == "walking":
                self.status_var.set(tr("ui.status.walk", count=done, name=name))
            else:
                self.status_var.set(tr("ui.status.phase_simple", phase=phase_label, name=name or "…"))

    def _set_progress_determinate(self, value: int, maximum: int) -> None:
        if self._progress_mode != "determinate":
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self._progress_mode = "determinate"
        self.progress.configure(maximum=maximum, value=value)

    def _set_progress_indeterminate(self) -> None:
        if self._progress_mode != "indeterminate":
            self.progress.configure(mode="indeterminate")
            self.progress.start(12)
            self._progress_mode = "indeterminate"

    def _finish_scan(self, report: ScanReport) -> None:
        self.items = report.items
        self.item_by_id = {item.item_id: item for item in self.items}
        self.last_report = report
        self._refresh_tree()
        self._set_busy(False)
        message = tr(
            "ui.status.scan_summary",
            files=report.files_seen,
            size=human_size(report.bytes_seen),
            items=len(report.items),
            seconds=f"{report.elapsed_seconds:.1f}",
        )
        if report.cancelled:
            message = tr("ui.status.scan_cancelled") + message
        if report.warnings:
            message += tr("ui.status.warnings_suffix", count=len(report.warnings))
        self.status_var.set(message)
        if report.warnings:
            preview = "\n".join(report.warnings[:12])
            messagebox.showwarning(tr("ui.msg.scan_warnings_title"), f"{message}\n\n{preview}")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.scan_button.configure(state=state)
        self.execute_button.configure(state=state)
        self.verify_button.configure(state=state)
        self.cancel_button.configure(state="normal" if busy else "disabled")
        if busy:
            self._progress_mode = ""
            self._set_progress_indeterminate()
        else:
            self.progress.stop()
            self.progress.configure(mode="indeterminate", value=0)
            self._progress_mode = ""

    # ------------------------------------------------------------------ table

    def _filtered_items(self) -> list[ScanItem]:
        return viewmodel.filter_items(
            self.items,
            query=self.search_var.get(),
            category=self.filter_category,
            action=self.filter_action,
            confidence=self.filter_confidence,
            only_selected=self.only_selected_var.get(),
        )

    def _on_search_changed(self, _event: object) -> None:
        if self._search_job is not None:
            self.root.after_cancel(self._search_job)
        self._search_job = self.root.after(250, self._search_refresh)

    def _search_refresh(self) -> None:
        self._search_job = None
        self._refresh_tree()

    def _on_category_selected(self, _event: object) -> None:
        self.filter_category = self._category_choices[self.category_box.current()]
        self._refresh_tree()

    def _on_action_filter_selected(self, _event: object) -> None:
        self.filter_action = self._action_choices[self.action_filter_box.current()]
        self._refresh_tree()

    def _on_confidence_selected(self, _event: object) -> None:
        self.filter_confidence = self._confidence_choices[self.confidence_box.current()]
        self._refresh_tree()

    def _on_assign_selected(self, _event: object) -> None:
        self.assign_action = self._assign_choices[self.assign_box.current()]

    def _sort_by(self, column: str) -> None:
        if self.sort_column == column:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = column
            self.sort_reverse = False
        for name in viewmodel.SORTABLE_COLUMNS:
            self.tree.heading(name, text=self._heading_text(name))
        self._refresh_tree()

    def _update_category_values(self) -> None:
        counts = viewmodel.category_counts(self.items)
        values = [f"{tr('ui.all_categories')} ({len(self.items)})"]
        for category in Category:
            values.append(f"{category.label} ({counts.get(category, 0)})")
        index = self._category_choices.index(self.filter_category)
        self.category_box.configure(values=values)
        self.category_box.current(index)

    def _refresh_tree(self) -> None:
        if not hasattr(self, "tree"):
            return
        current_selection = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        visible = self._filtered_items()
        if self.sort_column:
            visible = viewmodel.sort_items(visible, self.sort_column, self.sort_reverse)
        for item in visible:
            patient_date = " / ".join(value for value in (item.patient_name or item.patient_id, item.study_date) if value)
            self.tree.insert(
                "",
                "end",
                iid=item.item_id,
                tags=(viewmodel.row_tag(item),),
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

        counts = viewmodel.category_counts(self.items)
        selected = sum(item.selected for item in self.items)
        self.summary_var.set(
            tr(
                "ui.summary_line",
                total=len(self.items),
                ct=counts.get(Category.CT, 0),
                xray=counts.get(Category.XRAY, 0),
                photo=counts.get(Category.PHOTO, 0),
                selected=selected,
            )
        )
        self._update_category_values()

    def _tree_click(self, event: tk.Event) -> None:
        region = self.tree.identify_region(event.x, event.y)
        column = self.tree.identify_column(event.x)
        row = self.tree.identify_row(event.y)
        if region == "cell" and column == "#1" and row:
            item = self.item_by_id[row]
            item.selected = not item.selected
            self._refresh_tree()
            self.tree.selection_set(row)

    def _show_context_menu(self, event: tk.Event) -> None:
        row = self.tree.identify_row(event.y)
        if row:
            if row not in self.tree.selection():
                self.tree.selection_set(row)
            item = self.item_by_id[row]
            state = "normal" if item.metadata.get("series") else "disabled"
            self.context_menu.entryconfigure(self._series_menu_index, state=state)
            try:
                self.context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.context_menu.grab_release()

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

    def _assign_action(self, action: Action) -> None:
        rows = self.tree.selection()
        if not rows:
            messagebox.showinfo(tr("ui.msg.no_selection_title"), tr("ui.msg.no_selection"))
            return
        for row in rows:
            item = self.item_by_id[row]
            item.action = action
            item.selected = action != Action.KEEP
        self._refresh_tree()

    def _assign_action_to_rows(self) -> None:
        self._assign_action(self.assign_action)

    def _select_series(self) -> None:
        rows = self.tree.selection()
        if not rows:
            return
        label = self.item_by_id[rows[0]].metadata.get("series")
        if not label:
            return
        members = viewmodel.series_members(self.items, str(label))
        for member in members:
            member.selected = True
        self._refresh_tree()
        visible = [member.item_id for member in members if self.tree.exists(member.item_id)]
        if visible:
            self.tree.selection_set(visible)
            self.tree.see(visible[0])

    # ---------------------------------------------------------------- details

    def _show_selected_details(self) -> None:
        rows = self.tree.selection()
        if not rows:
            return
        item = self.item_by_id[rows[0]]
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")

        def add_line(text: str) -> None:
            self.detail_text.insert("end", text + "\n")

        add_line(tr("ui.detail.category", value=item.category.label))
        add_line(tr("ui.detail.action", value=item.action.label))
        add_line(tr("ui.detail.confidence", value=tr(f"confidence.{item.confidence}")))
        add_line(tr("ui.detail.reason", value=item.reason))
        add_line(tr("ui.detail.files", value=item.file_count))
        add_line(tr("ui.detail.size", value=human_size(item.total_size)))
        if item.patient_name:
            add_line(tr("ui.detail.patient", value=item.patient_name))
        if item.patient_id:
            add_line(tr("ui.detail.patient_id", value=item.patient_id))
        if item.study_date:
            add_line(tr("ui.detail.study_date", value=item.study_date))
        if item.modality:
            add_line(tr("ui.detail.modality", value=item.modality))
        if item.duplicate_of:
            add_line(tr("ui.detail.duplicate_of", value=item.duplicate_of))
        if item.metadata.get("series"):
            add_line(tr("ui.detail.series", value=item.metadata["series"]))
        if item.metadata.get("patient_context"):
            add_line(tr("ui.detail.patient_context", value=item.metadata["patient_context"]))
        if item.links:
            add_line("")
            add_line(tr("ui.detail.links", count=len(item.links)))
            for index, link in enumerate(item.links[:10]):
                other = self.item_by_id.get(link["item_id"])
                label = other.display_name if other else tr("ui.detail.outside_list")
                line = f"• {label} — {link['relation']}\n"
                if other is not None:
                    tag = f"link{index}"
                    self.detail_text.insert("end", line, (tag,))
                    self.detail_text.tag_configure(tag, foreground=TEAL, underline=True)
                    self.detail_text.tag_bind(tag, "<Button-1>", lambda _event, item_id=link["item_id"]: self._reveal_item(item_id))
                else:
                    self.detail_text.insert("end", line)
            if len(item.links) > 10:
                add_line(tr("ui.detail.links_more", count=len(item.links) - 10))
        add_line("")
        add_line(tr("ui.detail.path"))
        add_line(str(item.primary_path))
        self.detail_text.configure(state="disabled")
        self._show_preview(item)

    def _reveal_item(self, item_id: str) -> None:
        if item_id not in self.item_by_id:
            return
        if not self.tree.exists(item_id):
            self.search_var.set("")
            self.filter_category = None
            self.filter_action = None
            self.filter_confidence = None
            self.only_selected_var.set(False)
            self.action_filter_box.current(0)
            self.confidence_box.current(0)
            self._refresh_tree()
        if self.tree.exists(item_id):
            self.tree.selection_set(item_id)
            self.tree.see(item_id)

    # ---------------------------------------------------------------- preview

    def _show_preview(self, item: ScanItem) -> None:
        self.preview_photo = None
        placeholder = tr("ui.preview.files", category=item.category.label, count=item.file_count)
        if Image is None or ImageTk is None:
            self.preview_label.configure(image="", text=placeholder)
            return
        paths = item.paths or [item.primary_path]
        middle = len(paths) // 2
        path = paths[middle]
        caption = ""
        if len(paths) > 1:
            caption = tr("ui.preview.slice", index=middle + 1, total=len(paths))
        try:
            sniffed = sniff_format(path)
        except OSError:
            sniffed = None
        if sniffed is not None and sniffed.kind == Kind.IMAGE:
            self._preview_raster(path, caption)
            return
        if item.category in DICOM_CATEGORIES and pydicom is not None and numpy is not None:
            self._preview_dicom(path, caption, placeholder)
            return
        self.preview_label.configure(image="", text=placeholder)

    def _preview_raster(self, path: Path, caption: str) -> None:
        try:
            with Image.open(path) as image:
                image.thumbnail((360, 260))
                preview = image.convert("RGB").copy()
            self.preview_photo = ImageTk.PhotoImage(preview)
            self.preview_label.configure(image=self.preview_photo, text=caption)
        except Exception as exc:
            self.preview_label.configure(image="", text=tr("ui.preview.unavailable", error=exc))

    def _preview_dicom(self, path: Path, caption: str, placeholder: str) -> None:
        try:
            dataset = pydicom.dcmread(path)
            pixels = dataset.pixel_array
            if pixels.ndim > 2:
                pixels = pixels[pixels.shape[0] // 2]
            pixels = pixels.astype("float32")
            low = float(pixels.min())
            high = float(pixels.max())
            if high > low:
                pixels = (pixels - low) * (255.0 / (high - low))
            image = Image.fromarray(pixels.astype("uint8"))
            image.thumbnail((360, 260))
            self.preview_photo = ImageTk.PhotoImage(image.convert("RGB"))
            self.preview_label.configure(image=self.preview_photo, text=caption)
        except Exception:
            self.preview_label.configure(image="", text=placeholder)

    def _open_selected_location(self) -> None:
        rows = self.tree.selection()
        if rows:
            try:
                _open_in_file_manager(self.item_by_id[rows[0]].primary_path)
            except Exception as exc:
                messagebox.showerror(tr("ui.msg.open_folder_failed"), str(exc))

    # ---------------------------------------------------------------- exports

    def _export_plan(self) -> None:
        if not self.items:
            messagebox.showinfo(tr("ui.msg.no_data_title"), tr("ui.msg.no_data"))
            return
        filename = filedialog.asksaveasfilename(
            title=tr("ui.msg.save_plan_title"),
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
        messagebox.showinfo(tr("ui.msg.plan_saved_title"), filename)

    def _export_csv(self) -> None:
        if not self.items:
            messagebox.showinfo(tr("ui.msg.no_data_title"), tr("ui.msg.no_data"))
            return
        filename = filedialog.asksaveasfilename(
            title=tr("ui.msg.save_csv_title"),
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile="dental_archive_scan.csv",
        )
        if not filename:
            return
        write_scan_csv(self.items, Path(filename))
        messagebox.showinfo(tr("ui.msg.csv_saved_title"), filename)

    def _show_statistics(self) -> None:
        if not self.items:
            messagebox.showinfo(tr("ui.msg.no_data_title"), tr("ui.msg.no_data"))
            return
        warnings = self.last_report.warnings if self.last_report else []
        stats = build_statistics(self.items, warnings)
        lines = [
            f"{stats.total_items} {tr('report.items')} • {stats.total_files} {tr('report.files')}",
            f"{tr('report.total_size')}: {human_size(stats.total_size)}",
            f"{tr('report.duplicates')}: {stats.duplicate_items} • {tr('report.reclaimable')}: {human_size(stats.reclaimable_bytes)}",
            f"{tr('report.junk_size')}: {human_size(stats.junk_bytes)}",
            "",
            tr("report.by_category"),
        ]
        for category, entry in stats.by_category.items():
            lines.append(f"• {category.label}: {entry.items} / {human_size(entry.size)}")
        if warnings:
            lines.extend(("", tr("report.warnings") + f": {len(warnings)}"))

        dialog = tk.Toplevel(self.root)
        dialog.title(tr("ui.stats.title"))
        dialog.configure(bg=PANEL)
        dialog.transient(self.root)
        text = tk.Text(dialog, width=64, height=22, wrap="word", bg=PANEL, fg=TEXT, relief="flat", font=("Segoe UI", 10))
        text.insert("1.0", "\n".join(lines))
        text.configure(state="disabled")
        text.pack(fill="both", expand=True, padx=16, pady=(16, 8))
        buttons = ttk.Frame(dialog, style="Panel.TFrame")
        buttons.pack(fill="x", padx=16, pady=(0, 16))
        ttk.Button(buttons, text=tr("ui.stats.save_html"), command=self._save_html_report).pack(side="left")
        ttk.Button(buttons, text=tr("ui.run.close"), command=dialog.destroy).pack(side="right")

    def _save_html_report(self) -> None:
        filename = filedialog.asksaveasfilename(
            title=tr("ui.msg.save_report_title"),
            defaultextension=".html",
            filetypes=[("HTML", "*.html")],
            initialfile="dental_archive_report.html",
        )
        if not filename:
            return
        warnings = self.last_report.warnings if self.last_report else []
        write_html_report(self.items, Path(filename), warnings=warnings)
        messagebox.showinfo(tr("ui.msg.report_saved_title"), filename)

    # -------------------------------------------------------------- execution

    def _start_execution(self) -> None:
        selected = [item for item in self.items if item.selected and item.action != Action.KEEP]
        if not selected:
            messagebox.showinfo(tr("ui.msg.empty_plan_title"), tr("ui.msg.empty_plan"))
            return
        destination_text = self.destination_var.get().strip()
        if not destination_text:
            messagebox.showwarning(tr("ui.msg.no_destination_title"), tr("ui.msg.no_destination"))
            return
        destination = Path(destination_text)
        try:
            resolved_destination = destination.expanduser().resolve()
            if any(
                resolved_destination == source.resolve() or resolved_destination.is_relative_to(source.resolve())
                for source in self.sources
            ):
                if not messagebox.askyesno(
                    tr("ui.msg.destination_inside_source_title"),
                    tr("ui.msg.destination_inside_source"),
                ):
                    return
        except OSError:
            pass

        direct_trash = [item for item in selected if item.action == Action.TRASH]
        trash_word = tr("ui.msg.trash_word")
        if direct_trash:
            confirmation = simpledialog.askstring(
                tr("ui.msg.trash_confirm_title"),
                tr("ui.msg.trash_confirm", count=len(direct_trash), word=trash_word),
            )
            if confirmation != trash_word:
                messagebox.showinfo(tr("ui.msg.cancelled_title"), tr("ui.msg.trash_cancelled"))
                return
        elif not messagebox.askyesno(
            tr("ui.msg.execute_title"),
            tr("ui.msg.execute_confirm", count=len(selected)),
        ):
            return

        save_settings({"last_destination": destination_text})
        self._set_busy(True)
        self._set_progress_determinate(0, max(sum(item.file_count for item in selected), 1))
        self.status_var.set(tr("ui.status.executing"))
        plan_snapshot = tuple(self.items)
        source_snapshot = tuple(self.sources)

        def worker() -> None:
            try:
                summary = execute_plan(
                    plan_snapshot,
                    destination,
                    sources=source_snapshot,
                    progress=lambda done, total, path: self.ui_queue.put(("operation_progress", (done, total, path))),
                )
                self.ui_queue.put(("operation_done", summary))
            except Exception as exc:
                self.ui_queue.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_execution(self, summary: RunSummary) -> None:
        self._set_busy(False)
        self.status_var.set(tr("ui.status.done_operations", succeeded=summary.succeeded, failed=summary.failed))
        self._show_run_dialog(summary)

    def _show_run_dialog(self, summary: RunSummary) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title(tr("ui.run.title"))
        dialog.configure(bg=PANEL)
        dialog.transient(self.root)
        body = ttk.Frame(dialog, style="Panel.TFrame", padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=tr("ui.run.succeeded", count=summary.succeeded), style="Panel.TLabel").pack(anchor="w")
        failed_label = ttk.Label(body, text=tr("ui.run.failed", count=summary.failed), style="Panel.TLabel")
        failed_label.pack(anchor="w")
        if summary.failed:
            failed_label.configure(foreground=RED)
        if summary.manifest_path:
            ttk.Label(body, text=tr("ui.run.manifest", path=summary.manifest_path), style="Muted.TLabel", wraplength=520).pack(
                anchor="w", pady=(6, 0)
            )
        buttons = ttk.Frame(body, style="Panel.TFrame")
        buttons.pack(fill="x", pady=(14, 0))
        if summary.manifest_path:
            ttk.Button(
                buttons,
                text=tr("ui.run.open_log"),
                command=lambda: _open_in_file_manager(summary.manifest_path),
            ).pack(side="left")
        destination_text = self.destination_var.get().strip()
        if destination_text:
            ttk.Button(
                buttons,
                text=tr("ui.run.open_destination"),
                command=lambda: _open_in_file_manager(Path(destination_text)),
            ).pack(side="left", padx=(6, 0))
        if summary.failed:
            ttk.Button(
                buttons,
                text=tr("ui.run.show_errors"),
                command=lambda: self._show_run_errors(summary),
            ).pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text=tr("ui.run.close"), command=dialog.destroy).pack(side="right")

    def _show_run_errors(self, summary: RunSummary) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title(tr("ui.run.errors_title"))
        dialog.configure(bg=PANEL)
        dialog.transient(self.root)
        text = tk.Text(dialog, width=90, height=20, wrap="word", bg=PANEL, fg=TEXT, relief="flat", font=("Segoe UI", 9))
        for record in summary.records:
            if record.status == "error":
                text.insert("end", f"• {record.source}\n  {record.message}\n")
        text.configure(state="disabled")
        text.pack(fill="both", expand=True, padx=16, pady=16)

    # ------------------------------------------------------------ verification

    def _start_verify(self) -> None:
        initial = self.destination_var.get().strip()
        selected = filedialog.askdirectory(title=tr("ui.choose_archive_title"), initialdir=initial or None)
        if not selected:
            return
        destination = Path(selected)
        self.cancel_event.clear()
        self._set_busy(True)
        self.status_var.set(tr("ui.verify.running"))

        def worker() -> None:
            try:
                report = verify_archive(
                    destination,
                    cancel_event=self.cancel_event,
                    progress=lambda done, total, path: self.ui_queue.put(("verify_progress", (done, total, path))),
                )
                self.ui_queue.put(("verify_done", report))
            except Exception as exc:
                self.ui_queue.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_verify(self, report: VerifyReport) -> None:
        self._set_busy(False)
        self.status_var.set(tr("ui.verify.title"))
        if not report.manifests:
            messagebox.showwarning(tr("ui.verify.title"), tr("verify.no_manifests"))
            return
        summary = tr(
            "ui.verify.summary",
            total=report.total,
            ok=report.ok,
            mismatch=report.mismatched,
            missing=report.missing,
            unreadable=report.unreadable,
        )
        if report.cancelled:
            summary = tr("ui.status.scan_cancelled") + summary

        dialog = tk.Toplevel(self.root)
        dialog.title(tr("ui.verify.title"))
        dialog.configure(bg=PANEL)
        dialog.transient(self.root)
        body = ttk.Frame(dialog, style="Panel.TFrame", padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=summary, style="Panel.TLabel", justify="left").pack(anchor="w")
        problems = [record for record in report.records if record.status != "ok"]
        if problems:
            text = tk.Text(body, width=90, height=12, wrap="word", bg=PANEL, fg=TEXT, relief="flat", font=("Segoe UI", 9))
            for record in problems[:200]:
                label = tr(f"verify.{record.status}")
                detail = record.destination or record.message
                text.insert("end", f"• [{label}] {detail}\n")
            text.configure(state="disabled")
            text.pack(fill="both", expand=True, pady=(10, 0))
        buttons = ttk.Frame(body, style="Panel.TFrame")
        buttons.pack(fill="x", pady=(14, 0))
        ttk.Button(buttons, text=tr("ui.verify.save"), command=lambda: self._save_verify_report(report)).pack(side="left")
        ttk.Button(buttons, text=tr("ui.run.close"), command=dialog.destroy).pack(side="right")

    def _save_verify_report(self, report: VerifyReport) -> None:
        filename = filedialog.asksaveasfilename(
            title=tr("ui.verify.save"),
            defaultextension=".txt",
            filetypes=[("Text", "*.txt")],
            initialfile="dental_archive_verification.txt",
        )
        if not filename:
            return
        write_verify_report_text(report, Path(filename))
        messagebox.showinfo(tr("ui.verify.saved_title"), filename)


def run() -> None:
    root = tk.Tk()
    DentalArchiveApp(root)
    root.mainloop()
