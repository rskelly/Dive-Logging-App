"""Entry forms. Each form's values() returns the row to save, and EDITABLE lists
the columns an edit may change. Dives and transects belong to the current
cruise, so they have no cruise or leg fields."""

from pathlib import Path

from PySide6.QtCore import QLocale, Qt
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QPushButton, QWidget

from ..formats import build_config, format_number, join_ids, parse_config, split_ids
from ..lookups import instrument_label, person_label, platform_label
from .widgets import (REQUIRED, ChoiceField, DateField, EntryForm, MultiChoiceField, TextField, TimeField,
                      same_choices, unique)


def _row(*widgets, stretch_first=True):
    box = QWidget()
    layout = QHBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    for i, w in enumerate(widgets):
        layout.addWidget(w, 1 if (i == 0 and stretch_first) else 0)
    return box


def _unique_name_check(form, field, existing, own=None):
    """Block a name that another record already uses."""
    taken = set(existing) - {own}
    form.add_hint(lambda: field.value() not in taken, 'This name is already used.', field.changed)


def _default(choices, *preferred):
    """The first preferred value that is one of choices."""
    return next((p for p in preferred if p and p in choices), None)


class CruiseForm(EntryForm):
    """A cruise's properties and where its log is kept. For a new cruise the log
    defaults to the default log folder, named after the cruise and leg."""
    EDITABLE = ['name', 'leg', 'start_date', 'end_date', 'ship_id', 'objective', 'summary', 'note']

    def __init__(self, store, row=None, log_path=None, parent=None):
        super().__init__('Cruise', parent)
        self.store = store
        row = row or {}
        self.original_log = Path(log_path) if log_path else None

        self.name = self.add_row('Cruise name', TextField(row.get('name')), True)
        self.leg = self.add_row('Leg', TextField(row.get('leg') or ('1' if not row else '')), True)
        self.start = self.add_row('Start date', DateField(row.get('start_date')), True)
        self.end = self.add_row('End date', DateField(row.get('end_date')), True)
        self.add_hint(lambda: self.end.value() >= self.start.value(), 'The end date is before the start date.',
                      self.start.changed, self.end.changed)
        ships = store.lookups.ships()
        self.ship = self.add_row('Ship', ChoiceField([(platform_label(p), p['id']) for p in ships]), True)
        self.ship.set_value(row.get('ship_id'), f"Unknown ship (ID {row.get('ship_id')})")
        if not ships:
            self.ship.setPlaceholderText('No ships yet: update the lookups first')
        self.objective = self.add_row('Objective', TextField(row.get('objective')), True)
        self.summary = self.add_row('Summary', TextField(row.get('summary')))
        self.note = self.add_row('Note', TextField(row.get('note')))
        for field in (self.name, self.leg, self.ship, self.objective):
            self.require(field)

        # The log file: the default location for a new cruise, until another is chosen
        self.log = TextField(str(log_path) if log_path else '')
        self.log.setReadOnly(True)
        change = QPushButton('Change...')
        change.clicked.connect(self._choose_log)
        self.add_row('Log file', _row(self.log, change), True)
        self._auto_log = log_path is None
        self.name.changed.connect(self._update_log)
        self.leg.changed.connect(self._update_log)
        self._update_log()
        self.add_hint(self._log_ok, 'A file already exists there. Choose another location.', self.log.changed)
        self.log.changed.connect(self._show_log)
        self._show_log()

    def _update_log(self):
        if self._auto_log:
            self.log.set_value(str(self.store.default_log_path(self.name.value(), self.leg.value())))

    def _choose_log(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Log file', self.log.value(), 'Cruise logs (*.sqlite);;All files (*)',
                                              options=QFileDialog.Option.DontConfirmOverwrite)
        if path:
            path = Path(path)
            self.set_log_path(path if path.suffix else path.with_suffix('.sqlite'))

    def set_log_path(self, path):
        self._auto_log = False
        self.log.set_value(str(path))

    def _show_log(self):
        self.log.setToolTip(self.log.value())

    def log_path(self):
        return Path(self.log.value())

    def _log_ok(self):
        # The log can stay where it is; anywhere else must be free
        return self.log_path() == self.original_log or not self.log_path().exists()

    def values(self):
        return {'name': self.name.value(), 'leg': self.leg.value(), 'start_date': self.start.value(),
                'end_date': self.end.value(), 'ship_id': self.ship.value(), 'objective': self.objective.value(),
                'summary': self.summary.value(), 'note': self.note.value()}


class EquipconfigForm(EntryForm):
    """An instrument or a platform (sub), and its configuration."""
    EDITABLE = ['instrument_id', 'platform_id', 'type', 'configuration', 'note']

    def __init__(self, store, row=None, parent=None):
        super().__init__('Equipment configuration', parent)
        self.store = store
        row = row or {}
        self.type = self.add_row('Type', ChoiceField(same_choices(['instrument', 'platform']),
                                                     row.get('type') or 'instrument'), True)
        self.equipment = ChoiceField()
        self.equipment_label = QLabel()
        self.equipment_label.setTextFormat(Qt.TextFormat.RichText)
        self.form.addRow(self.equipment_label, self.equipment)
        self._set_equipment_choices()
        if self.type.value() == 'platform':
            self.equipment.set_value(row.get('platform_id'), f"Unknown platform (ID {row.get('platform_id')})")
        else:
            self.equipment.set_value(row.get('instrument_id'), f"Unknown instrument (ID {row.get('instrument_id')})")
        self.type.changed.connect(self._set_equipment_choices)
        self.name = self.add_row('Name', TextField(row.get('name')), True)
        for field in (self.type, self.equipment, self.name):
            self.require(field)
        if row:
            self.name.setReadOnly(True)
        else:
            _unique_name_check(self, self.name, [r['name'] for r in store.log.rows('equipconfig')])

        # Variables are added to the configuration string one at a time
        self.variable = ChoiceField(same_choices(store.config_variables))
        self.value = TextField()
        self.value.setPlaceholderText('Value')
        validator = QDoubleValidator(self.value)
        validator.setLocale(QLocale.c())  # always a '.' decimal point
        self.value.setValidator(validator)
        self.add = QPushButton('Add')
        self.add.clicked.connect(self._add_variable)
        self.add_row('Variable', _row(self.variable, self.value, self.add, stretch_first=False))
        self.variable.changed.connect(self._update_add)
        self.value.changed.connect(self._update_add)
        self._update_add()

        self.configuration = self.add_row('Configuration', TextField(row.get('configuration') or '{}'))
        self.note = self.add_row('Note', TextField(row.get('note')))

    def _set_equipment_choices(self):
        """Instruments, or subs (the ship is the cruise's), depending on the type."""
        if self.type.value() == 'platform':
            self.equipment_label.setText('Platform' + REQUIRED)
            choices = [(platform_label(p), p['id']) for p in self.store.lookups.subs()]
        else:
            self.equipment_label.setText('Instrument' + REQUIRED)
            choices = [(instrument_label(i), i['id']) for i in self.store.lookups.instruments()]
        self.equipment.set_choices(choices)
        self.equipment.changed.emit()

    def _update_add(self):
        self.add.setEnabled(self.variable.value() is not None and self.value.hasAcceptableInput())

    def _add_variable(self):
        pairs = parse_config(self.configuration.value())
        pairs.append((self.variable.value(), format_number(self.value.value())))
        self.configuration.set_value(build_config(pairs))
        self.value.clear()

    def values(self):
        platform = self.type.value() == 'platform'
        return {'name': self.name.value(), 'type': self.type.value(),
                'instrument_id': None if platform else self.equipment.value(),
                'platform_id': self.equipment.value() if platform else None,
                'configuration': self.configuration.value(), 'note': self.note.value()}


class DiveconfigForm(EntryForm):
    """The sub and the instruments on the ship and the sub. The ship is the cruise's."""
    EDITABLE = ['sub_config', 'ship_instrument_configs', 'sub_instrument_configs', 'note']

    def __init__(self, store, row=None, parent=None):
        super().__init__('Dive configuration', parent)
        row = row or {}
        configs = store.log.rows('equipconfig')
        platforms = same_choices(c['name'] for c in configs if c['type'] == 'platform')
        instruments = same_choices([c['name'] for c in configs if c['type'] == 'instrument'])

        self.name = self.add_row('Name', TextField(row.get('name')), True)
        self.sub = self.add_row('Sub', ChoiceField(platforms, row.get('sub_config')), True)
        self.ship_instruments = self.add_row('Ship instruments', MultiChoiceField(instruments), True)
        self.ship_instruments.set_value(split_ids(row.get('ship_instrument_configs')))
        self.sub_instruments = self.add_row('Sub instruments', MultiChoiceField(instruments), True)
        self.sub_instruments.set_value(split_ids(row.get('sub_instrument_configs')))
        self.note = self.add_row('Note', TextField(row.get('note')))
        for field in (self.name, self.sub, self.ship_instruments, self.sub_instruments):
            self.require(field)
        if row:
            self.name.setReadOnly(True)
        else:
            _unique_name_check(self, self.name, [r['name'] for r in store.log.rows('diveconfig')])

    def values(self):
        return {'name': self.name.value(), 'ship_config': '', 'sub_config': self.sub.value(),
                'ship_instrument_configs': join_ids(self.ship_instruments.value()),
                'sub_instrument_configs': join_ids(self.sub_instruments.value()),
                'note': self.note.value()}


def _cruise_values(store):
    """The current cruise's name and leg, which dives and transects record."""
    cruise = store.cruise or {}
    return {'cruise_name': cruise.get('name') or '', 'leg': cruise.get('leg') or ''}


class DiveForm(EntryForm):
    EDITABLE = ['name', 'pilot', 'start_time', 'end_time', 'site_name', 'dive_config', 'objective', 'summary', 'note']

    def __init__(self, store, row=None, parent=None):
        super().__init__('Dive', parent)
        self.store = store
        diveconfigs = [d['name'] for d in store.log.rows('diveconfig')]
        editing = row is not None
        # A new dive uses the last dive config used, or else the newest
        row = row or {'dive_config': _default(diveconfigs, store.last('last_dive_config'),
                                              diveconfigs[-1] if diveconfigs else None)}

        self.name = self.add_row('Dive name', TextField(row.get('name')), True)
        self.require(self.name)
        _unique_name_check(self, self.name, [d['name'] for d in store.log.rows('dives')],
                           own=row.get('name') if editing else None)
        self.dive_config = self.add_row('Dive config', ChoiceField(same_choices(diveconfigs), row.get('dive_config')), True)
        self.pilot = self.add_row('Pilot', MultiChoiceField(
            [(person_label(p), str(p['id'])) for p in store.lookups.people()]), True)
        self.pilot.set_value(split_ids(row.get('pilot')), lambda i: f'Unknown person (ID {i})')
        self.start = self.add_row('Start time', TimeField('Start', row.get('start_time')), True)

        self.add_transect = QPushButton('Add transect')
        self.add_transect.clicked.connect(self._add_transect)
        self.transects = QLabel()
        self.transects.setTextFormat(Qt.TextFormat.PlainText)
        self.transects.setWordWrap(True)
        self.add_row('', _row(self.add_transect, self.transects, stretch_first=False))
        self.name.changed.connect(self._show_transects)
        self._show_transects()

        self.end = self.add_row('End time', TimeField('End', row.get('end_time')), True)
        self.site_name = self.add_row('Site name', TextField(row.get('site_name')))
        self.objective = self.add_row('Objective', TextField(row.get('objective')))
        self.summary = self.add_row('Summary', TextField(row.get('summary')))
        self.note = self.add_row('Note', TextField(row.get('note')))
        for field in (self.dive_config, self.pilot):
            self.require(field)
        for time in (self.start, self.end):
            self.add_check(time.is_valid, time.changed)

    def _show_transects(self):
        names = [t['name'] for t in self.store.log.rows('transects') if t['dive_name'] == self.name.value()]
        self.transects.setText('Transects: ' + ', '.join(names) if names else '')
        self.add_transect.setEnabled(bool(self.name.value()))

    def _add_transect(self):
        # The transect form opens on top of this one, which keeps its values
        form = TransectForm(self.store, dive=self.name.value(), parent=self)
        try:
            if form.exec():
                values = form.values()
                self.store.log.insert('transects', values)
                form.saved(values)
                self.store.notify()
                self._show_transects()
        finally:
            form.deleteLater()

    def values(self):
        return {**_cruise_values(self.store), 'name': self.name.value(), 'pilot': join_ids(self.pilot.value()),
                'start_time': self.start.value(), 'end_time': self.end.value(), 'site_name': self.site_name.value(),
                'dive_config': self.dive_config.value(), 'objective': self.objective.value(),
                'summary': self.summary.value(), 'note': self.note.value()}

    def saved(self, values):
        self.store.remember(last_dive=values['name'], last_dive_config=values['dive_config'])


class TransectForm(EntryForm):
    EDITABLE = ['dive_name', 'name', 'start_time', 'end_time', 'objective', 'summary', 'note']

    def __init__(self, store, row=None, dive=None, parent=None):
        super().__init__('Transect', parent)
        self.store = store
        self.transect_rows = store.log.rows('transects')
        dives = [d['name'] for d in store.log.rows('dives')]
        editing = row is not None
        if row is None:
            # A new transect belongs to the given dive (from the dive form), or
            # else the last dive used, or else the newest dive
            name = dive or _default(dives, store.last('last_dive'), dives[-1] if dives else None)
            row = {'dive_name': name, 'name': self._next_name(name)}

        self.dive_name = self.add_row('Dive name', ChoiceField(same_choices(unique(dives + [row.get('dive_name')])),
                                                                row.get('dive_name')), True)
        self.name = self.add_row('Transect name', TextField(row.get('name')), True)
        _unique_name_check(self, self.name, [t['name'] for t in self.transect_rows],
                           own=row.get('name') if editing else None)
        if not editing:
            # Keep the suggested name in step with the dive, until it's edited
            self._suggested = self.name.value()
            self.dive_name.changed.connect(self._follow_dive)
        self.start = self.add_row('Start time', TimeField('Start', row.get('start_time')), True)
        self.end = self.add_row('End time', TimeField('End', row.get('end_time')), True)
        self.objective = self.add_row('Objective', TextField(row.get('objective')))
        self.summary = self.add_row('Summary', TextField(row.get('summary')))
        self.note = self.add_row('Note', TextField(row.get('note')))
        for field in (self.dive_name, self.name):
            self.require(field)
        for time in (self.start, self.end):
            self.add_check(time.is_valid, time.changed)

    def _next_name(self, dive):
        """<dive>_<n>, numbered after the dive's existing transects."""
        if not dive:
            return ''
        return f'{dive}_{sum(t["dive_name"] == dive for t in self.transect_rows) + 1}'

    def _follow_dive(self):
        if self.name.value() == self._suggested:
            self._suggested = self._next_name(self.dive_name.value())
            self.name.set_value(self._suggested)

    def values(self):
        return {**_cruise_values(self.store), 'dive_name': self.dive_name.value(), 'name': self.name.value(),
                'start_time': self.start.value(), 'end_time': self.end.value(),
                'objective': self.objective.value(), 'summary': self.summary.value(), 'note': self.note.value()}

    def saved(self, values):
        self.store.remember(last_dive=values['dive_name'])
