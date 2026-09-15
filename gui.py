#!/usr/bin/env python3
"""
OCUT (OpenCore Update Tool) - native desktop UI for updating an EFI/OC
folder's kexts, OpenCore.efi, Drivers, theme, and migrating config.plist
across OpenCore versions. Built on PySide6 (Qt) - the one dependency
this project accepts a `pip install` for, per direct request for a
modern, native-looking interface (styled after OpenCore Configurator's
own Kexts Installer dialog) rather than the plain HTML/CSS the browser
version (server.py) used. All the actual logic still lives in core.py,
completely UI-framework-agnostic - this file is purely presentation and
event wiring, same separation server.py already kept.

    python3 gui.py

server.py/static/ are untouched and still work exactly as before for
anyone who prefers running it headless/remote through a browser - this
is an additional, now-default frontend, not a replacement that deletes
the old one.
"""
import os
import sys
import traceback

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
    QFileDialog, QFrame, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QTabWidget,
    QVBoxLayout, QWidget,
)

import core

APP_TITLE = "OCUT — обновление EFI/OC"

STYLE_SHEET = """
QWidget { font-size: 13px; }
QMainWindow, QDialog { background: #f5f5f7; }
QLineEdit, QComboBox {
    padding: 5px 8px; border: 1px solid #d0d0d5; border-radius: 6px; background: white;
}
QPushButton {
    padding: 6px 14px; border-radius: 6px; border: 1px solid #d0d0d5;
    background: #ffffff;
}
QPushButton:hover { background: #eef2ff; border-color: #b8c4f0; }
QPushButton:disabled { color: #aaa; background: #f0f0f0; }
QPushButton#primary { background: #0071e3; color: white; border: none; font-weight: 600; }
QPushButton#primary:hover { background: #0077ed; }
QPushButton#danger { background: #d93025; color: white; border: none; font-weight: 600; }
QPushButton#danger:hover { background: #e6392e; }
QTableWidget {
    background: white; border: 1px solid #e2e2e6; border-radius: 8px;
    gridline-color: #eee; alternate-background-color: #fafafc;
}
QHeaderView::section {
    background: #f0f0f3; padding: 6px; border: none; border-bottom: 1px solid #ddd;
    font-weight: 600;
}
QTabWidget::pane { border: 1px solid #e2e2e6; border-radius: 8px; top: -1px; background: white; }
QTabBar::tab {
    padding: 7px 16px; margin-right: 2px; border-top-left-radius: 6px; border-top-right-radius: 6px;
    background: #ebebef;
}
QTabBar::tab:selected { background: white; font-weight: 600; }
QGroupBox {
    border: 1px solid #e2e2e6; border-radius: 8px; margin-top: 10px; padding-top: 14px;
    font-weight: 600;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
#LogPanel { background: #111318; color: #dcdcdc; border-radius: 8px; padding: 6px; }
.badge { border-radius: 8px; padding: 1px 7px; font-size: 11px; font-weight: 600; }
"""

COLOR_YES = "#15803d"
COLOR_NO = "#b45309"
COLOR_MISSING = "#b91c1c"


def badge_label(text, bg, fg):
    lbl = QLabel(text)
    lbl.setStyleSheet(f"background:{bg}; color:{fg}; border-radius:8px; padding:1px 7px; font-size:11px; font-weight:600;")
    return lbl


def source_badge(source):
    if source == "dortania":
        return badge_label("Dortania", "#ede9fe", "#5b21b6")
    if source == "github":
        return badge_label("GitHub", "#e5e7eb", "#374151")
    return None


def status_label(text, color):
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color:{color};")
    return lbl


# ---------------------------------------------------------------- worker --

class LogSink:
    """Duck-typed stand-in for the plain `log: list` every mutating
    core.py function expects - .append() still works exactly the same,
    but each call also streams the line into the GUI's log panel in
    near-real time via a Qt signal, instead of only being visible once
    the whole background call returns."""

    def __init__(self, emit_fn):
        self._emit = emit_fn
        self.lines = []

    def append(self, line):
        self.lines.append(line)
        self._emit(line)


class Worker(QThread):
    """Runs one core.py call off the GUI thread so the window never
    freezes - scan is local/fast but still routed through here for
    consistency (it can shell out to `nvram` with a 10s worst-case
    timeout), everything else here can hit the network. Pass
    with_log=True for any function whose signature takes a `log`
    parameter - it's supplied as a LogSink bound to this worker's own
    log_line signal, so lines stream in as the call progresses rather
    than only appearing at the end."""
    log_line = Signal(str)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, *args, with_log=False, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.with_log = with_log

    def run(self):
        try:
            kwargs = dict(self.kwargs)
            if self.with_log:
                kwargs["log"] = LogSink(self.log_line.emit)
            result = self.fn(*self.args, **kwargs)
            self.succeeded.emit(result)
        except Exception as e:
            traceback.print_exc()
            self.failed.emit(str(e))


# ------------------------------------------------------------ status cell --

def make_wire_or_toggle_widget(kind, key, item, on_wire, on_toggle):
    """Shared by the Кексты and Drivers tables - `item` is the per-row
    dict (a kext or driver status dict from scan_root()), `key` is which
    field identifies it ("bundle" or "file"). Mirrors the web version's
    kextStatusActionHtml()/driverStatusActionHtml() exactly: a disabled
    "+" wire button when not wired at all (enabled only once the file is
    actually present on disk), an interactive checkbox + status text once
    wired, or a stuck-on "подключён, но файла нет!" if config references
    a bundle that vanished from disk."""
    ident = item[key]
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)

    if not item["wired"]:
        btn = QPushButton("+")
        btn.setFixedWidth(28)
        btn.setEnabled(bool(item.get("present")))
        btn.setToolTip(f"Подключить в {'Kernel->Add' if kind == 'kext' else 'UEFI->Drivers'}")
        btn.clicked.connect(lambda: on_wire(ident))
        lay.addWidget(btn)
        lay.addWidget(status_label("не подключён", COLOR_NO))
        lay.addStretch(1)
        return w

    if kind == "kext" and not item.get("present"):
        cb = QCheckBox()
        cb.setChecked(True)
        cb.setEnabled(False)
        lay.addWidget(cb)
        lay.addWidget(status_label("подключён, но файла нет!", COLOR_MISSING))
        lay.addStretch(1)
        return w

    cb = QCheckBox()
    cb.setChecked(bool(item.get("enabled")))
    cb.toggled.connect(lambda checked: on_toggle(ident, checked))
    lay.addWidget(cb)
    lay.addWidget(status_label("включён" if item.get("enabled") else "выключен",
                                COLOR_YES if item.get("enabled") else COLOR_NO))
    lay.addStretch(1)
    return w


# --------------------------------------------------------- add-kext dialog

class AddKextDialog(QDialog):
    """Modal "+ Добавить" dialog for the Кексты table - styled after
    OpenCore Configurator's own Kexts Installer window (checkbox table +
    Download), split into three tabs matching what the browser version
    already offers: pick from the curated catalog (auto-downloads,
    same as OpenCore Configurator's own Download button), import an
    already-extracted .kext from somewhere on disk, or type an
    owner/repo by hand. All three end by asking the main window to
    re-scan so the table reflects whatever changed."""

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.setWindowTitle("Добавить кекст")
        self.resize(640, 480)

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)

        tabs.addTab(self._build_catalog_tab(), "Из каталога")
        tabs.addTab(self._build_local_tab(), "С диска")
        tabs.addTab(self._build_manual_tab(), "Вручную")

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

    # ---- catalog tab ----

    def _build_catalog_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        self.catalog_filter = QLineEdit()
        self.catalog_filter.setPlaceholderText("Поиск по названию/категории...")
        self.catalog_filter.textChanged.connect(self._render_catalog_table)
        lay.addWidget(self.catalog_filter)

        self.catalog_table = QTableWidget(0, 4)
        self.catalog_table.setHorizontalHeaderLabels(["", "Название", "Категория", "Описание"])
        self.catalog_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.catalog_table.verticalHeader().setVisible(False)
        self.catalog_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        lay.addWidget(self.catalog_table, 1)

        self._catalog_data = core.get_kext_catalog()
        self._render_catalog_table()

        btn = QPushButton("Добавить выбранные")
        btn.setObjectName("primary")
        btn.clicked.connect(self._submit_catalog)
        lay.addWidget(btn)

        hint = QLabel("Список из каталога кекстов OpCore-Simplify — скачивается через Dortania/GitHub, "
                      "как и всё остальное в этом инструменте.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666; font-size:11px;")
        lay.addWidget(hint)
        return w

    def _render_catalog_table(self):
        filt = self.catalog_filter.text().strip().lower()
        rows = [e for e in self._catalog_data
                if not filt or filt in f"{e['name']} {e['category']} {e['description']}".lower()]
        self.catalog_table.setRowCount(len(rows))
        for r, entry in enumerate(rows):
            cb = QCheckBox()
            cb.setProperty("catalog_name", entry["name"])
            cell = QWidget()
            cell_lay = QHBoxLayout(cell)
            cell_lay.setContentsMargins(0, 0, 0, 0)
            cell_lay.setAlignment(Qt.AlignCenter)
            cell_lay.addWidget(cb)
            self.catalog_table.setCellWidget(r, 0, cell)
            self.catalog_table.setItem(r, 1, QTableWidgetItem(entry["name"]))
            self.catalog_table.setItem(r, 2, QTableWidgetItem(entry["category"]))
            self.catalog_table.setItem(r, 3, QTableWidgetItem(entry["description"]))

    def _submit_catalog(self):
        names = []
        for r in range(self.catalog_table.rowCount()):
            cell = self.catalog_table.cellWidget(r, 0)
            cb = cell.findChild(QCheckBox)
            if cb and cb.isChecked():
                names.append(cb.property("catalog_name"))
        if not names:
            self.main_window.log("Отметьте хотя бы один кекст в каталоге.")
            return
        root = self.main_window.root_path()
        if not root:
            self.main_window.log("Укажите путь к EFI/OC - выбор из каталога сразу скачивает кекст в Kexts/.")
            return

        def on_done(res):
            self.main_window.log(f"Добавлено из каталога: {', '.join(res['added']) or '(уже были отслеживаемы)'}")
            self.main_window.rescan()

        self.main_window.run_worker(
            core.add_kexts_from_catalog, names, root, self.main_window.channel(),
            with_log=True, on_success=on_done)
        self.accept()

    # ---- local-disk tab ----

    def _build_local_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        row = QHBoxLayout()
        pick_btn = QPushButton("Выбрать папку с кекстом...")
        pick_btn.clicked.connect(self._pick_local_folder)
        row.addWidget(pick_btn)
        self.local_folder_hint = QLabel("")
        self.local_folder_hint.setStyleSheet("color:#666;")
        row.addWidget(self.local_folder_hint, 1)
        lay.addLayout(row)

        self.local_kext_list = QListWidget()
        lay.addWidget(self.local_kext_list, 1)

        hint = QLabel("Копирует выбранный .kext в Kexts/ этой EFI/OC. Подключить его в конфиг (Kernel→Add) "
                      "можно после этого кнопкой «+» в таблице — так же, как для любого другого уже лежащего, "
                      "но не подключённого кекста.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666; font-size:11px;")
        lay.addWidget(hint)

        self._local_folder = None
        return w

    def _pick_local_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку, где лежит .kext")
        if not folder:
            return
        self._local_folder = folder
        self.local_folder_hint.setText(folder)
        self.local_kext_list.clear()
        try:
            kexts = core.list_kexts_in_folder(folder)
        except Exception as e:
            self.main_window.log(f"Список кекстов в папке: {e}")
            return
        if not kexts:
            self.local_kext_list.addItem(".kext не найден в этой папке.")
            return
        for bundle in kexts:
            item = QListWidgetItem()
            self.local_kext_list.addItem(item)
            row = QWidget()
            row_lay = QHBoxLayout(row)
            row_lay.setContentsMargins(4, 2, 4, 2)
            row_lay.addWidget(QLabel(bundle), 1)
            imp_btn = QPushButton("Импортировать")
            imp_btn.clicked.connect(lambda checked=False, b=bundle: self._import_local_kext(b))
            row_lay.addWidget(imp_btn)
            item.setSizeHint(row.sizeHint())
            self.local_kext_list.setItemWidget(item, row)

    def _import_local_kext(self, bundle):
        root = self.main_window.root_path()
        if not root:
            self.main_window.log("Укажите путь к EFI/OC перед импортом.")
            return
        try:
            core.import_kext_from_folder(root, self._local_folder, bundle)
            self.main_window.log(f"{bundle}: скопирован в Kexts/. Подключите его в конфиг кнопкой «+» в таблице.")
            self.main_window.rescan()
            self.accept()
        except Exception as e:
            self.main_window.log(f"{bundle}: ошибка импорта - {e}")

    # ---- manual tab ----

    def _build_manual_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        self.manual_repo = QLineEdit()
        self.manual_repo.setPlaceholderText("owner/repo (например acidanthera/AppleALC)")
        lay.addWidget(QLabel("Репозиторий:"))
        lay.addWidget(self.manual_repo)

        self.manual_kexts = QLineEdit()
        self.manual_kexts.setPlaceholderText("файлы .kext через запятую")
        lay.addWidget(QLabel("Кексты:"))
        lay.addWidget(self.manual_kexts)

        btn = QPushButton("Добавить")
        btn.setObjectName("primary")
        btn.clicked.connect(self._submit_manual)
        lay.addWidget(btn)

        hint = QLabel("Название компонента берётся из репозитория автоматически.")
        hint.setStyleSheet("color:#666; font-size:11px;")
        lay.addWidget(hint)
        lay.addStretch(1)
        return w

    def _submit_manual(self):
        repo = self.manual_repo.text().strip()
        kexts = [s.strip() for s in self.manual_kexts.text().split(",") if s.strip()]
        if not repo or not kexts:
            self.main_window.log("Заполните репозиторий и хотя бы один .kext.")
            return
        try:
            core.add_component(repo, kexts)
            self.main_window.log(f"Добавлен компонент из {repo}.")
            self.main_window.rescan()
            self.accept()
        except Exception as e:
            self.main_window.log(f"Добавить компонент: {e}")


class AddDriverDialog(QDialog):
    """"+ Добавить" for the Drivers table - much narrower than kexts (no
    catalog/local-disk equivalent makes sense here, every driver comes
    from the same OpenCorePkg build), just the one existing flow: name a
    stock driver and pull it out of the current build."""

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.setWindowTitle("Добавить драйвер")
        self.resize(420, 160)

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Имя файла (например OpenHfsPlus.efi):"))
        self.name_edit = QLineEdit()
        lay.addWidget(self.name_edit)

        hint = QLabel("Скачивает этот файл из текущей (Dortania/GitHub, канал выбран в главном окне) сборки "
                      "OpenCorePkg, даже если его раньше не было в Drivers/, и сразу подключает в UEFI→Drivers.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666; font-size:11px;")
        lay.addWidget(hint)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        row.addWidget(cancel_btn)
        submit_btn = QPushButton("Скачать и подключить")
        submit_btn.setObjectName("primary")
        submit_btn.clicked.connect(self._submit)
        row.addWidget(submit_btn)
        lay.addLayout(row)

    def _submit(self):
        filename = self.name_edit.text().strip()
        if not filename:
            self.main_window.log("Укажите имя файла драйвера.")
            return
        root = self.main_window.root_path()
        if not root:
            self.main_window.log("Укажите путь к EFI/OC.")
            return

        def on_done(result):
            self.main_window.log(f"{filename}: скачан ({result['version']}, {result['source']})")
            try:
                core.add_driver_to_config(root, filename)
                self.main_window.log(f"{filename}: добавлен в UEFI->Drivers")
            except Exception as e:
                self.main_window.log(f"{filename}: ошибка подключения - {e}")
            self.main_window.rescan()

        self.main_window.run_worker(
            core.fetch_driver_from_opencore, root, filename, self.main_window.channel(),
            with_log=True, on_success=on_done)
        self.accept()


# --------------------------------------------------------------- main win --

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1080, 780)

        self.last_scan = None
        self._workers = []  # keep references alive while running
        self._bulk_delete_armed = {"components": False, "drivers": False}

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)

        root_layout.addLayout(self._build_top_bar())

        self.tabs = QTabWidget()
        root_layout.addWidget(self.tabs, 1)
        self.tabs.addTab(self._build_kexts_tab(), "Кексты")
        self.tabs.addTab(self._build_drivers_tab(), "Drivers")
        self.tabs.addTab(self._build_opencore_tab(), "OpenCore")
        self.tabs.addTab(self._build_theme_tab(), "Тема")
        self.tabs.addTab(self._build_migration_tab(), "Миграция")

        self.log_panel = QPlainTextEdit()
        self.log_panel.setObjectName("LogPanel")
        self.log_panel.setReadOnly(True)
        self.log_panel.setFixedHeight(160)
        self.log_panel.setFont(QFont("Menlo, Monaco, monospace"))
        root_layout.addWidget(self.log_panel)

    # ---------------------------------------------------------- top bar --

    def _build_top_bar(self):
        row = QHBoxLayout()
        row.addWidget(QLabel("EFI/OC:"))
        self.root_edit = QLineEdit()
        self.root_edit.setPlaceholderText("/Volumes/FAT32-16GB/EFI/OC")
        row.addWidget(self.root_edit, 1)

        pick_btn = QPushButton("Выбрать папку...")
        pick_btn.clicked.connect(self._pick_root_folder)
        row.addWidget(pick_btn)

        self.channel_combo = QComboBox()
        self.channel_combo.addItems(["stable", "prerelease"])
        row.addWidget(self.channel_combo)

        scan_btn = QPushButton("Сканировать")
        scan_btn.clicked.connect(self.rescan)
        row.addWidget(scan_btn)

        check_btn = QPushButton("Проверить обновления")
        check_btn.setObjectName("primary")
        check_btn.clicked.connect(self.check_updates)
        row.addWidget(check_btn)
        return row

    def _pick_root_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку EFI/OC")
        if folder:
            self.root_edit.setText(folder)

    def root_path(self):
        return self.root_edit.text().strip()

    def channel(self):
        return self.channel_combo.currentText()

    def log(self, text):
        self.log_panel.appendPlainText(text)

    def clear_log(self):
        self.log_panel.clear()

    # ------------------------------------------------------- worker glue --

    def run_worker(self, fn, *args, with_log=False, on_success=None, on_error=None, **kwargs):
        worker = Worker(fn, *args, with_log=with_log, **kwargs)
        worker.log_line.connect(self.log)

        def cleanup():
            # Connected to QThread's own `finished` (emitted once run()
            # has actually returned control), not fired from inside
            # handle_success/handle_error - dropping the last Python
            # reference to `worker` before the OS thread has fully wound
            # down is exactly what triggers Qt's noisy (and, if it ever
            # raced badly, unsafe) "QThread: Destroyed while thread is
            # still running" warning.
            if worker in self._workers:
                self._workers.remove(worker)

        def handle_success(result):
            if on_success:
                on_success(result)

        def handle_error(message):
            self.log(f"Ошибка: {message}")
            if on_error:
                on_error(message)

        worker.succeeded.connect(handle_success)
        worker.failed.connect(handle_error)
        worker.finished.connect(cleanup)
        self._workers.append(worker)
        worker.start()

    # ------------------------------------------------------------- scan --

    def rescan(self):
        self.clear_log()
        root = self.root_path()
        if not root:
            self.log("Укажите путь к EFI/OC.")
            return

        def on_done(data):
            self.last_scan = data
            self.render_scan(data)
            self.log("Скан завершён (без обращения к сети).")

        self.run_worker(core.scan_root, root, on_success=on_done)

    def check_updates(self):
        self.clear_log()
        root = self.root_path()
        if not root:
            self.log("Укажите путь к EFI/OC.")
            return
        self.log(f"Проверяю GitHub ({self.channel()})...")

        def on_done(data):
            self.last_scan = data
            self.render_scan(data)
            self.log("Готово.")

        self.run_worker(core.check_updates, root, self.channel(), on_success=on_done)

    # ------------------------------------------------------ Кексты tab --

    def _build_kexts_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        self.kexts_table = QTableWidget(0, 5)
        self.kexts_table.setHorizontalHeaderLabels(["", "Компонент", "Текущая версия", "Доступная", "Статус"])
        self.kexts_table.verticalHeader().setVisible(False)
        self.kexts_table.setAlternatingRowColors(True)
        self.kexts_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.kexts_table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        lay.addWidget(self.kexts_table, 1)

        btn_row = QHBoxLayout()
        select_all_btn = QPushButton("Выделить всё")
        select_all_btn.clicked.connect(lambda: self._select_all(self.kexts_table))
        btn_row.addWidget(select_all_btn)

        add_btn = QPushButton("+ Добавить")
        add_btn.clicked.connect(lambda: AddKextDialog(self).exec())
        btn_row.addWidget(add_btn)

        update_btn = QPushButton("Обновить")
        update_btn.clicked.connect(self.update_all_components)
        btn_row.addWidget(update_btn)

        btn_row.addStretch(1)

        self.kexts_delete_btn = QPushButton("Удалить")
        self.kexts_delete_btn.setObjectName("danger")
        self.kexts_delete_btn.clicked.connect(lambda: self._start_bulk_delete("components"))
        btn_row.addWidget(self.kexts_delete_btn)

        self.kexts_confirm_btn = QPushButton("Подтвердить удаление")
        self.kexts_confirm_btn.setObjectName("danger")
        self.kexts_confirm_btn.hide()
        self.kexts_confirm_btn.clicked.connect(lambda: self._confirm_bulk_delete("components"))
        btn_row.addWidget(self.kexts_confirm_btn)

        self.kexts_cancel_btn = QPushButton("Отмена")
        self.kexts_cancel_btn.hide()
        self.kexts_cancel_btn.clicked.connect(lambda: self._cancel_bulk_delete("components"))
        btn_row.addWidget(self.kexts_cancel_btn)

        lay.addLayout(btn_row)
        return w

    # ------------------------------------------------------ Drivers tab --

    def _build_drivers_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        hint = QLabel("Все драйверы идут одной сборкой OpenCorePkg (нет отдельной версии на файл) — "
                      "«обновить» перекачивает Drivers/*.efi целиком, как и в блоке OpenCore.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666; font-size:11px;")
        lay.addWidget(hint)

        self.drivers_table = QTableWidget(0, 5)
        self.drivers_table.setHorizontalHeaderLabels(
            ["", "Файл", "Последняя применённая версия", "Изменился с тех пор?", "Статус"])
        self.drivers_table.verticalHeader().setVisible(False)
        self.drivers_table.setAlternatingRowColors(True)
        self.drivers_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.drivers_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        lay.addWidget(self.drivers_table, 1)

        btn_row = QHBoxLayout()
        select_all_btn = QPushButton("Выделить всё")
        select_all_btn.clicked.connect(lambda: self._select_all(self.drivers_table))
        btn_row.addWidget(select_all_btn)

        add_btn = QPushButton("+ Добавить из текущей сборки")
        add_btn.clicked.connect(lambda: AddDriverDialog(self).exec())
        btn_row.addWidget(add_btn)

        update_btn = QPushButton("Обновить Drivers/*.efi")
        update_btn.clicked.connect(self.update_drivers)
        btn_row.addWidget(update_btn)

        btn_row.addStretch(1)

        self.drivers_delete_btn = QPushButton("Удалить")
        self.drivers_delete_btn.setObjectName("danger")
        self.drivers_delete_btn.clicked.connect(lambda: self._start_bulk_delete("drivers"))
        btn_row.addWidget(self.drivers_delete_btn)

        self.drivers_confirm_btn = QPushButton("Подтвердить удаление")
        self.drivers_confirm_btn.setObjectName("danger")
        self.drivers_confirm_btn.hide()
        self.drivers_confirm_btn.clicked.connect(lambda: self._confirm_bulk_delete("drivers"))
        btn_row.addWidget(self.drivers_confirm_btn)

        self.drivers_cancel_btn = QPushButton("Отмена")
        self.drivers_cancel_btn.hide()
        self.drivers_cancel_btn.clicked.connect(lambda: self._cancel_bulk_delete("drivers"))
        btn_row.addWidget(self.drivers_cancel_btn)

        lay.addLayout(btn_row)
        return w

    # ------------------------------------------------------ OpenCore tab --

    def _build_opencore_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        box = QGroupBox("OpenCorePkg")
        box_lay = QVBoxLayout(box)

        compare_row = QHBoxLayout()
        self.oc_current_label = QLabel("—")
        self.oc_current_label.setStyleSheet("font-size:20px; font-weight:600;")
        current_box = self._version_box("Текущая", self.oc_current_label)
        compare_row.addWidget(current_box)
        compare_row.addWidget(QLabel("→"))
        self.oc_latest_label = QLabel("—")
        self.oc_latest_label.setOpenExternalLinks(True)
        self.oc_latest_label.setStyleSheet("font-size:20px; font-weight:600;")
        latest_box = self._version_box("Доступная", self.oc_latest_label)
        compare_row.addWidget(latest_box)
        compare_row.addStretch(1)
        box_lay.addLayout(compare_row)

        self.oc_info_label = QLabel("")
        self.oc_info_label.setWordWrap(True)
        self.oc_info_label.setStyleSheet("color:#666; font-size:11px;")
        box_lay.addWidget(self.oc_info_label)

        parts_row = QHBoxLayout()
        self.oc_part_efi = QCheckBox("OpenCore.efi")
        self.oc_part_efi.setChecked(True)
        self.oc_part_drivers = QCheckBox("Drivers/*.efi")
        self.oc_part_drivers.setChecked(True)
        self.oc_part_resources = QCheckBox("Resources/ (тема, из этого же релиза)")
        parts_row.addWidget(self.oc_part_efi)
        parts_row.addWidget(self.oc_part_drivers)
        parts_row.addWidget(self.oc_part_resources)
        parts_row.addStretch(1)
        box_lay.addLayout(parts_row)

        apply_btn = QPushButton("Обновить выбранное")
        apply_btn.setObjectName("primary")
        apply_btn.clicked.connect(self.update_opencore)
        box_lay.addWidget(apply_btn, alignment=Qt.AlignLeft)

        lay.addWidget(box)
        lay.addStretch(1)
        return w

    def _version_box(self, label_text, value_label):
        box = QFrame()
        box.setStyleSheet("QFrame { border: 1px solid #ddd; border-radius: 8px; background: #fafafc; }")
        v = QVBoxLayout(box)
        lbl = QLabel(label_text.upper())
        lbl.setStyleSheet("color:#888; font-size:10px; font-weight:600;")
        v.addWidget(lbl)
        v.addWidget(value_label)
        return box

    # ---------------------------------------------------------- Тема tab --

    def _build_theme_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        lay.addWidget(QLabel("Репозиторий темы:"))
        self.theme_repo = QLineEdit()
        self.theme_repo.setPlaceholderText("owner/repo, напр. acidanthera/OcBinaryData")
        lay.addWidget(self.theme_repo)

        lay.addWidget(QLabel("Ветка/тег (необязательно):"))
        self.theme_ref = QLineEdit()
        lay.addWidget(self.theme_ref)

        apply_btn = QPushButton("Скачать и применить в Resources/")
        apply_btn.setObjectName("primary")
        apply_btn.clicked.connect(self.apply_theme)
        lay.addWidget(apply_btn, alignment=Qt.AlignLeft)

        hint = QLabel("Официальная тема — acidanthera/OcBinaryData. Любой другой репозиторий с папкой "
                      "Resources/ (Image/Label/Font в нужной структуре) тоже подойдёт — на свой риск, "
                      "он не проверяется.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666; font-size:11px;")
        lay.addWidget(hint)
        lay.addStretch(1)
        return w

    # ------------------------------------------------------ Миграция tab --

    def _build_migration_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        hint = QLabel("Берёт текущий config.plist + Docs/Sample.plist из выбранного канала/релиза OpenCorePkg, "
                      "переносит значения туда, где путь ключа и его тип совпадают. Результат сохраняется в "
                      "отдельный файл, отчёт показывает, что перенеслось, что осталось дефолтным, что "
                      "несовместимо по типу и что убрали из новой схемы.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666; font-size:11px;")
        lay.addWidget(hint)

        btn_row = QHBoxLayout()
        preview_btn = QPushButton("Показать отчёт (ничего не пишет на диск)")
        preview_btn.clicked.connect(self.preview_migration)
        btn_row.addWidget(preview_btn)
        save_btn = QPushButton("Сохранить как config.migrated.plist")
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(self.save_migration)
        btn_row.addWidget(save_btn)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        self.migration_report = QPlainTextEdit()
        self.migration_report.setReadOnly(True)
        self.migration_report.setFont(QFont("Menlo, Monaco, monospace"))
        lay.addWidget(self.migration_report, 1)
        return w

    # --------------------------------------------------------- rendering --

    def render_scan(self, data):
        self._render_kexts_table(data)
        self._render_drivers_table(data)
        self._render_opencore(data)
        self._cancel_bulk_delete("components")
        self._cancel_bulk_delete("drivers")

    def _render_kexts_table(self, data):
        table = self.kexts_table
        table.setRowCount(0)

        def add_row(display_name, bundle_hint, k, badge=None):
            row = table.rowCount()
            table.insertRow(row)

            sel_cell = QWidget()
            sel_lay = QHBoxLayout(sel_cell)
            sel_lay.setContentsMargins(0, 0, 0, 0)
            sel_lay.setAlignment(Qt.AlignCenter)
            sel_cb = QCheckBox()
            sel_cb.setProperty("bundle", k["bundle"])
            sel_lay.addWidget(sel_cb)
            table.setCellWidget(row, 0, sel_cell)

            name_cell = QWidget()
            name_lay = QHBoxLayout(name_cell)
            name_lay.setContentsMargins(4, 2, 4, 2)
            name_text = QLabel(f"<b>{display_name}</b><br><span style='color:#888;font-size:11px;'>{bundle_hint}</span>")
            name_lay.addWidget(name_text)
            if badge:
                name_lay.addWidget(badge)
            name_lay.addStretch(1)
            table.setCellWidget(row, 1, name_cell)

            local_ver = k.get("local_version") or ("?" if k.get("present") else "—")
            table.setItem(row, 2, QTableWidgetItem(local_ver))
            return row

        for c in data["components"]:
            latest_cell = QWidget()
            latest_lay = QHBoxLayout(latest_cell)
            latest_lay.setContentsMargins(4, 2, 4, 2)
            latest_text = c.get("latest_version") or ("ошибка" if c.get("error") else "?")
            latest_lbl = QLabel(latest_text)
            if c.get("release_url"):
                latest_lbl.setText(f"<a href='{c['release_url']}'>{latest_text}</a>")
                latest_lbl.setOpenExternalLinks(True)
            latest_lay.addWidget(latest_lbl)
            sb = source_badge(c.get("source"))
            if sb:
                latest_lay.addWidget(sb)
            latest_lay.addStretch(1)

            for k in c["kexts"]:
                row = add_row(c["name"], k["bundle"], k)
                # clone the latest-version cell widget per row (Qt widgets
                # can't be shared across cells) - cheap enough at this size
                cell = QWidget()
                cell_lay = QHBoxLayout(cell)
                cell_lay.setContentsMargins(4, 2, 4, 2)
                lbl = QLabel(latest_lbl.text())
                lbl.setOpenExternalLinks(True)
                cell_lay.addWidget(lbl)
                sb2 = source_badge(c.get("source"))
                if sb2:
                    cell_lay.addWidget(sb2)
                cell_lay.addStretch(1)
                table.setCellWidget(row, 3, cell)
                table.setCellWidget(row, 4, make_wire_or_toggle_widget(
                    "kext", "bundle", k, self.wire_kext, self.toggle_kext))

        for k in data.get("other_kexts_present", []):
            row = add_row(k["bundle"], "", k, badge_label("на диске", "#fef3c7", "#92400e"))
            table.setItem(row, 3, QTableWidgetItem("—"))
            table.setCellWidget(row, 4, make_wire_or_toggle_widget(
                "kext", "bundle", k, self.wire_kext, self.toggle_kext))

        for k in data.get("manual_only_kexts_present", []):
            row = add_row(k["bundle"], "", k, badge_label("на диске, ручной", "#fef3c7", "#92400e"))
            table.setItem(row, 3, QTableWidgetItem("—"))
            table.setCellWidget(row, 4, make_wire_or_toggle_widget(
                "kext", "bundle", k, self.wire_kext, self.toggle_kext))

    def _render_drivers_table(self, data):
        table = self.drivers_table
        table.setRowCount(0)
        for d in data.get("drivers", []):
            row = table.rowCount()
            table.insertRow(row)

            sel_cell = QWidget()
            sel_lay = QHBoxLayout(sel_cell)
            sel_lay.setContentsMargins(0, 0, 0, 0)
            sel_lay.setAlignment(Qt.AlignCenter)
            sel_cb = QCheckBox()
            sel_cb.setProperty("file", d["file"])
            sel_lay.addWidget(sel_cb)
            table.setCellWidget(row, 0, sel_cell)

            table.setItem(row, 1, QTableWidgetItem(d["file"]))
            table.setItem(row, 2, QTableWidgetItem(d.get("last_known_version") or "—"))
            table.setItem(row, 3, QTableWidgetItem("да" if d.get("changed_since_last_update") else "нет"))
            table.setCellWidget(row, 4, make_wire_or_toggle_widget(
                "driver", "file", d, self.wire_driver, self.toggle_driver))

    def _render_opencore(self, data):
        oc = data["opencore"]
        self.oc_current_label.setText(
            oc.get("live_booted_version") or oc.get("last_known_version") or ("?" if oc.get("present") else "нет файла"))

        latest_text = oc.get("latest_version") or ("ошибка" if oc.get("error") else "?")
        if oc.get("release_url"):
            self.oc_latest_label.setText(f"<a href='{oc['release_url']}'>{latest_text}</a>")
        else:
            self.oc_latest_label.setText(latest_text)

        if not oc.get("present"):
            self.oc_info_label.setText("OpenCore.efi не найден по этому пути.")
            return

        lines = []
        if data.get("dortania_error"):
            lines.append(f"Dortania build-repo недоступен ({data['dortania_error']}) - используется официальный "
                          f"GitHub-релиз как запасной вариант.")
        if oc.get("live_booted_version"):
            lines.append("Версия взята из NVRAM текущей загруженной системы - совпадает с файлом по этому пути, "
                          "только если вы сейчас загружены именно с него.")
        else:
            lines.append("NVRAM-версия недоступна (не macOS, или ExposeSensitiveData без бита 0x02) - показана "
                          "версия, которую последний раз применил сам OCUT.")
        if oc.get("last_known_version") and oc.get("changed_since_last_update"):
            lines.append("Файл изменился с последнего known-апдейта (обновили чем-то другим или вручную).")
        if oc.get("error"):
            lines.append(oc["error"])
        self.oc_info_label.setText("\n".join(lines))

    # -------------------------------------------------------- selection --

    def _select_all(self, table):
        boxes = [table.cellWidget(r, 0).findChild(QCheckBox) for r in range(table.rowCount())]
        boxes = [b for b in boxes if b]
        if not boxes:
            return
        all_checked = all(b.isChecked() for b in boxes)
        for b in boxes:
            b.setChecked(not all_checked)

    def _selected_values(self, table, prop_name):
        values = []
        for r in range(table.rowCount()):
            cell = table.cellWidget(r, 0)
            cb = cell.findChild(QCheckBox) if cell else None
            if cb and cb.isChecked():
                values.append(cb.property(prop_name))
        return values

    def _start_bulk_delete(self, kind):
        table = self.kexts_table if kind == "components" else self.drivers_table
        prop = "bundle" if kind == "components" else "file"
        if not self._selected_values(table, prop):
            self.log("Сначала отметьте хотя бы одну строку чекбоксом.")
            return
        delete_btn, confirm_btn, cancel_btn = self._bulk_buttons(kind)
        delete_btn.hide()
        confirm_btn.show()
        cancel_btn.show()

    def _cancel_bulk_delete(self, kind):
        delete_btn, confirm_btn, cancel_btn = self._bulk_buttons(kind)
        delete_btn.show()
        confirm_btn.hide()
        cancel_btn.hide()

    def _bulk_buttons(self, kind):
        if kind == "components":
            return self.kexts_delete_btn, self.kexts_confirm_btn, self.kexts_cancel_btn
        return self.drivers_delete_btn, self.drivers_confirm_btn, self.drivers_cancel_btn

    def _confirm_bulk_delete(self, kind):
        root = self.root_path()
        if kind == "components":
            values = self._selected_values(self.kexts_table, "bundle")
            self._cancel_bulk_delete(kind)
            if not values or not root:
                return

            def on_done(res):
                msg = f"Убрано из Kernel->Add: {', '.join(res['removed']) or '(ничего)'} (сами файлы остались в Kexts/)"
                if res["skipped"]:
                    msg += f"; уже не были подключены: {', '.join(res['skipped'])}"
                self.log(msg)
                self.rescan()

            self.run_worker(core.remove_kexts_from_config_bulk, root, values, on_success=on_done)
        else:
            values = self._selected_values(self.drivers_table, "file")
            self._cancel_bulk_delete(kind)
            if not values or not root:
                return

            def on_done(res):
                msg = f"Убрано из UEFI->Drivers: {', '.join(res['removed']) or '(ничего)'} (сами файлы остались в Drivers/)"
                if res["skipped"]:
                    msg += f"; уже не были подключены: {', '.join(res['skipped'])}"
                self.log(msg)
                self.rescan()

            self.run_worker(core.remove_drivers_from_config_bulk, root, values, on_success=on_done)

    # ------------------------------------------------------------ kexts --

    def wire_kext(self, bundle):
        root = self.root_path()
        try:
            core.add_kext_to_config(root, bundle)
            self.log(f"{bundle}: добавлен в Kernel->Add")
        except Exception as e:
            self.log(f"{bundle}: ошибка - {e}")
        self.rescan()

    def toggle_kext(self, bundle, enabled):
        root = self.root_path()
        try:
            core.set_kext_enabled(root, bundle, enabled)
            self.log(f"{bundle}: {'включён' if enabled else 'выключен'}")
        except Exception as e:
            self.log(f"{bundle}: ошибка - {e}")
        self.rescan()

    def update_all_components(self):
        if not self.last_scan:
            self.log("Сначала сканируйте.")
            return
        names = [c["name"] for c in self.last_scan["components"]]
        if QMessageBox.question(self, "Обновить всё", f"Обновить все отслеживаемые кексты ({len(names)})?") != QMessageBox.Yes:
            return
        root = self.root_path()
        channel = self.channel()

        def update_next(remaining):
            if not remaining:
                self.rescan()
                return
            name, rest = remaining[0], remaining[1:]
            self.log(f"Обновляю {name}...")

            def on_done(_result):
                update_next(rest)

            def on_error(_message):
                update_next(rest)

            self.run_worker(core.apply_kext_component, name, root, channel,
                             with_log=True, on_success=on_done, on_error=on_error)

        update_next(names)

    # ---------------------------------------------------------- drivers --

    def wire_driver(self, filename):
        root = self.root_path()
        try:
            core.add_driver_to_config(root, filename)
            self.log(f"{filename}: добавлен в UEFI->Drivers")
        except Exception as e:
            self.log(f"{filename}: ошибка - {e}")
        self.rescan()

    def toggle_driver(self, filename, enabled):
        root = self.root_path()
        try:
            core.set_driver_enabled(root, filename, enabled)
            self.log(f"{filename}: {'включён' if enabled else 'выключен'}")
        except Exception as e:
            self.log(f"{filename}: ошибка - {e}")
        self.rescan()

    def update_drivers(self):
        self.update_opencore(parts_override=["drivers"])

    # --------------------------------------------------------- opencore --

    def update_opencore(self, parts_override=None):
        parts = parts_override
        if parts is None:
            parts = []
            if self.oc_part_efi.isChecked():
                parts.append("efi")
            if self.oc_part_drivers.isChecked():
                parts.append("drivers")
            if self.oc_part_resources.isChecked():
                parts.append("resources")
        if not parts:
            self.log("Ничего не выбрано.")
            return
        if QMessageBox.question(self, "Обновить OpenCorePkg",
                                 f"Применить к OpenCorePkg ({', '.join(parts)})? "
                                 f"Это затрагивает загрузчик напрямую.") != QMessageBox.Yes:
            return
        root = self.root_path()
        channel = self.channel()

        def on_done(_result):
            self.rescan()

        self.run_worker(core.apply_opencore, root, channel, parts, with_log=True, on_success=on_done)

    # ------------------------------------------------------------- тема --

    def apply_theme(self):
        repo = self.theme_repo.text().strip()
        ref = self.theme_ref.text().strip() or None
        if not repo:
            self.log("Укажите репозиторий темы.")
            return
        if QMessageBox.question(self, "Применить тему",
                                 f"Заменить Resources/ содержимым из {repo}?") != QMessageBox.Yes:
            return
        root = self.root_path()
        self.run_worker(core.apply_theme, repo, root, with_log=True, ref=ref)

    # -------------------------------------------------------- migration --

    def preview_migration(self):
        root = self.root_path()
        if not root:
            self.log("Укажите путь к EFI/OC.")
            return

        def on_done(result):
            merged, report = result
            self._render_migration_report(report)

        self.run_worker(core.fetch_new_sample_and_migrate, root, self.channel(), on_success=on_done)

    def save_migration(self):
        root = self.root_path()
        if not root:
            self.log("Укажите путь к EFI/OC.")
            return
        if QMessageBox.question(self, "Сохранить миграцию",
                                 "Сохранить результат как config.migrated.plist рядом с текущим config.plist? "
                                 "Текущий config.plist не будет тронут.") != QMessageBox.Yes:
            return

        def on_done(result):
            merged, report = result
            import plistlib
            out_path = os.path.join(root, "config.migrated.plist")
            with open(out_path, "wb") as f:
                plistlib.dump(merged, f)
            self._render_migration_report(report)
            self.log(f"Сохранено: {out_path}")

        self.run_worker(core.fetch_new_sample_and_migrate, root, self.channel(), on_success=on_done)

    def _render_migration_report(self, report):
        lines = [f"Целевая версия OpenCore: {report['target_version']} ({report['channel']})", ""]
        lines.append(f"=== Несовместимость типов ({len(report['type_mismatch'])}) — "
                      f"использован новый дефолт, проверьте руками ===")
        for t in report["type_mismatch"]:
            lines.append(f"  {t['path']}: было {t['old_type']}, стало {t['new_type']}")
        lines.append("")
        lines.append(f"=== Убрано из новой схемы ({len(report['removed_in_new'])}) ===")
        lines.extend(f"  {p}" for p in report["removed_in_new"])
        lines.append("")
        lines.append(f"=== Новые ключи, оставлены по дефолту новой схемы ({len(report['kept_new_default'])}) ===")
        lines.extend(f"  {p}" for p in report["kept_new_default"])
        self.migration_report.setPlainText("\n".join(lines))


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE_SHEET)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
