"""The pages shown from the sidebar."""

import html
from collections import Counter

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..formats import duration, parse_time
from ..lookups import person_label
from .charts import DIVE_COLOR, PILOT_COLOR, TRANSECT_COLOR, BarChart, TimelineChart


def _title(text):
    label = QLabel(text)
    font = label.font()
    font.setPointSizeF(font.pointSizeF() * 1.6)
    label.setFont(font)
    return label


def _table():
    table = QTableWidget()
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    table.horizontalHeader().setStretchLastSection(True)
    table.setWordWrap(False)
    return table


def _fill(table, headers, rows):
    """rows: lists of display strings."""
    table.clear()
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            table.setItem(r, c, QTableWidgetItem('' if value is None else str(value)))
    table.resizeColumnsToContents()
    for c in range(table.columnCount()):
        table.setColumnWidth(c, min(table.columnWidth(c), 320))


class TablePage(QWidget):
    """A log table with Add, Edit and Delete. columns: [(header, row -> value)]."""

    def __init__(self, store, title, table, columns, form_class, parent=None):
        super().__init__(parent)
        self.store, self.table_name, self.columns, self.form_class = store, table, columns, form_class
        self.rows = []

        add, edit, delete = QPushButton('Add'), QPushButton('Edit'), QPushButton('Delete')
        add.clicked.connect(self.add)
        edit.clicked.connect(self.edit)
        delete.clicked.connect(self.delete)
        buttons = QHBoxLayout()
        for b in (add, edit, delete):
            buttons.addWidget(b)
        buttons.addStretch()

        self.table = _table()
        self.table.doubleClicked.connect(self.edit)
        layout = QVBoxLayout(self)
        layout.addWidget(_title(title))
        layout.addLayout(buttons)
        layout.addWidget(self.table)
        store.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        self.rows = self.store.log.rows(self.table_name)
        _fill(self.table, [h for h, _ in self.columns], [[f(r) for _, f in self.columns] for r in self.rows])

    def selected(self):
        """The selected row, or None after telling the user to select one."""
        index = self.table.currentRow() if self.table.selectionModel().hasSelection() else -1
        if index < 0:
            QMessageBox.information(self, 'Select a row', 'Please select a row.')
            return None
        return self.rows[index]

    def add(self):
        form = self.form_class(self.store, parent=self)
        try:
            if form.exec():
                self.store.log.insert(self.table_name, form.values())
                self.store.notify()
        finally:
            form.deleteLater()

    def edit(self):
        row = self.selected()
        if row is None:
            return
        form = self.form_class(self.store, row=row, parent=self)
        try:
            if form.exec():
                values = form.values()
                self.store.log.update(self.table_name, row['row_id'], {c: values[c] for c in form.EDITABLE})
                self.store.notify()
        finally:
            form.deleteLater()

    def delete(self):
        row = self.selected()
        if row is None:
            return
        answer = QMessageBox.warning(self, 'Delete selected row?', 'Warning: This action cannot be undone!',
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                     QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Yes:
            self.store.log.delete(self.table_name, row['row_id'])
            self.store.notify()


class LookupPage(QWidget):
    """People or instruments: read-only, from the API. kind: 'people' or 'instruments'."""

    COLUMNS = {
        'people': [('First name', 'first_name'), ('Last name', 'last_name'), ('ID', 'id')],
        'instruments': [('Name', 'name'), ('Serial number', 'serial_number'), ('Brand', 'brand'),
                        ('Model', 'model'), ('Type', 'type'), ('Retired', 'retired'), ('ID', 'id')],
    }

    def __init__(self, store, title, kind, parent=None):
        super().__init__(parent)
        self.store, self.kind = store, kind
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.RichText)
        self.status.setWordWrap(True)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.table = _table()
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)

        layout = QVBoxLayout(self)
        layout.addWidget(_title(title))
        layout.addWidget(self.status)
        layout.addWidget(self.search)
        layout.addWidget(self.table)
        store.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        info = self.store.lookups.info()
        if info is None:
            self.status.setText('<b>No lookups yet.</b> Click <i>Update lookups</i> while connected to the network.')
        else:
            self.status.setText(f"Last updated {html.escape(info['updated_on'])} from {html.escape(info['source'])}. "
                                'Click <i>Update lookups</i> to refresh.')
        rows = getattr(self.store.lookups, self.kind)()
        cols = self.COLUMNS[self.kind]
        _fill(self.table, [h for h, _ in cols], [[r[c] for _, c in cols] for r in rows])
        self._filter()

    def _filter(self):
        words = self.search.text().lower().split()
        for r in range(self.table.rowCount()):
            text = ' '.join(self.table.item(r, c).text().lower() for c in range(self.table.columnCount()))
            self.table.setRowHidden(r, not all(w in text for w in words))


class _InfoBox(QFrame):
    def __init__(self, title, color):
        super().__init__()
        self.setObjectName('infobox')
        self.setStyleSheet(f'#infobox {{ border: 1px solid palette(mid); border-left: 6px solid {color}; }}')
        self.value = QLabel('0')
        font = self.value.font()
        font.setPointSizeF(font.pointSizeF() * 1.8)
        font.setBold(True)
        self.value.setFont(font)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(title))
        layout.addWidget(self.value)


class ChecksPage(QScrollArea):
    """Totals, warnings and charts to check the log."""

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWidgetResizable(True)
        body = QWidget()
        self.setWidget(body)
        layout = QVBoxLayout(body)
        layout.addWidget(_title('Checks'))

        boxes = QHBoxLayout()
        self.totals = {
            'dives': _InfoBox('Total dives', DIVE_COLOR.name()),
            'transects': _InfoBox('Total transects', TRANSECT_COLOR.name()),
            'equipconfig': _InfoBox('Total equipment configurations', '#00c0ef'),
            'diveconfig': _InfoBox('Total dive configurations', '#d81b60'),
        }
        for box in self.totals.values():
            boxes.addWidget(box)
        layout.addLayout(boxes)

        self.warnings = QLabel()
        self.warnings.setTextFormat(Qt.TextFormat.RichText)
        self.warnings.setWordWrap(True)
        self.warnings.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        warnings_box = QGroupBox('Warnings')
        QVBoxLayout(warnings_box).addWidget(self.warnings)
        layout.addWidget(warnings_box)

        self.dive_lengths = BarChart('Length in minutes', DIVE_COLOR)
        self.transect_lengths = BarChart('Length in minutes', TRANSECT_COLOR)
        self.timeline = TimelineChart()
        self.pilot_hours = BarChart('Total hours', PILOT_COLOR)
        grid = QGridLayout()
        for i, (title, chart) in enumerate([('Duration of dives', self.dive_lengths),
                                            ('Duration of transects', self.transect_lengths),
                                            ('Timeline', self.timeline),
                                            ('Hours piloting', self.pilot_hours)]):
            box = QGroupBox(title)
            QVBoxLayout(box).addWidget(chart)
            grid.addWidget(box, i // 2, i % 2, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(grid)
        layout.addStretch()
        store.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        log = self.store.log
        dives, transects = log.rows('dives'), log.rows('transects')
        for table, box in self.totals.items():
            box.value.setText(str(len(log.rows(table))))
        self.warnings.setText(warnings_html(dives, transects))

        self.dive_lengths.set_data([(d['name'], duration(d['start_time'], d['end_time'])) for d in dives])
        self.transect_lengths.set_data([(t['name'], duration(t['start_time'], t['end_time'])) for t in transects])
        self.timeline.set_data([
            (d['name'], parse_time(d['start_time']), parse_time(d['end_time']),
             [(parse_time(t['start_time']), parse_time(t['end_time'])) for t in transects if t['dive_name'] == d['name']])
            for d in dives])

        # Hours by pilot (or team of pilots), by name
        names = {str(p['id']): person_label(p) for p in self.store.lookups.people()}
        hours = Counter()
        for d in dives:
            h = duration(d['start_time'], d['end_time'], 3600)
            if h is not None:
                hours[pilot_names(d['pilot'], names)] += h
        self.pilot_hours.set_data(sorted(hours.items()))


def pilot_names(pilot, names):
    """'7;9' -> 'Jackie Doe, Stacey Ray'. Unknown IDs are shown as they are."""
    return ', '.join(names.get(i, i) for i in (pilot or '').split(';') if i)


def warnings_html(dives, transects):
    """Missing dives, duplicate names, and times that can't be read or are out of order."""
    dive_names = [d['name'] for d in dives]
    transect_names = [t['name'] for t in transects]
    warnings = {
        'Missing dives': [t['dive_name'] for t in transects if t['dive_name'] not in dive_names],
        'Duplicate dives': [n for n, c in Counter(dive_names).items() if c > 1],
        'Duplicate transects': [n for n, c in Counter(transect_names).items() if c > 1],
        'Unreadable times': [r['name'] for r in dives + transects
                             if parse_time(r['start_time']) is None or parse_time(r['end_time']) is None],
        'Ends before start': [r['name'] for r in dives + transects
                              if (duration(r['start_time'], r['end_time']) or 0) < 0],
    }
    lines = [f'<b>{k}</b>: {html.escape(", ".join(sorted(set(v))))}' for k, v in warnings.items() if v]
    return '<br><br>'.join(lines) if lines else '<h4>No warnings</h4>'
