"""Entry forms for each log table. Each form's values() returns the row to save,
and EDITABLE lists the columns an edit may change: names
that other records refer to are fixed once saved."""

from PySide6.QtCore import QLocale, Qt
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from ..formats import build_config, format_number, join_ids, parse_config, split_ids
from ..lookups import instrument_label, person_label
from .widgets import (ChoiceField, EntryForm, MultiChoiceField, TextField, TimeField, same_choices,
                      unique)


def _row(*widgets, stretch_first=True):
    box = QWidget()
    layout = QHBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    for i, w in enumerate(widgets):
        layout.addWidget(w, 1 if (i == 0 and stretch_first) else 0)
    return box


def _unique_name_check(form, field, existing, own=None):
    """Block a name that another record already uses, and say so."""
    taken = set(existing) - {own}
    hint = QLabel()
    hint.setStyleSheet('color: #c0392b')
    form.add_row('', hint)

    def check():
        duplicate = field.value() in taken
        hint.setText('This name is already used.' if duplicate else '')
        form.form.setRowVisible(hint, duplicate)
        return not duplicate
    form.add_check(check, field.changed)
    check()


class CruiseForm(EntryForm):
    EDITABLE = ['objective', 'summary', 'note']

    def __init__(self, store, row=None, parent=None):
        super().__init__('Cruise', parent)
        row = row or {}
        self.name = self.add_row('Cruise name', TextField(row.get('name')), True)
        self.leg = self.add_row('Leg', TextField(row.get('leg')), True)
        self.objective = self.add_row('Objective', TextField(row.get('objective')), True)
        self.summary = self.add_row('Summary', TextField(row.get('summary')))
        self.note = self.add_row('Note', TextField(row.get('note')))
        for field in (self.name, self.leg, self.objective):
            self.require(field)
        if row:
            self.name.setReadOnly(True)
            self.leg.setReadOnly(True)

    def values(self):
        return {'name': self.name.value(), 'leg': self.leg.value(), 'objective': self.objective.value(),
                'summary': self.summary.value(), 'note': self.note.value()}


class EquipconfigForm(EntryForm):
    EDITABLE = ['instrument_id', 'type', 'configuration', 'note']

    def __init__(self, store, row=None, parent=None):
        super().__init__('Equipment configuration', parent)
        row = row or {}
        self.type = self.add_row('Type', ChoiceField(same_choices(['instrument', 'platform']),
                                                     row.get('type') or 'instrument'), True)
        self.instrument = self.add_row('Instrument', ChoiceField(
            [(instrument_label(i), i['id']) for i in store.lookups.instruments()]), True)
        self.instrument.set_value(row.get('instrument_id'), f"Unknown instrument (ID {row.get('instrument_id')})")
        self.name = self.add_row('Name', TextField(row.get('name')), True)
        for field in (self.type, self.instrument, self.name):
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

    def _update_add(self):
        self.add.setEnabled(self.variable.value() is not None and self.value.hasAcceptableInput())

    def _add_variable(self):
        pairs = parse_config(self.configuration.value())
        pairs.append((self.variable.value(), format_number(self.value.value())))
        self.configuration.set_value(build_config(pairs))
        self.value.clear()

    def values(self):
        return {'name': self.name.value(), 'instrument_id': self.instrument.value(),
                'type': self.type.value(), 'configuration': self.configuration.value(),
                'note': self.note.value()}


class DiveconfigForm(EntryForm):
    EDITABLE = ['ship_config', 'sub_config', 'ship_instrument_configs', 'sub_instrument_configs', 'note']

    def __init__(self, store, row=None, parent=None):
        super().__init__('Dive configuration', parent)
        row = row or {}
        configs = store.log.rows('equipconfig')
        platforms = same_choices(c['name'] for c in configs if c['type'] == 'platform')
        instruments = same_choices([c['name'] for c in configs if c['type'] == 'instrument'])

        self.name = self.add_row('Name', TextField(row.get('name')), True)
        self.ship = self.add_row('Ship', ChoiceField(platforms, row.get('ship_config')), True)
        self.sub = self.add_row('Sub', ChoiceField(platforms, row.get('sub_config')), True)
        self.ship_instruments = self.add_row('Ship instruments', MultiChoiceField(instruments), True)
        self.ship_instruments.set_value(split_ids(row.get('ship_instrument_configs')))
        self.sub_instruments = self.add_row('Sub instruments', MultiChoiceField(instruments), True)
        self.sub_instruments.set_value(split_ids(row.get('sub_instrument_configs')))
        self.note = self.add_row('Note', TextField(row.get('note')))
        for field in (self.name, self.ship, self.sub, self.ship_instruments, self.sub_instruments):
            self.require(field)
        if row:
            self.name.setReadOnly(True)
        else:
            _unique_name_check(self, self.name, [r['name'] for r in store.log.rows('diveconfig')])

    def values(self):
        return {'name': self.name.value(), 'ship_config': self.ship.value(), 'sub_config': self.sub.value(),
                'ship_instrument_configs': join_ids(self.ship_instruments.value()),
                'sub_instrument_configs': join_ids(self.sub_instruments.value()),
                'note': self.note.value()}


def _cruise_fields(form, store, cruise_name, leg):
    """Cruise name and leg drop-downs, defaulting to the given values."""
    cruises = store.log.rows('cruise')
    name = form.add_row('Cruise name', ChoiceField(same_choices(unique(c['name'] for c in cruises)), cruise_name), True)
    leg_ = form.add_row('Leg', ChoiceField(same_choices(unique(c['leg'] for c in cruises)), leg), True)
    form.require(name)
    form.require(leg_)
    return name, leg_


class DiveForm(EntryForm):
    EDITABLE = ['cruise_name', 'leg', 'name', 'pilot', 'start_time', 'end_time', 'site_name',
                'dive_config', 'objective', 'summary', 'note']

    def __init__(self, store, row=None, parent=None):
        super().__init__('Dive', parent)
        self.store = store
        cruises = store.log.rows('cruise')
        diveconfigs = [d['name'] for d in store.log.rows('diveconfig')]
        # New dives default to the last cruise and dive configuration
        last = cruises[-1] if cruises else {}
        row = row or {'cruise_name': last.get('name'), 'leg': last.get('leg'),
                      'dive_config': diveconfigs[-1] if diveconfigs else None}
        editing = 'row_id' in row

        self.cruise_name, self.leg = _cruise_fields(self, store, row.get('cruise_name'), row.get('leg'))
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
        dive = {'cruise_name': self.cruise_name.value(), 'leg': self.leg.value(), 'name': self.name.value()}
        form = TransectForm(self.store, dive=dive, parent=self)
        try:
            if form.exec():
                self.store.log.insert('transects', form.values())
                self.store.notify()
                self._show_transects()
        finally:
            form.deleteLater()

    def values(self):
        return {'cruise_name': self.cruise_name.value(), 'leg': self.leg.value(), 'name': self.name.value(),
                'pilot': join_ids(self.pilot.value()), 'start_time': self.start.value(),
                'end_time': self.end.value(), 'site_name': self.site_name.value(),
                'dive_config': self.dive_config.value(), 'objective': self.objective.value(),
                'summary': self.summary.value(), 'note': self.note.value()}


class TransectForm(EntryForm):
    EDITABLE = ['cruise_name', 'leg', 'dive_name', 'name', 'start_time', 'end_time',
                'objective', 'summary', 'note']

    def __init__(self, store, row=None, dive=None, parent=None):
        super().__init__('Transect', parent)
        transects = store.log.rows('transects')
        dives = store.log.rows('dives')
        editing = row is not None
        if row is None:
            # A new transect belongs to the given dive (from the dive form), or the last dive
            dive = dive or (dives[-1] if dives else {})
            n = sum(t['dive_name'] == dive.get('name') for t in transects) + 1
            row = {'cruise_name': dive.get('cruise_name'), 'leg': dive.get('leg'), 'dive_name': dive.get('name'),
                   'name': f"{dive['name']}_{n}" if dive.get('name') else ''}

        self.cruise_name, self.leg = _cruise_fields(self, store, row.get('cruise_name'), row.get('leg'))
        self.dive_name = self.add_row('Dive name', ChoiceField(
            same_choices(unique([d['name'] for d in dives] + [row.get('dive_name')])), row.get('dive_name')), True)
        self.name = self.add_row('Transect name', TextField(row.get('name')), True)
        _unique_name_check(self, self.name, [t['name'] for t in transects],
                           own=row.get('name') if editing else None)
        self.start = self.add_row('Start time', TimeField('Start', row.get('start_time')), True)
        self.end = self.add_row('End time', TimeField('End', row.get('end_time')), True)
        self.objective = self.add_row('Objective', TextField(row.get('objective')))
        self.summary = self.add_row('Summary', TextField(row.get('summary')))
        self.note = self.add_row('Note', TextField(row.get('note')))
        for field in (self.dive_name, self.name):
            self.require(field)
        for time in (self.start, self.end):
            self.add_check(time.is_valid, time.changed)

    def values(self):
        return {'cruise_name': self.cruise_name.value(), 'leg': self.leg.value(),
                'dive_name': self.dive_name.value(), 'name': self.name.value(),
                'start_time': self.start.value(), 'end_time': self.end.value(),
                'objective': self.objective.value(), 'summary': self.summary.value(), 'note': self.note.value()}
