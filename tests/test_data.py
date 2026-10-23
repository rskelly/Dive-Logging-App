"""The data layer: formats, log db, lookups and export."""

import csv
import sqlite3
from datetime import date, datetime, timezone

import pytest

from divelog.db import TABLES, LogDB, LogExistsError, OldLogError, create_log_db, read_cruise
from divelog.export import export_all
from divelog.formats import (TIME_FORMAT, build_config, duration, format_number, join_ids, now_utc,
                             parse_config, parse_time, split_ids)
from divelog.lookups import (LookupsError, Lookups, create_lookups_db, describe_error, instrument_label,
                             person_label, platform_label, update_lookups)


# Formats

def test_times_are_iso_8601_and_legacy_times_still_read():
    assert datetime.strptime(now_utc(), TIME_FORMAT)
    expected = datetime(2026, 10, 23, 19, 46, 23, tzinfo=timezone.utc)
    assert parse_time('2026-10-23T19:46:23Z') == expected
    assert parse_time('2026-10-23T-19:46:23Z') == expected  # written by the Shiny app
    assert parse_time('') is None and parse_time('23/10/2026') is None
    assert duration('2026-10-23T10:00:00Z', '2026-10-23T-11:30:00Z') == 90


def test_config_strings():
    assert build_config([]) == '{}'
    pairs = [('pan', '10'), ('tilt', '-5.5')]
    assert build_config(pairs) == "{'pan':10, 'tilt':-5.5}"
    assert parse_config("{'pan':10, 'tilt':-5.5}") == pairs
    assert parse_config("{'pan': 10 ,'tilt':-5.5}") == pairs
    assert [format_number(v) for v in ('10', '10.0', '0.5', '-3')] == ['10', '10', '0.5', '-3']


def test_id_lists():
    assert join_ids([7, 9]) == '7;9'
    assert split_ids('7;9') == ['7', '9'] and split_ids('') == [] and split_ids(None) == []


# Log db

def test_log_schema(tmp_path):
    path = tmp_path / 'log.sqlite'
    create_log_db(path)
    con = sqlite3.connect(path)
    for table, columns in TABLES.items():
        info = con.execute(f'PRAGMA table_info({table})').fetchall()
        assert [r[1] for r in info] == columns
        types = {r[1]: r[2] for r in info}
        assert all(types[c] == ('INTEGER' if c.endswith('_id') and c != 'row_id' else 'TEXT') for c in columns)
    create_log_db(path)  # again: no change, no error


def test_older_logs_get_the_new_columns(tmp_path):
    path = tmp_path / 'old.sqlite'
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE cruise (row_id TEXT, name TEXT, leg TEXT, objective TEXT, summary TEXT, note TEXT)')
    con.execute("INSERT INTO cruise VALUES ('x', 'C1', '1', 'o', '', '')")
    con.execute('CREATE TABLE equipconfig (row_id TEXT, name TEXT, instrument_id INTEGER, type TEXT, '
                'configuration TEXT, note TEXT)')
    con.commit()
    con.close()
    log = LogDB(path)
    assert log.cruise() == {'row_id': 'x', 'name': 'C1', 'leg': '1', 'objective': 'o', 'summary': '', 'note': '',
                            'start_date': None, 'end_date': None, 'ship_id': None}
    assert [r[1] for r in log.con.execute('PRAGMA table_info(equipconfig)')][-1] == 'platform_id'


def test_renaming_the_cruise_renames_it_in_dives_and_transects(tmp_path):
    log = LogDB.create(tmp_path / 'log.sqlite', {'name': 'C1', 'leg': '1'})
    log.insert('dives', {'cruise_name': 'C1', 'leg': '1', 'name': 'D1'})
    log.insert('dives', {'cruise_name': 'Other', 'leg': '2', 'name': 'D2'})  # e.g. a Shiny log with two legs
    log.insert('transects', {'cruise_name': 'C1', 'leg': '1', 'name': 'T1'})
    log.set_cruise({'name': 'C1b', 'leg': '1', 'start_date': '2026-10-01'})
    assert log.cruise()['name'] == 'C1b' and log.cruise()['start_date'] == '2026-10-01'
    assert [(d['cruise_name'], d['leg']) for d in log.rows('dives')] == [('C1b', '1'), ('Other', '2')]
    assert log.rows('transects')[0]['cruise_name'] == 'C1b'
    with pytest.raises(LogExistsError):
        LogDB.create(tmp_path / 'log.sqlite', {'name': 'C2'})


def test_read_cruise_does_not_change_the_file(tmp_path):
    path = tmp_path / 'log.sqlite'
    LogDB.create(path, {'name': 'C1', 'leg': '1'}).close()
    before = path.read_bytes()
    assert read_cruise(path)['name'] == 'C1'
    assert path.read_bytes() == before
    assert read_cruise(tmp_path / 'missing.sqlite') is None


def test_old_log_is_refused(tmp_path):
    path = tmp_path / 'old.sqlite'
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE equipconfig (row_id TEXT, short_code TEXT)')
    con.commit()
    con.close()
    with pytest.raises(OldLogError):
        create_log_db(path)


def test_log_crud(tmp_path):
    log = LogDB(tmp_path / 'log.sqlite')
    a = log.insert('cruise', {'name': 'C1', 'leg': '1', 'objective': 'x'})
    log.insert('cruise', {'name': 'C2', 'leg': '2', 'objective': 'y'})
    rows = log.rows('cruise')
    assert [r['name'] for r in rows] == ['C1', 'C2']
    assert rows[0]['summary'] == ''  # empty optional fields are '' as in the Shiny app
    log.update('cruise', a, {'objective': 'changed'})
    assert log.rows('cruise')[0]['objective'] == 'changed'
    with pytest.raises(KeyError):
        log.update('cruise', a, {'row_id': 'nope'})
    log.delete('cruise', a)
    assert [r['name'] for r in log.rows('cruise')] == ['C2']
    # Committed immediately: visible to another connection
    assert sqlite3.connect(tmp_path / 'log.sqlite').execute('SELECT count(*) FROM cruise').fetchone() == (1,)


# Lookups

def test_update_lookups_follows_pages(api, tmp_path):
    path = tmp_path / 'lookups.sqlite'
    create_lookups_db(path)
    assert update_lookups(path, api.url + '/') == {'people': 2, 'instruments': 3, 'platforms': 3}
    assert all(q['detail'] == ['ref'] for _, q in api.requests)
    lookups = Lookups(path)
    assert [person_label(p) for p in lookups.people()] == ['Jackie Doe', 'Stacey Ray']
    assert sorted(instrument_label(i) for i in lookups.instruments()) == [
        'Compass (12345)', 'Main camera (4830543)', 'ROWETech DVL (123456) [retired]']
    assert [platform_label(p) for p in lookups.ships()] == ['John P. Tully']
    assert [platform_label(p) for p in lookups.subs()] == ['Delta', 'Phantom (428)']
    info = lookups.info()
    assert info['source'] == api.url  # trailing slash removed
    assert datetime.strptime(info['updated_on'], '%Y-%m-%d %H:%M UTC')


def _snapshot(path):
    con = sqlite3.connect(path)
    return [con.execute(f'SELECT * FROM {t} ORDER BY 1').fetchall()
            for t in ('people', 'instruments', 'platforms', 'lookups_info')]


@pytest.mark.parametrize('failure', ['server error', 'unreachable', 'no instruments', 'no platforms'])
def test_failed_update_leaves_lookups_untouched(api, tmp_path, failure):
    path = tmp_path / 'lookups.sqlite'
    create_lookups_db(path)
    update_lookups(path, api.url)
    before = _snapshot(path)
    api.people = [{'id': 1, 'first_name': 'New', 'last_name': 'Person'}]  # would change the people
    url = api.url
    if failure == 'server error':
        api.fail = '/api/v2/rov/instruments/'  # the second endpoint fails
    elif failure == 'unreachable':
        url = 'http://127.0.0.1:9/api/v2'
    elif failure == 'no instruments':
        api.instruments = []
    else:
        api.platforms = []  # the last endpoint
    with pytest.raises(Exception) as error:
        update_lookups(path, url)
    assert _snapshot(path) == before
    assert describe_error(error.value)
    if failure.startswith('no '):
        assert isinstance(error.value, LookupsError)


def test_lookups_start_empty(tmp_path):
    lookups = Lookups(tmp_path / 'lookups.sqlite')
    assert lookups.info() is None and lookups.people() == [] and lookups.instruments() == []


# Export

def test_export(api, tmp_path):
    log = LogDB(tmp_path / 'log.sqlite')
    create_lookups_db(tmp_path / 'lookups.sqlite')
    update_lookups(tmp_path / 'lookups.sqlite', api.url)
    log.set_cruise({'name': 'PAC2026/01', 'leg': '1', 'objective': 'Survey, with "quotes"', 'start_date': '2026-10-01',
                    'end_date': '2026-10-20', 'ship_id': 201})
    log.insert('dives', {'name': 'D1', 'pilot': '7;9', 'start_time': '2026-10-23T10:00:00Z'})

    folder = export_all(log, Lookups(tmp_path / 'lookups.sqlite'), tmp_path / 'Exports', date(2026, 10, 23))
    assert folder == tmp_path / 'Exports' / '2026-10-23'
    names = sorted(p.name for p in folder.iterdir())
    assert names == sorted(f'PAC2026_01_{t}.csv' for t in [*TABLES, 'people', 'instruments', 'platforms'])

    raw = (folder / 'PAC2026_01_cruise.csv').read_bytes()
    assert raw.count(b'\r\n') == 2 and b'\n' not in raw.replace(b'\r\n', b'')
    with open(folder / 'PAC2026_01_cruise.csv', newline='', encoding='utf-8') as f:
        rows = list(csv.reader(f))
    assert rows[0] == TABLES['cruise']
    assert rows[1][1:] == ['PAC2026/01', '1', 'Survey, with "quotes"', '', '', '2026-10-01', '2026-10-20', '201']
    with open(folder / 'PAC2026_01_instruments.csv', newline='', encoding='utf-8') as f:
        instruments = {r['id']: r for r in csv.DictReader(f)}
    assert instruments['101']['retired'] == '' and instruments['102']['name'] == ''


def test_export_without_cruise(tmp_path):
    log = LogDB(tmp_path / 'log.sqlite')
    folder = export_all(log, Lookups(tmp_path / 'lookups.sqlite'), tmp_path / 'Exports')
    assert (folder / 'NA_dives.csv').exists()  # as the Shiny app names them
