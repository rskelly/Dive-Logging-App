"""Cruise logs: one SQLite file per cruise.

The tables start with the columns the earlier R Shiny version of the app created,
so its logs can still be opened; columns added since are at the end, and are
added to older logs when they're opened.
"""

import sqlite3
import uuid

# Columns of each table, in order. All are TEXT except the *_id columns.
# cruise has one row: the cruise the log belongs to. Its dates are YYYY-MM-DD and
# ship_id is a platform from the lookups.
# dives.pilot is a ';'-separated list of person IDs; the *_instrument_configs
# columns are ';'-separated lists of equipment config names. An equipment config
# is either an instrument (instrument_id) or a platform (platform_id).
# diveconfig.ship_config is only set in logs from the Shiny version: the ship is now the cruise's.
TABLES = {
    'cruise': ['row_id', 'name', 'leg', 'objective', 'summary', 'note', 'start_date', 'end_date', 'ship_id'],
    'dives': ['row_id', 'cruise_name', 'leg', 'name', 'pilot', 'start_time', 'end_time',
              'site_name', 'dive_config', 'objective', 'summary', 'note'],
    'transects': ['row_id', 'cruise_name', 'leg', 'dive_name', 'name', 'start_time', 'end_time',
                  'objective', 'summary', 'note'],
    'equipconfig': ['row_id', 'name', 'instrument_id', 'type', 'configuration', 'note', 'platform_id'],
    'diveconfig': ['row_id', 'name', 'ship_config', 'sub_config', 'ship_instrument_configs',
                   'sub_instrument_configs', 'note'],
}
INTEGER_COLUMNS = {('cruise', 'ship_id'), ('equipconfig', 'instrument_id'), ('equipconfig', 'platform_id')}


class OldLogError(Exception):
    """The log was written by a version of the app that used equipment short codes."""


class LogExistsError(Exception):
    """A new log would overwrite an existing file."""


def _type(table, column):
    return 'INTEGER' if (table, column) in INTEGER_COLUMNS else 'TEXT'


def create_log_db(path):
    """Create the log at path, or add any missing tables and columns.
    Raises OldLogError for a log that references equipment by short code."""
    con = sqlite3.connect(path)
    try:
        cols = [r[1] for r in con.execute('PRAGMA table_info(equipconfig)')]
        if cols and 'instrument_id' not in cols:
            raise OldLogError(f'"{path}" was created by an older version of the app '
                              '(equipment configurations use short codes).')
        with con:
            for table, columns in TABLES.items():
                existing = [r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]
                if not existing:
                    con.execute(f'CREATE TABLE "{table}" ('
                                + ', '.join(f'"{c}" {_type(table, c)}' for c in columns) + ')')
                for c in columns:
                    if existing and c not in existing:
                        con.execute(f'ALTER TABLE "{table}" ADD COLUMN "{c}" {_type(table, c)}')
    finally:
        con.close()


def read_cruise(path):
    """The cruise row of the log at path, without changing the file. None if
    the file is missing or unreadable."""
    try:
        con = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    except sqlite3.Error:
        return None
    try:
        con.row_factory = sqlite3.Row
        row = con.execute('SELECT * FROM cruise ORDER BY rowid LIMIT 1').fetchone()
        return dict(row) if row else None
    except sqlite3.Error:
        return None
    finally:
        con.close()


class LogDB:
    """Read and write a log's tables. Every write is committed immediately, so
    nothing is lost if the app is closed or crashes."""

    def __init__(self, path):
        create_log_db(path)
        self.path = path
        self.con = sqlite3.connect(path)
        self.con.row_factory = sqlite3.Row

    @classmethod
    def create(cls, path, cruise):
        """Create a new log at path for a cruise (a dict of cruise columns).
        Raises LogExistsError if the file exists."""
        if path.exists():
            raise LogExistsError(str(path))
        path.parent.mkdir(parents=True, exist_ok=True)
        log = cls(path)
        log.set_cruise(cruise)
        return log

    def close(self):
        self.con.close()

    def rows(self, table):
        """All rows of a table as dicts, in the order they were added."""
        cols = ', '.join(f'"{c}"' for c in TABLES[table])
        return [dict(r) for r in self.con.execute(f'SELECT {cols} FROM "{table}" ORDER BY rowid')]

    def insert(self, table, values):
        """Add a row with a new row_id. Returns the row_id."""
        row = {c: values.get(c, '') for c in TABLES[table]}
        row['row_id'] = str(uuid.uuid4())
        cols = ', '.join(f'"{c}"' for c in row)
        marks = ', '.join('?' for _ in row)
        with self.con:
            self.con.execute(f'INSERT INTO "{table}" ({cols}) VALUES ({marks})', list(row.values()))
        return row['row_id']

    def update(self, table, row_id, values):
        """Change some columns of a row."""
        for c in values:
            if c not in TABLES[table] or c == 'row_id':
                raise KeyError(c)
        sets = ', '.join(f'"{c}" = ?' for c in values)
        with self.con:
            self.con.execute(f'UPDATE "{table}" SET {sets} WHERE row_id = ?', [*values.values(), row_id])

    def delete(self, table, row_id):
        with self.con:
            self.con.execute(f'DELETE FROM "{table}" WHERE row_id = ?', [row_id])

    def cruise(self):
        """The log's cruise, or None. (Logs from the Shiny version may have more
        than one cruise row; the first is the log's cruise.)"""
        rows = self.rows('cruise')
        return rows[0] if rows else None

    def set_cruise(self, values):
        """Create or change the log's cruise. Renaming it renames the cruise in the
        dives and transects that used the old name and leg. Returns the row_id."""
        old = self.cruise()
        if old is None:
            return self.insert('cruise', values)
        values = {c: v for c, v in values.items() if c in TABLES['cruise'] and c != 'row_id'}
        sets = ', '.join(f'"{c}" = ?' for c in values)
        # One transaction: the cruise and the names in its dives and transects change together
        with self.con:
            self.con.execute(f'UPDATE cruise SET {sets} WHERE row_id = ?', [*values.values(), old['row_id']])
            new_name, new_leg = values.get('name', old['name']), values.get('leg', old['leg'])
            if (new_name, new_leg) != (old['name'], old['leg']):
                for table in ('dives', 'transects'):
                    self.con.execute(f'UPDATE "{table}" SET cruise_name = ?, leg = ? WHERE cruise_name = ? AND leg = ?',
                                     (new_name, new_leg, old['name'], old['leg']))
        return old['row_id']
