"""Cruises, forms, pages and the main window, driven offscreen."""

import json
import shutil
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog, QMessageBox

from divelog.formats import parse_time
from divelog.lookups import update_lookups
from divelog.settings import Settings, home_dir
from divelog.store import AlreadyOpenError, Store
from divelog.ui import cruises as cruises_module
from divelog.ui.cruises import CruisesPage
from divelog.ui.forms import CruiseForm, DiveconfigForm, DiveForm, EquipconfigForm, TransectForm
from divelog.ui.main_window import MainWindow
from divelog.ui.pages import ChecksPage, TablePage, warnings_html

SHINY_LOG = Path(__file__).parent / 'fixtures' / 'shiny' / 'divelogging-db.sqlite'
CRUISE = {'name': 'C1', 'leg': '1', 'start_date': '2026-10-01', 'end_date': '2026-10-20', 'ship_id': 201,
          'objective': 'Survey', 'summary': '', 'note': ''}

YES, NO = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No


@pytest.fixture
def settings(home, api):
    return Settings(api_url=api.url)


@pytest.fixture
def store(qapp, settings, api):
    store = Store(settings)
    update_lookups(settings.lookups_path, api.url)
    yield store
    store.close()


@pytest.fixture
def cruise(store):
    """A current cruise, with a log in the default location."""
    return store.create_cruise(CRUISE, store.default_log_path('C1', '1'))


def _fill_setup(store):
    """Equipment configs and a dive config, as saved by the forms."""
    store.log.insert('equipconfig', {'name': 'phantom', 'platform_id': 202, 'type': 'platform', 'configuration': '{}'})
    store.log.insert('equipconfig', {'name': 'cam', 'instrument_id': 101, 'type': 'instrument', 'configuration': "{'pan':10}"})
    store.log.insert('diveconfig', {'name': 'dc1', 'sub_config': 'phantom', 'ship_instrument_configs': 'cam',
                                    'sub_instrument_configs': 'cam'})
    store.log.insert('diveconfig', {'name': 'dc2', 'sub_config': 'phantom', 'ship_instrument_configs': 'cam',
                                    'sub_instrument_configs': 'cam'})


def _choices(combo):
    return [combo.itemText(i) for i in range(combo.count())]


# Cruises

def test_new_cruise_form(store, home):
    form = CruiseForm(store)
    assert _choices(form.ship) == ['John P. Tully']  # ships only
    form.name.setText('PAC 2026/01')
    form.leg.setText('2')
    assert form.log_path() == home / 'logs' / 'PAC_2026_01_leg2.sqlite'
    form.ship.set_value(201)
    form.objective.setText('Survey')
    form.start.set_value('2026-10-10')
    form.end.set_value('2026-10-01')
    assert not form.submit.isEnabled()  # ends before it starts
    form.end.set_value('2026-10-20')
    assert form.submit.isEnabled()
    assert form.values() == {'name': 'PAC 2026/01', 'leg': '2', 'start_date': '2026-10-10', 'end_date': '2026-10-20',
                             'ship_id': 201, 'objective': 'Survey', 'summary': '', 'note': ''}
    # A log can't overwrite an existing file
    taken = home / 'taken.sqlite'
    taken.parent.mkdir(parents=True, exist_ok=True)
    taken.write_text('x')
    form.set_log_path(taken)
    assert not form.submit.isEnabled()


def test_creating_a_cruise_creates_its_log_and_lists_it(store, cruise, home):
    log = home / 'logs' / 'C1_leg1.sqlite'
    assert log.is_file() and store.log.path == log
    assert store.cruise['start_date'] == '2026-10-01' and store.cruise['ship_id'] == 201
    saved = json.loads((home / 'settings.json').read_text())
    assert saved['current'] == cruise
    assert saved['cruises'] == [{'id': cruise, 'name': 'C1', 'leg': '1', 'log': str(log),
                                 'last_dive': '', 'last_dive_config': ''}]
    assert Settings.load().cruise(cruise)['log'] == str(log)


def test_default_log_folder_comes_from_settings(store, tmp_path):
    store.settings.logs_dir = str(tmp_path / 'elsewhere')
    assert CruiseForm(store).log_path().parent == tmp_path / 'elsewhere'


def test_selecting_a_cruise_switches_logs(store, cruise):
    store.log.insert('dives', {'name': 'D1'})
    other = store.create_cruise({**CRUISE, 'name': 'C2'}, store.default_log_path('C2', '1'))
    assert store.cruise['name'] == 'C2' and store.log.rows('dives') == []
    store.open_cruise(cruise)
    assert [d['name'] for d in store.log.rows('dives')] == ['D1']
    assert Settings.load().current == cruise != other


def _edit_cruise(monkeypatch, page, store, cruise, new_log=None, **values):
    """Edit the cruise through the Cruises page, changing values and maybe the log location."""
    def fill(form):
        for name, value in values.items():
            getattr(form, name).set_value(value)
        if new_log:
            form.set_log_path(new_log)
        return True
    monkeypatch.setattr(CruiseForm, 'exec', fill)
    page.table.selectRow([e['id'] for e in page.entries].index(cruise))
    page.edit()


def test_editing_a_cruise_and_moving_its_log(store, cruise, monkeypatch, tmp_path):
    store.log.insert('dives', {'cruise_name': 'C1', 'leg': '1', 'name': 'D1'})
    old_log, new_log = store.log.path, tmp_path / 'usb' / 'C1.sqlite'
    page = CruisesPage(store)
    asked = []
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: asked.append(a[2]) or YES)
    _edit_cruise(monkeypatch, page, store, cruise, new_log, name='C1 renamed', end='2026-10-25')
    assert 'Move the log file' in asked[0]
    assert new_log.is_file() and not old_log.exists()
    assert store.log.path == new_log  # still the current cruise, at its new location
    assert store.cruise['name'] == 'C1 renamed' and store.cruise['end_date'] == '2026-10-25'
    assert store.log.rows('dives')[0]['cruise_name'] == 'C1 renamed'
    assert Settings.load().cruise(cruise)['log'] == str(new_log)
    assert page.table.item(0, 1).text() == 'C1 renamed'


def test_declining_the_move_keeps_the_log_where_it_is(store, cruise, monkeypatch, tmp_path):
    old_log = store.log.path
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: NO)
    _edit_cruise(monkeypatch, CruisesPage(store), store, cruise, tmp_path / 'usb' / 'C1.sqlite', objective='New')
    assert store.log.path == old_log and old_log.is_file()
    assert store.cruise['objective'] == 'New'  # the other changes are saved
    assert Settings.load().cruise(cruise)['log'] == str(old_log)


def test_a_failed_move_keeps_the_log_where_it_is(store, cruise, monkeypatch, tmp_path):
    old_log = store.log.path
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: YES)
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: warnings.append(a[2]))

    def fail(*args):
        raise OSError('device not ready')
    monkeypatch.setattr(shutil, 'move', fail)
    _edit_cruise(monkeypatch, CruisesPage(store), store, cruise, tmp_path / 'usb' / 'C1.sqlite')
    assert 'could not be moved' in warnings[0]
    assert store.log is not None and store.log.path == old_log and old_log.is_file()
    assert Settings.load().cruise(cruise)['log'] == str(old_log)


def test_a_missing_log_can_be_located(store, cruise, monkeypatch, tmp_path):
    old_log = store.log.path
    store.close_cruise()
    moved = tmp_path / 'moved.sqlite'
    shutil.move(str(old_log), str(moved))
    page = CruisesPage(store)
    assert page.table.item(0, 6).text().endswith('(not found)')
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: YES)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a, **k: (str(moved), ''))
    page.table.selectRow(0)
    page.select()
    assert store.log.path == moved and store.cruise_id == cruise


def test_opening_a_log_from_elsewhere(store, tmp_path, monkeypatch):
    copy = tmp_path / 'shiny.sqlite'
    shutil.copy(SHINY_LOG, copy)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a, **k: (str(copy), ''))
    page = CruisesPage(store)
    page.open_log()
    page.open_log()  # not added twice
    assert len(store.settings.cruises) == 1
    assert store.cruise['name'] == 'C1' and store.log.path == copy
    assert 'start_date' in store.cruise  # upgraded


def test_removing_a_cruise_keeps_its_log(store, cruise, monkeypatch):
    log = store.log.path
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: YES)
    page = CruisesPage(store)
    page.table.selectRow(0)
    page.remove()
    assert store.settings.cruises == [] and store.log is None and log.is_file()


# Forms

def test_equipconfig_form_chooses_instruments_or_subs(store, cruise):
    _fill_setup(store)
    form = EquipconfigForm(store)
    assert _choices(form.equipment) == ['Compass (12345)', 'Main camera (4830543)', 'ROWETech DVL (123456) [retired]']
    form.type.set_value('platform')
    assert _choices(form.equipment) == ['Delta', 'Phantom (428)']  # no ships: the ship is the cruise's
    form.equipment.set_value(202)
    form.name.setText('cam')  # already used
    assert not form.submit.isEnabled()
    form.name.setText('rov')
    assert form.submit.isEnabled()
    form.variable.set_value('pan')
    form.value.setText('10')
    form.add.click()
    assert form.values() == {'name': 'rov', 'type': 'platform', 'instrument_id': None, 'platform_id': 202,
                             'configuration': "{'pan':10}", 'note': ''}

    edit = EquipconfigForm(store, row=store.log.rows('equipconfig')[0])
    assert edit.equipment.currentText() == 'Phantom (428)'
    old = EquipconfigForm(store, row={'row_id': 'x', 'name': 'old', 'instrument_id': 999, 'type': 'instrument'})
    assert old.equipment.currentText() == 'Unknown instrument (ID 999)' and old.values()['instrument_id'] == 999


def test_diveconfig_form_has_no_ship(store, cruise):
    _fill_setup(store)
    form = DiveconfigForm(store)
    assert not hasattr(form, 'ship')
    form.name.setText('dc3')
    form.sub.set_value('phantom')
    form.ship_instruments.set_value(['cam'])
    assert not form.submit.isEnabled()
    form.sub_instruments.set_value(['cam'])
    assert form.submit.isEnabled()
    assert form.values()['ship_config'] == '' and form.values()['sub_config'] == 'phantom'


def test_dive_form_records_the_current_cruise(store, cruise, monkeypatch):
    _fill_setup(store)
    form = DiveForm(store)
    assert not hasattr(form, 'cruise_name') and not hasattr(form, 'leg')
    form.name.setText('D1')
    form.pilot.set_value(['7', '9'])
    form.start.button.click()
    assert parse_time(form.start.value()) is not None
    form.end.set_value('not a time')
    assert not form.submit.isEnabled()
    form.end.set_value('2099-01-01T00:00:00Z')
    assert form.submit.isEnabled()
    values = form.values()
    assert (values['cruise_name'], values['leg'], values['pilot']) == ('C1', '1', '7;9')

    # Add a transect from inside the dive form; the dive form keeps its values
    def fill_transect(self):
        assert (self.dive_name.value(), self.name.value()) == ('D1', 'D1_1')
        self.start.button.click()
        self.end.button.click()
        return True
    monkeypatch.setattr(TransectForm, 'exec', fill_transect)
    form.add_transect.click()
    assert form.transects.text() == 'Transects: D1_1' and form.name.value() == 'D1'
    assert store.log.rows('transects')[0]['cruise_name'] == 'C1'


def _save(store, form_class, table, fill, row=None):
    """Save a form through a table page, as the user would."""
    def run(form):
        fill(form)
        return True
    page = TablePage(store, table, table, [('Name', lambda r: r['name'])], form_class)
    form_class.exec = run
    try:
        if row is None:
            page.add()
        else:
            page.table.selectRow([r['row_id'] for r in page.rows].index(row['row_id']))
            page.edit()
    finally:
        del form_class.exec


def _dive(name, config):
    def fill(form):
        form.name.setText(name)
        form.dive_config.set_value(config)
        form.pilot.set_value(['7'])
        form.start.set_value('2026-10-23T10:00:00Z')
        form.end.set_value('2026-10-23T11:00:00Z')
    return fill


def test_new_dives_use_the_last_used_dive_config(store, cruise):
    _fill_setup(store)
    assert DiveForm(store).dive_config.value() == 'dc2'  # nothing used yet: the newest
    _save(store, DiveForm, 'dives', _dive('D1', 'dc1'))
    assert DiveForm(store).dive_config.value() == 'dc1'
    assert Settings.load().cruise(cruise)['last_dive_config'] == 'dc1'


def test_new_transects_use_the_last_used_dive(store, cruise):
    _fill_setup(store)
    _save(store, DiveForm, 'dives', _dive('D1', 'dc1'))
    _save(store, DiveForm, 'dives', _dive('D2', 'dc1'))
    _save(store, DiveForm, 'dives', _dive('D3', 'dc1'))
    # Editing D1 makes it the last used
    _save(store, DiveForm, 'dives', lambda f: f.summary.setText('edited'), row=store.log.rows('dives')[0])
    form = TransectForm(store)  # raised from the transect list
    assert (form.dive_name.value(), form.name.value()) == ('D1', 'D1_1')
    form.dive_name.set_value('D2')
    assert form.name.value() == 'D2_1'  # the suggested name follows the dive

    def transect(form):
        form.dive_name.set_value('D3')
        form.start.set_value('2026-10-23T10:10:00Z')
        form.end.set_value('2026-10-23T10:20:00Z')
    _save(store, TransectForm, 'transects', transect)
    assert TransectForm(store).dive_name.value() == 'D3'


def test_table_page_add_edit_delete(store, cruise, monkeypatch):
    page = TablePage(store, 'Dive configurations', 'diveconfig', [('Name', lambda r: r['name']),
                                                                  ('Note', lambda r: r['note'])], DiveconfigForm)
    store.log.insert('equipconfig', {'name': 'rov', 'platform_id': 202, 'type': 'platform'})
    store.log.insert('equipconfig', {'name': 'cam', 'instrument_id': 101, 'type': 'instrument'})

    def fill(self):
        if not self.name.isReadOnly():
            self.name.setText('dc1')
        self.sub.set_value('rov')
        self.ship_instruments.set_value(['cam'])
        self.sub_instruments.set_value(['cam'])
        self.note.setText('First' if not self.name.isReadOnly() else 'Changed')
        return True
    monkeypatch.setattr(DiveconfigForm, 'exec', fill)
    page.add()
    assert page.table.rowCount() == 1 and page.table.item(0, 1).text() == 'First'
    page.table.selectRow(0)
    page.edit()
    assert store.log.rows('diveconfig')[0]['note'] == 'Changed'
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: YES)
    page.table.selectRow(0)
    page.delete()
    assert store.log.rows('diveconfig') == [] and page.table.rowCount() == 0


def _enabled(item):
    return bool(item.flags() & Qt.ItemFlag.ItemIsEnabled)


def test_log_pages_are_disabled_without_a_cruise(store):
    window = MainWindow(store, store.settings)
    disabled = {window.nav.item(i).text() for i in range(window.nav.count()) if not _enabled(window.nav.item(i))}
    assert disabled == {'Equipment configurations', 'Dive configurations', 'Dives', 'Transects', 'Checks'}
    assert not window.export_action.isEnabled()
    store.create_cruise(CRUISE, store.default_log_path('C1', '1'))
    assert all(_enabled(window.nav.item(i)) for i in range(window.nav.count()))
    assert window.windowTitle().startswith('C1 leg 1')
    window.close()


def test_checks_page(store, cruise, tmp_path):
    _fill_setup(store)
    store.log.insert('dives', {'name': 'D1', 'pilot': '7;9', 'start_time': '2026-10-23T10:00:00Z',
                               'end_time': '2026-10-23T11:30:00Z'})
    store.log.insert('dives', {'name': 'D2', 'pilot': '7', 'start_time': '2026-10-23T-13:00:00Z',  # Shiny format
                               'end_time': '2026-10-23T-13:45:00Z'})
    store.log.insert('transects', {'dive_name': 'D1', 'name': 'D1_1', 'start_time': '2026-10-23T10:10:00Z',
                                   'end_time': '2026-10-23T10:40:00Z'})
    store.log.insert('transects', {'dive_name': 'D9', 'name': 'D9_1', 'start_time': 'bad', 'end_time': ''})
    page = ChecksPage(store)
    page.resize(1100, 900)
    assert page.totals['dives'].value.text() == '2'
    assert page.dive_lengths.items == [('D1', 90.0), ('D2', 45.0)]
    assert dict(page.pilot_hours.items) == {'Jackie Doe, Stacey Ray': 1.5, 'Jackie Doe': 0.75}
    assert len(page.timeline.dives) == 2
    text = page.warnings.text()
    assert 'Missing dives</b>: D9' in text and 'Unreadable times</b>: D9_1' in text
    page.grab().save(str(tmp_path / 'checks.png'))


def test_warnings_escape_names():
    html = warnings_html([{'name': '<b>x</b>', 'start_time': '', 'end_time': ''}] * 2, [])
    assert '&lt;b&gt;x&lt;/b&gt;' in html


def test_main_window_update_and_second_copy(store, api, monkeypatch):
    window = MainWindow(store, store.settings)
    messages = []
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: messages.append(a[1]))
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: messages.append(a[1]))

    def wait():
        for _ in range(100):
            if messages:
                return
            QTest.qWait(50)
    window.update_lookups()
    wait()
    assert messages == ['Lookups updated']
    assert 'lookups updated' in window.status.text()

    api.fail = '/api/v2/rov/platforms/'
    messages.clear()
    window.update_lookups()
    wait()
    assert messages == ['Lookups not updated']
    assert len(store.lookups.platforms()) == 3

    # A second copy of the app can't run
    with pytest.raises(AlreadyOpenError):
        Store(store.settings)
    window.close()


def test_reopens_the_last_cruise(store, cruise, monkeypatch):
    store.close_cruise()
    window = MainWindow(store, store.settings)
    window.reopen_last_cruise()
    assert store.cruise_id == cruise
    assert window.nav.currentItem().text() == 'Dives'
    window.close()


def test_home_is_the_test_folder(home):
    assert home_dir() == home and cruises_module  # the tests never touch the real home
