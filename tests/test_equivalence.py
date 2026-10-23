"""Compatibility with the earlier R Shiny version of the app.

tests/fixtures/shiny/ holds what the Shiny app wrote for a scripted session: its
log, lookups and export. The Shiny app has been removed, so these files are a
fixed reference. These tests run the same session (run_session) through the
desktop app's forms and compare, and check that the desktop app can open and
export a Shiny log. Byte-identical output isn't required (WINDOWS_APP_PLAN.md,
section 1): row_ids differ, times are compared as times, and NA equals an empty field.
"""

import csv
import shutil
import sqlite3
from pathlib import Path

import pytest

from divelog.db import TABLES, LogDB
from divelog.export import export_all
from divelog.formats import parse_time
from divelog.lookups import Lookups, create_lookups_db, update_lookups
from divelog.ui.forms import CruiseForm, DiveconfigForm, DiveForm, EquipconfigForm, TransectForm

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


def _table(rows, columns):
    return [{c: _normal(c, r[c]) for c in columns if c != 'row_id'} for r in rows]


def _csv(path):
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def run_session(store_log, lookups):
    """The session the Shiny fixtures were made with, through the desktop app's forms:
    a cruise, three equipment configs, a dive config, dives D1-D3 with a transect on D1,
    D2 edited (summary), D3 deleted."""
    store = type('Store', (), {'log': store_log, 'lookups': lookups, 'config_variables': [], 'notify': lambda self: None})()

    form = CruiseForm(store)
    form.name.setText('C1'); form.leg.setText('1'); form.objective.setText('Survey')
    store.log.insert('cruise', form.values())

    for name, instrument, kind, config in [('phantom', 103, 'platform', '{}'), ('vector', 103, 'platform', '{}'),
                                           ('cam', 101, 'instrument', "{'pan':10, 'tilt':-5.5}")]:
        form = EquipconfigForm(store)
        form.name.setText(name); form.instrument.set_value(instrument); form.type.set_value(kind)
        form.configuration.setText(config)
        store.log.insert('equipconfig', form.values())

    form = DiveconfigForm(store)
    form.name.setText('dc1'); form.ship.set_value('vector'); form.sub.set_value('phantom')
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
def desktop(qapp, tmp_path, api):
    """The session's log, lookups and export from the desktop app."""
    create_lookups_db(tmp_path / 'lookups.sqlite')
    update_lookups(tmp_path / 'lookups.sqlite', api.url)
    log, lookups = LogDB(tmp_path / 'log.sqlite'), Lookups(tmp_path / 'lookups.sqlite')
    run_session(log, lookups)
    folder = export_all(log, lookups, tmp_path / 'Exports')
    yield log, lookups, folder
    log.close()
    lookups.close()


def test_schemas_match(tmp_path):
    LogDB(tmp_path / 'log.sqlite').close()
    create_lookups_db(tmp_path / 'lookups.sqlite')
    assert _schema(tmp_path / 'log.sqlite') == _schema(SHINY / 'divelogging-db.sqlite')
    assert _schema(tmp_path / 'lookups.sqlite') == _schema(SHINY / 'lookups.sqlite')


def test_same_session_gives_the_same_log(desktop):
    log = desktop[0]
    shiny = LogDB(SHINY / 'divelogging-db.sqlite')
    try:
        for table, columns in TABLES.items():
            assert _table(log.rows(table), columns) == _table(shiny.rows(table), columns), table
    finally:
        shiny.close()


def test_same_session_gives_the_same_export(desktop):
    folder = desktop[2]
    shiny_files = sorted(p.name for p in (SHINY / 'export').iterdir())
    assert sorted(p.name for p in folder.iterdir()) == shiny_files
    for name in shiny_files:
        columns, rows = _csv(folder / name)
        shiny_columns, shiny_rows = _csv(SHINY / 'export' / name)
        assert columns == shiny_columns, name
        key = (lambda r: r['id']) if 'id' in columns else (lambda r: 0)  # lookups may be ordered differently
        assert sorted(_table(rows, columns), key=str) == sorted(_table(shiny_rows, columns), key=str), name
        assert key


def test_desktop_app_reads_and_exports_a_shiny_log(tmp_path):
    for name in ('divelogging-db.sqlite', 'lookups.sqlite'):
        shutil.copy(SHINY / name, tmp_path / name)
    log, lookups = LogDB(tmp_path / 'divelogging-db.sqlite'), Lookups(tmp_path / 'lookups.sqlite')
    folder = export_all(log, lookups, tmp_path / 'Exports')
    for path in (SHINY / 'export').iterdir():
        columns, rows = _csv(folder / path.name)
        assert sorted(_table(rows, columns), key=str) == sorted(_table(_csv(path)[1], columns), key=str), path.name
    # Legacy T- times are read
    assert all(parse_time(d['start_time']) for d in log.rows('dives'))
    log.close()
    lookups.close()
