"""The Cruises page: the list of cruises, each with its own log. The selected
cruise is the one dives, transects and configurations are logged in."""

import sqlite3
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from ..db import LogExistsError, OldLogError
from ..lookups import platform_label
from .forms import CruiseForm
from .pages import _fill, _table, _title

# Errors that opening, creating or moving a log can raise
LOG_ERRORS = (OSError, sqlite3.Error, OldLogError, LogExistsError)


class CruisesPage(QWidget):
    COLUMNS = ['', 'Name', 'Leg', 'Start', 'End', 'Ship', 'Log file']

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.entries = []

        intro = QLabel('Select the cruise to log. Configurations, dives and transects are saved in the '
                       "selected cruise's log file.")
        intro.setWordWrap(True)
        buttons = QHBoxLayout()
        for label, slot in [('New cruise...', self.new), ('Open log file...', self.open_log), ('Select', self.select),
                            ('Edit...', self.edit), ('Remove from list', self.remove)]:
            button = QPushButton(label)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch()
        self.table = _table()
        self.table.doubleClicked.connect(self.select)

        layout = QVBoxLayout(self)
        layout.addWidget(_title('Cruises'))
        layout.addWidget(intro)
        layout.addLayout(buttons)
        layout.addWidget(self.table)
        store.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        self.entries = list(self.store.settings.cruises)
        ships = {p['id']: platform_label(p) for p in self.store.lookups.platforms()}
        rows = []
        for e in self.entries:
            cruise = self.store.details(e)
            if cruise is None:
                rows.append(['', e['name'], e['leg'], '', '', '', f"{e['log']} (not found)"])
            else:
                ship = cruise.get('ship_id')
                rows.append(['●' if e['id'] == self.store.cruise_id else '', cruise['name'], cruise['leg'],
                             cruise.get('start_date'), cruise.get('end_date'),
                             ships.get(ship, f'ID {ship}' if ship else ''), e['log']])
        _fill(self.table, self.COLUMNS, rows)
        # The current cruise in bold
        for r, e in enumerate(self.entries):
            if e['id'] == self.store.cruise_id:
                for c in range(self.table.columnCount()):
                    item = self.table.item(r, c)
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
        self.table.resizeColumnsToContents()

    def selected(self):
        index = self.table.currentRow() if self.table.selectionModel().hasSelection() else -1
        if index < 0:
            QMessageBox.information(self, 'Select a cruise', 'Please select a cruise in the list.')
            return None
        return self.entries[index]

    def new(self):
        form = CruiseForm(self.store, parent=self)
        try:
            if form.exec():
                try:
                    self.store.create_cruise(form.values(), form.log_path())
                except LOG_ERRORS as e:
                    QMessageBox.warning(self, 'New cruise', f'The cruise log could not be created.\n\n{e}')
        finally:
            form.deleteLater()

    def open_log(self):
        """Add a log made elsewhere (another computer, the Shiny version) to the list, and select it."""
        path, _ = QFileDialog.getOpenFileName(self, 'Open log file', str(self.store.settings.logs_path),
                                              'Cruise logs (*.sqlite);;All files (*)')
        if not path:
            return
        try:
            self.store.open_cruise(self.store.add_log(path))
        except LOG_ERRORS as e:
            QMessageBox.warning(self, 'Open log file', f'{path} could not be opened as a cruise log.\n\n{e}')

    def select(self):
        entry = self.selected()
        if entry is not None:
            self.open(entry)

    def open(self, entry):
        """Make a cruise current, offering to locate its log if it's missing. True if it worked."""
        while True:
            try:
                self.store.open_cruise(entry['id'])
                return True
            except FileNotFoundError:
                if not self._locate(entry):
                    return False
            except LOG_ERRORS as e:
                QMessageBox.warning(self, 'Select cruise', f"The log for {entry['name']} could not be opened.\n\n{e}")
                return False

    def _locate(self, entry):
        """Ask for a missing log's new location. True if one was chosen."""
        answer = QMessageBox.question(self, 'Log not found', f"The log for {entry['name']} was not found at\n"
                                      f"{entry['log']}\n\nWas it moved? Locate it?")
        if answer != QMessageBox.StandardButton.Yes:
            return False
        path, _ = QFileDialog.getOpenFileName(self, 'Locate log file', str(Path(entry['log']).parent),
                                              'Cruise logs (*.sqlite);;All files (*)')
        if not path:
            return False
        try:
            self.store.locate_log(entry['id'], path)
            return True
        except LOG_ERRORS as e:
            QMessageBox.warning(self, 'Locate log file', f'{path} could not be opened as a cruise log.\n\n{e}')
            return False

    def edit(self):
        entry = self.selected()
        if entry is None:
            return
        cruise = self.store.details(entry)
        if cruise is None:
            if not self._locate(entry) or (cruise := self.store.details(entry)) is None:
                return
        form = CruiseForm(self.store, row=cruise, log_path=entry['log'], parent=self)
        try:
            if not form.exec():
                return
            values, new_log = form.values(), form.log_path()
        finally:
            form.deleteLater()
        try:
            self.store.update_cruise(entry['id'], {c: values[c] for c in CruiseForm.EDITABLE})
        except LOG_ERRORS as e:
            QMessageBox.warning(self, 'Edit cruise', f'The cruise could not be changed.\n\n{e}')
            return
        old_log = Path(entry['log'])
        if new_log != old_log:
            self.move(entry, old_log, new_log)

    def move(self, entry, old_log, new_log):
        """Move a log, with the user's approval. If they decline or it fails, the log stays where it is."""
        answer = QMessageBox.question(self, 'Move log file', f'Move the log file\n\nfrom {old_log}\n\nto {new_log}?')
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.store.move_log(entry['id'], new_log)
        except LOG_ERRORS as e:
            QMessageBox.warning(self, 'Move log file', f'The log file could not be moved and is still at\n{old_log}\n\n{e}')

    def remove(self):
        entry = self.selected()
        if entry is None:
            return
        answer = QMessageBox.question(self, 'Remove cruise', f"Remove {entry['name']} from the list?\n\n"
                                      f"Its log file is kept at\n{entry['log']}\nand can be opened again later.")
        if answer == QMessageBox.StandardButton.Yes:
            self.store.remove_cruise(entry['id'])
