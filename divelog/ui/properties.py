"""The configuration properties editor: the variables (with units and
descriptions) that equipment configurations can set. They're kept in the settings."""

import re

from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel,
                               QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..settings import PROPERTY_FIELDS

# Characters a variable can't contain, because configuration strings are {'name':value, ...}
_BAD = re.compile(r"[',:{}]")


class PropertiesEditor(QDialog):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle('Configuration properties')
        self.resize(620, 460)
        self._added = []  # the variable cells of rows added in this editor, in order
        self.saved_last_added = None

        self.table = QTableWidget(0, len(PROPERTY_FIELDS))
        self.table.setHorizontalHeaderLabels(['Variable', 'Unit', 'Description'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        for p in store.settings.config_properties:
            self._append(p)

        add, remove = QPushButton('Add'), QPushButton('Remove')
        add.clicked.connect(self.add)
        remove.clicked.connect(self.remove)
        row = QHBoxLayout()
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        note = QLabel('Variables that equipment configurations can set. Removing one doesn\'t change '
                      'configurations that already use it.')
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addLayout(row)
        layout.addWidget(self.table)
        layout.addWidget(buttons)

    def _append(self, values):
        r = self.table.rowCount()
        self.table.insertRow(r)
        for c, key in enumerate(PROPERTY_FIELDS):
            self.table.setItem(r, c, QTableWidgetItem(values.get(key, '')))
        return r

    def add(self):
        """A new, empty row, ready to type the variable's name."""
        r = self._append({})
        self._added.append(self.table.item(r, 0))
        self.table.setCurrentCell(r, 0)
        self.table.editItem(self.table.item(r, 0))

    def remove(self):
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)

    def properties(self):
        """The rows as property dicts, skipping completely empty rows."""
        rows = [{key: (self.table.item(r, c).text().strip() if self.table.item(r, c) else '')
                 for c, key in enumerate(PROPERTY_FIELDS)} for r in range(self.table.rowCount())]
        return [p for p in rows if any(p.values())]

    def problems(self, properties):
        names = [p['variable'] for p in properties]
        if any(not n for n in names):
            return 'Every property needs a variable name.'
        if bad := [n for n in names if _BAD.search(n)]:
            return f"Variable names can't contain ' , : {{ or }}: {', '.join(bad)}"
        if dupes := sorted({n for n in names if names.count(n) > 1}):
            return f"Variable names must be unique: {', '.join(dupes)}"
        return None

    def accept(self):
        self.table.setCurrentItem(None)  # finish any edit in progress
        properties = self.properties()
        problem = self.problems(properties)
        if problem:
            QMessageBox.warning(self, 'Configuration properties', problem)
            return
        self.store.set_config_properties(properties)
        # The last row added in this editor that still exists and has a name
        names = {p['variable'] for p in properties}
        live = [item.text().strip() for item in self._added if self._alive(item)]
        self.saved_last_added = next((n for n in reversed(live) if n in names), None)
        super().accept()

    def _alive(self, item):
        try:
            return item.tableWidget() is self.table
        except RuntimeError:  # its row was removed, deleting the cell
            return False


def edit_properties(store, parent=None):
    """Run the editor. Returns the last property added, if one was added and saved."""
    editor = PropertiesEditor(store, parent)
    try:
        return editor.saved_last_added if editor.exec() else None
    finally:
        editor.deleteLater()
