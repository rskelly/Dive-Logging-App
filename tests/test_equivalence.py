"""Compatibility with the earlier R Shiny version of the app.

tests/fixtures/shiny/ holds what the Shiny app wrote for a scripted session: its
log, lookups and export. The Shiny app has been removed, so these files are a
fixed reference. These tests check that its logs still open and export, and run
the same session through this app's forms and compare what both record.

What's compared: the Shiny columns (this app adds columns at the end of some
tables), with row_ids ignored, times compared as times, and NA equal to an empty
field. The ship and subs are now platforms from the lookups rather than
equipment configs, so platform configs and diveconfig.ship_config aren't compared.
"""

import csv
import shutil
import sqlite3
from pathlib import Path

import pytest

from divelog.db import LogDB
from divelog.export import export_all
from divelog.formats import parse_time
from divelog.lookups import Lookups, create_lookups_db, update_lookups
from divelog.settings import Settings
from divelog.store import Store
from divelog.ui.forms import DiveconfigForm, DiveForm, EquipconfigForm, TransectForm

SHINY = Path(__file__).parent / 'fixtures' / 'shiny'
TIME_COLUMNS = {'start_time', 'end_time'}


def _schema(path):
    con = sqlite3.connect(path)
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
    return {t: [(r[1], r[2]) for r in con.execute(f'PRAGMA table_info({t})')] for t in tables}


def _normal(column, value):
    """Compare values the way the output contract allows."""
    if value in (None, 'NA'):
        return ''
    if column in TIME_COLUMNS and parse_time(str(value)):
        return parse_time(str(value))
    return str(value)


def _comparable(table, rows, columns):
    """Rows reduced to what both versions record."""
    if table == 'equipconfig':
        rows = [r for r in rows if r['type'] == 'instrument']
    columns = [c for c in columns if c not in ('row_id', 'ship_config')]
    return sorted(({c: _normal(c, r[c]) for c in columns} for r in rows), key=str)


def _csv(path):
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def test_shiny_columns_come_first(tmp_path):
    LogDB(tmp_path / 'log.sqlite').close()
    create_lookups_db(tmp_path / 'lookups.sqlite')
    for ours, shiny in [(tmp_path / 'log.sqlite', SHINY / 'divelogging-db.sqlite'),
                        (tmp_path / 'lookups.sqlite', SHINY / 'lookups.sqlite')]:
        ours, shiny = _schema(ours), _schema(shiny)
        for table, columns in shiny.items():
            assert ours[table][:len(columns)] == columns, table


def run_session(store):
    """The session the Shiny fixtures were made with, through this app's forms:
    cruise C1 leg 1, equipment configs, a dive config, dives D1-D3 with a
    transect on D1, D2 edited (summary), D3 deleted."""
    store.create_cruise({'name': 'C1', 'leg': '1', 'objective': 'Survey', 'start_date': '2026-10-23',
                         'end_date': '2026-10-23', 'ship_id': 201}, store.default_log_path('C1', '1'))

    for name, kind, equipment, config in [('phantom', 'platform', 202, '{}'),
                                          ('cam', 'instrument', 101, "{'pan':10, 'tilt':-5.5}")]:
        form = EquipconfigForm(store)
        form.name.setText(name); form.type.set_value(kind); form.equipment.set_value(equipment)
        form.configuration.setText(config)
        store.log.insert('equipconfig', form.values())

    form = DiveconfigForm(store)
    form.name.setText('dc1'); form.sub.set_value('phantom')
    form.ship_instruments.set_value(['cam']); form.sub_instruments.set_value(['cam'])
    store.log.insert('diveconfig', form.values())

    def dive(name, pilots, start, end, site='', summary='', row=None):
        form = DiveForm(store, row=row)
        form.name.setText(name); form.pilot.set_value(pilots)
        form.start.set_value(start); form.end.set_value(end)
        form.site_name.setText(site); form.summary.setText(summary)
        assert form.submit.isEnabled()
        return form

    store.log.insert('dives', dive('D1', ['7', '9'], '2026-10-23T10:00:00Z', '2026-10-23T11:30:00Z', site='Hecate').values())
    form = TransectForm(store)
    assert form.dive_name.value() == 'D1' and form.name.value() == 'D1_1'
    form.start.set_value('2026-10-23T10:10:00Z'); form.end.set_value('2026-10-23T10:40:00Z')
    store.log.insert('transects', form.values())
    store.log.insert('dives', dive('D2', ['7'], '2026-10-23T13:00:00Z', '2026-10-23T13:45:00Z').values())
    store.log.insert('dives', dive('D3', ['9'], '2026-10-23T15:00:00Z', '2026-10-23T15:30:00Z').values())

    d2, d3 = store.log.rows('dives')[1:]
    form = dive('D2', ['7'], '2026-10-23T13:00:00Z', '2026-10-23T13:45:00Z', summary='edited', row=d2)
    store.log.update('dives', d2['row_id'], {c: form.values()[c] for c in DiveForm.EDITABLE})
    store.log.delete('dives', d3['row_id'])


@pytest.fixture
def session(qapp, home, api):
    """The session's store and export from this app."""
    settings = Settings(api_url=api.url)
    store = Store(settings)
    update_lookups(settings.lookups_path, api.url)
    run_session(store)
    folder = export_all(store.log, store.lookups, store.export_path)
    yield store, folder
    store.close()


def test_same_session_records_the_same(session):
    store = session[0]
    # Read-only: opening the fixture with LogDB would add the new columns to it
    con = sqlite3.connect(f'file:{SHINY / "divelogging-db.sqlite"}?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    for table in ('cruise', 'dives', 'transects', 'equipconfig', 'diveconfig'):
        shiny_rows = [dict(r) for r in con.execute(f'SELECT * FROM {table}')]
        columns = list(shiny_rows[0])
        assert _comparable(table, store.log.rows(table), columns) == _comparable(table, shiny_rows, columns), table


def test_same_session_exports_the_same(session):
    folder = session[1]
    for path in sorted((SHINY / 'export').iterdir()):
        table = path.name.split('_', 1)[1][:-4]
        columns, rows = _csv(folder / path.name)
        shiny_columns, shiny_rows = _csv(path)
        assert columns[:len(shiny_columns)] == shiny_columns, path.name
        assert _comparable(table, rows, shiny_columns) == _comparable(table, shiny_rows, shiny_columns), path.name
    assert (folder / 'C1_platforms.csv').exists()


def test_a_shiny_log_opens_and_exports(tmp_path):
    for name in ('divelogging-db.sqlite', 'lookups.sqlite'):
        shutil.copy(SHINY / name, tmp_path / name)
    log, lookups = LogDB(tmp_path / 'divelogging-db.sqlite'), Lookups(tmp_path / 'lookups.sqlite')
    folder = export_all(log, lookups, tmp_path / 'Exports')
    for path in (SHINY / 'export').iterdir():
        columns, rows = _csv(folder / path.name)
        shiny_columns, shiny_rows = _csv(path)
        assert columns[:len(shiny_columns)] == shiny_columns
        # Same log: everything compares, platform configs included (lookups may be in another order)
        assert (sorted(({c: _normal(c, r[c]) for c in shiny_columns} for r in rows), key=str)
                == sorted(({c: _normal(c, r[c]) for c in shiny_columns} for r in shiny_rows), key=str)), path.name
    assert all(parse_time(d['start_time']) for d in log.rows('dives'))  # legacy T- times
    log.close()
    lookups.close()
