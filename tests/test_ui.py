"""The forms, pages and main window, driven offscreen."""

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from divelog.formats import parse_time
from divelog.lookups import update_lookups
from divelog.store import AlreadyOpenError, Store
from divelog.ui.forms import CruiseForm, DiveconfigForm, DiveForm, EquipconfigForm, TransectForm
from divelog.ui.main_window import MainWindow
from divelog.ui.pages import ChecksPage, TablePage, warnings_html


@pytest.fixture
def store(qapp, tmp_path, api):
    store = Store(tmp_path / 'data')
    update_lookups(store.lookups_path, api.url)
    yield store
    store.close()


def _fill_setup(store):
    """A cruise, three equipment configs and a dive config, as saved by the forms."""
    store.log.insert('cruise', {'name': 'C1', 'leg': '1', 'objective': 'Survey'})
    store.log.insert('equipconfig', {'name': 'phantom', 'instrument_id': 103, 'type': 'platform', 'configuration': '{}'})
    store.log.insert('equipconfig', {'name': 'vector', 'instrument_id': 103, 'type': 'platform', 'configuration': '{}'})
    store.log.insert('equipconfig', {'name': 'cam', 'instrument_id': 101, 'type': 'instrument', 'configuration': "{'pan':10}"})
    store.log.insert('diveconfig', {'name': 'dc1', 'ship_config': 'vector', 'sub_config': 'phantom',
                                    'ship_instrument_configs': 'cam', 'sub_instrument_configs': 'cam'})


def test_cruise_form_requires_fields(store):
    form = CruiseForm(store)
    form.validate()
    assert not form.submit.isEnabled()
    form.name.setText('C1')
    form.leg.setText('1')
    assert not form.submit.isEnabled()
    form.objective.setText('Survey')
    assert form.submit.isEnabled()
    assert form.values() == {'name': 'C1', 'leg': '1', 'objective': 'Survey', 'summary': '', 'note': ''}

    edit = CruiseForm(store, row={'row_id': 'x', **form.values()})
    assert edit.name.isReadOnly() and edit.leg.isReadOnly()


def test_equipconfig_form(store):
    _fill_setup(store)
    form = EquipconfigForm(store)
    assert [form.instrument.itemText(i) for i in range(form.instrument.count())] == [
        'Compass (12345)', 'Main camera (4830543)', 'ROWETech DVL (123456) [retired]']
    form.instrument.set_value(101)
    form.name.setText('cam')  # already used
    form.validate()
    assert not form.submit.isEnabled()
    form.name.setText('cam2')
    assert form.submit.isEnabled()

    assert not form.add.isEnabled()
    form.variable.set_value('pan')
    form.value.setText('10')
    form.add.click()
    form.variable.set_value('tilt')
    form.value.setText('-5.5')
    form.add.click()
    assert form.values() == {'name': 'cam2', 'instrument_id': 101, 'type': 'instrument',
                             'configuration': "{'pan':10, 'tilt':-5.5}", 'note': ''}


def test_editing_keeps_an_instrument_missing_from_the_lookups(store):
    form = EquipconfigForm(store, row={'row_id': 'x', 'name': 'old', 'instrument_id': 999, 'type': 'instrument',
                                       'configuration': '{}', 'note': ''})
    assert form.values()['instrument_id'] == 999
    assert form.instrument.currentText() == 'Unknown instrument (ID 999)'


def test_diveconfig_form(store):
    _fill_setup(store)
    form = DiveconfigForm(store)
    assert [form.ship.itemText(i) for i in range(form.ship.count())] == ['phantom', 'vector']
    form.name.setText('dc2')
    form.ship.set_value('vector')
    form.sub.set_value('phantom')
    form.ship_instruments.set_value(['cam'])
    form.validate()
    assert not form.submit.isEnabled()  # sub instruments missing
    form.sub_instruments.set_value(['cam'])
    assert form.submit.isEnabled()
    assert form.values()['sub_instrument_configs'] == 'cam'


def test_dive_form_with_transects(store, monkeypatch):
    _fill_setup(store)
    form = DiveForm(store)
    # Defaults: the last cruise and dive configuration
    assert (form.cruise_name.value(), form.leg.value(), form.dive_config.value()) == ('C1', '1', 'dc1')
    form.name.setText('D1')
    form.pilot.set_value(['7', '9'])
    form.start.button.click()
    assert parse_time(form.start.value()) is not None
    form.end.set_value('not a time')
    assert not form.submit.isEnabled()
    form.end.set_value('2099-01-01T00:00:00Z')
    assert form.submit.isEnabled()

    # Add a transect from inside the dive form; the dive form keeps its values
    def fill_transect(self):
        assert (self.dive_name.value(), self.name.value(), self.cruise_name.value()) == ('D1', 'D1_1', 'C1')
        self.start.button.click()
        self.end.button.click()
        return True
    monkeypatch.setattr(TransectForm, 'exec', fill_transect)
    form.add_transect.click()
    assert form.transects.text() == 'Transects: D1_1'
    assert form.name.value() == 'D1'
    assert TransectForm(store, dive={'cruise_name': 'C1', 'leg': '1', 'name': 'D1'}).name.value() == 'D1_2'

    values = form.values()
    assert values['pilot'] == '7;9' and values['dive_config'] == 'dc1'


def test_dive_names_must_be_unique(store):
    _fill_setup(store)
    store.log.insert('dives', {'cruise_name': 'C1', 'leg': '1', 'name': 'D1', 'pilot': '7', 'dive_config': 'dc1',
                               'start_time': '2026-10-23T10:00:00Z', 'end_time': '2026-10-23T11:00:00Z'})
    form = DiveForm(store)
    form.pilot.set_value(['7'])
    form.start.set_value('2026-10-23T12:00:00Z')
    form.end.set_value('2026-10-23T13:00:00Z')
    form.name.setText('D1')
    assert not form.submit.isEnabled()
    form.name.setText('D2')
    assert form.submit.isEnabled()
    # Editing a dive may keep its own name
    edit = DiveForm(store, row=store.log.rows('dives')[0])
    edit.validate()
    assert edit.submit.isEnabled()


def test_table_page_add_edit_delete(store, monkeypatch):
    page = TablePage(store, 'Cruise', 'cruise', [('Name', lambda r: r['name']), ('Objective', lambda r: r['objective'])],
                     CruiseForm)

    def fill(self):
        if not self.name.isReadOnly():
            self.name.setText('C1')
            self.leg.setText('1')
        self.objective.setText('First' if not self.name.isReadOnly() else 'Changed')
        return True
    monkeypatch.setattr(CruiseForm, 'exec', fill)
    page.add()
    assert page.table.rowCount() == 1 and page.table.item(0, 1).text() == 'First'

    page.table.selectRow(0)
    page.edit()
    assert store.log.rows('cruise')[0]['objective'] == 'Changed'

    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: QMessageBox.StandardButton.Yes)
    page.table.selectRow(0)
    page.delete()
    assert store.log.rows('cruise') == [] and page.table.rowCount() == 0


def test_checks_page(store, tmp_path):
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


def test_main_window_update_and_second_copy(qapp, tmp_path, api, monkeypatch):
    from divelog.settings import Settings
    store = Store(tmp_path / 'data')
    window = MainWindow(store, Settings(api_url=api.url, data_dir=str(tmp_path / 'data')))
    messages = []
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: messages.append(a[1]))
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: messages.append(a[1]))
    window.update_lookups()
    for _ in range(100):
        if messages:
            break
        QTest.qWait(50)
    assert messages == ['Lookups updated']
    assert 'lookups updated' in window.status.text()

    api.fail = '/api/v2/shared/people/'
    messages.clear()
    window.update_lookups()
    for _ in range(100):
        if messages:
            break
        QTest.qWait(50)
    assert messages == ['Lookups not updated']
    assert len(store.lookups.people()) == 2

    # A second copy can't open the same data folder
    with pytest.raises(AlreadyOpenError):
        Store(tmp_path / 'data')
    window.close()
    store.close()
    Store(tmp_path / 'data').close()  # free again once closed


def test_new_survey_sets_the_log_aside(qapp, tmp_path, monkeypatch):
    from divelog.settings import Settings
    store = Store(tmp_path / 'data')
    store.log.insert('cruise', {'name': 'C1', 'leg': '1', 'objective': 'x'})
    window = MainWindow(store, Settings(data_dir=str(tmp_path / 'data')))
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: None)
    window.new_survey()
    assert store.log.rows('cruise') == []
    kept = [p.name for p in (tmp_path / 'data').glob('divelogging-db_C1_*.sqlite')]
    assert len(kept) == 1
    window.close()
    store.close()
