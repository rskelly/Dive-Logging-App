"""Building blocks for the entry forms."""

from PySide6.QtCore import QDate, QDateTime, Qt, QTime, QTimeZone, Signal
from PySide6.QtWidgets import (QComboBox, QDateEdit, QDateTimeEdit, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                               QVBoxLayout, QWidget)

from ..formats import parse_time

REQUIRED = ' <span style="color:#c0392b">*</span>'


class EntryForm(QDialog):
    """A dialog of labelled fields. Submit is enabled only while every required
    field is filled in and every check passes."""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        self._checks = []

        self.form = QFormLayout()
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.submit = self.buttons.addButton('Submit', QDialogButtonBox.ButtonRole.AcceptRole)
        self.submit.setDefault(True)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(self.form)
        note = QLabel('Fields marked' + REQUIRED + ' are mandatory.')
        note.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(note)
        layout.addWidget(self.buttons)

    def add_row(self, label, widget, required=False):
        """Add a field. widget may be a layout or widget; returns it."""
        text = QLabel(label + (REQUIRED if required else ''))
        text.setTextFormat(Qt.TextFormat.RichText)
        self.form.addRow(text, widget)
        return widget

    def add_check(self, check, *signals):
        """Require check() to be true; re-check whenever one of signals fires."""
        self._checks.append(check)
        for signal in signals:
            signal.connect(self.validate)

    def require(self, field):
        """Require a field (anything with value() and changed) to have a value."""
        self.add_check(lambda: bool(field.value()), field.changed)

    def validate(self):
        self.submit.setEnabled(all(check() for check in self._checks))

    def add_hint(self, check, message, *signals):
        """Like add_check, with a message under the last field while check() fails."""
        hint = QLabel(message)
        hint.setStyleSheet('color: #c0392b')
        hint.setWordWrap(True)
        self.form.addRow('', hint)

        def checked():
            ok = check()
            self.form.setRowVisible(hint, not ok)
            return ok
        self.add_check(checked, *signals)
        checked()

    def saved(self, values):
        """Called after the form's values are saved."""

    def showEvent(self, event):
        self.validate()
        super().showEvent(event)


class TextField(QLineEdit):
    changed = Signal()

    def __init__(self, text='', parent=None):
        super().__init__(text or '', parent)
        self.textChanged.connect(self.changed)

    def value(self):
        return self.text().strip()

    def set_value(self, value):
        self.setText(value or '')


class ChoiceField(QComboBox):
    """A drop-down of (label, value) choices. Starts with nothing selected unless
    a value is given."""
    changed = Signal()

    def __init__(self, choices=(), value=None, parent=None):
        super().__init__(parent)
        self.setPlaceholderText('Select...')
        self.set_choices(choices, value)
        self.currentIndexChanged.connect(self.changed)

    def set_choices(self, choices, value=None):
        self.blockSignals(True)
        self.clear()
        for label, data in choices:
            self.addItem(label, data)
        self.blockSignals(False)
        self.set_value(value)

    def value(self):
        return self.currentData() if self.currentIndex() >= 0 else None

    def set_value(self, value, unknown_label=None):
        """Select value. A value that isn't a choice is added, labelled unknown_label
        (or the value itself), so editing a record never silently changes it."""
        if value is None or value == '':
            self.setCurrentIndex(-1)
            return
        index = self.findData(value)
        if index < 0:
            self.addItem(unknown_label or str(value), value)
            index = self.count() - 1
        self.setCurrentIndex(index)


class MultiChoiceField(QListWidget):
    """A list of (label, value) choices with check boxes."""
    changed = Signal()

    def __init__(self, choices=(), parent=None):
        super().__init__(parent)
        self.setMaximumHeight(170)
        for label, data in choices:
            self._add(label, data)
        self.itemChanged.connect(lambda _: self.changed.emit())

    def _add(self, label, data):
        item = QListWidgetItem(label, self)
        item.setData(Qt.ItemDataRole.UserRole, data)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Unchecked)
        return item

    def _items(self):
        return [self.item(i) for i in range(self.count())]

    def add_choice(self, label, data):
        """Add an unchecked choice, unless it's already there."""
        if data not in [i.data(Qt.ItemDataRole.UserRole) for i in self._items()]:
            self._add(label, data)

    def value(self):
        """The checked values, in list order."""
        return [i.data(Qt.ItemDataRole.UserRole) for i in self._items()
                if i.checkState() == Qt.CheckState.Checked]

    def set_value(self, values, unknown_label=None):
        """Check exactly values. Values that aren't choices are added (see ChoiceField)."""
        known = {i.data(Qt.ItemDataRole.UserRole): i for i in self._items()}
        for v in values:
            if v not in known:
                known[v] = self._add(unknown_label(v) if unknown_label else str(v), v)
        for v, item in known.items():
            item.setCheckState(Qt.CheckState.Checked if v in values else Qt.CheckState.Unchecked)


class DateField(QDateEdit):
    """A date (YYYY-MM-DD) with a calendar. Defaults to today."""
    changed = Signal()

    def __init__(self, value=None, parent=None):
        super().__init__(parent)
        self.setCalendarPopup(True)
        self.setDisplayFormat('yyyy-MM-dd')
        self.set_value(value)
        self.dateChanged.connect(self.changed)

    def value(self):
        return self.date().toString('yyyy-MM-dd')

    def set_value(self, value):
        date = QDate.fromString(value or '', 'yyyy-MM-dd')
        self.setDate(date if date.isValid() else QDate.currentDate())


UTC = QTimeZone(QTimeZone.Initialization.UTC)
# The log's time format, in Qt's notation (see formats.TIME_FORMAT)
QT_TIME_FORMAT = "yyyy-MM-dd'T'HH:mm:ss'Z'"


class _DateTimeEdit(QDateTimeEdit):
    """A UTC date and time with a calendar. Its minimum stands for 'not set'."""
    UNSET = QDateTime(QDate(2000, 1, 1), QTime(0, 0), UTC)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTimeZone(UTC)
        self.setDisplayFormat("yyyy-MM-dd HH:mm:ss 'UTC'")
        self.setCalendarPopup(True)
        self.setMinimumDateTime(self.UNSET)
        self.setSpecialValueText('Not set')  # shown at the minimum
        self.setDateTime(self.UNSET)

    def is_set(self):
        return self.dateTime() != self.UNSET

    def mousePressEvent(self, event):
        # Open the calendar at today, not at 'not set' (2000)
        if not self.is_set():
            self.setDateTime(QDateTime.currentDateTimeUtc().toTimeZone(UTC))
        super().mousePressEvent(event)


class TimeField(QWidget):
    """A time (UTC), picked from a calendar or typed, with a button that sets it to now."""
    changed = Signal()

    def __init__(self, button_label='Now', value='', parent=None):
        super().__init__(parent)
        self.edit = _DateTimeEdit()
        self.set_value(value)
        self.edit.dateTimeChanged.connect(self.changed)
        self.button = QPushButton(button_label)
        self.button.clicked.connect(self.set_now)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.button)

    def set_now(self):
        now = QDateTime.currentDateTimeUtc().toTimeZone(UTC)
        self.edit.setDateTime(now.addMSecs(-now.time().msec()))

    def is_valid(self):
        return self.edit.is_set()

    def value(self):
        """The time in the log's format, or '' if not set."""
        return self.edit.dateTime().toString(QT_TIME_FORMAT) if self.edit.is_set() else ''

    def set_value(self, value):
        """Set from the log's format; anything else (e.g. '') means not set."""
        when = parse_time(value)
        self.edit.setDateTime(QDateTime.fromSecsSinceEpoch(int(when.timestamp()), UTC) if when else _DateTimeEdit.UNSET)


def unique(values):
    """Distinct non-empty values, in order."""
    return list(dict.fromkeys(v for v in values if v))


def same_choices(values):
    return [(v, v) for v in values]
