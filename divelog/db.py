"""The dive log: one SQLite file per survey.

The tables and columns are the ones the earlier R Shiny version of the app
created, so logs it wrote can still be opened.
"""

import sqlite3
import uuid

# Columns of each table, in order. All are TEXT except equipconfig.instrument_id.
# pilot is a ';'-separated list of person IDs; the *_instrument_configs columns
# are ';'-separated lists of equipment config names.
TABLES = {
    'cruise': ['row_id', 'name', 'leg', 'objective', 'summary', 'note'],
    'dives': ['row_id', 'cruise_name', 'leg', 'name', 'pilot', 'start_time', 'end_time',
              'site_name', 'dive_config', 'objective', 'summary', 'note'],
    'transects': ['row_id', 'cruise_name', 'leg', 'dive_name', 'name', 'start_time', 'end_time',
                  'objective', 'summary', 'note'],
    'equipconfig': ['row_id', 'name', 'instrument_id', 'type', 'configuration', 'note'],
    'diveconfig': ['row_id', 'name', 'ship_config', 'sub_config', 'ship_instrument_configs',
                   'sub_instrument_configs', 'note'],
}
INTEGER_COLUMNS = {('equipconfig', 'instrument_id')}


class OldLogError(Exception):
    """The log was written by a version of the app that used equipment short codes."""


def _create_sql(table):
    cols = ', '.join(f'"{c}" {"INTEGER" if (table, c) in INTEGER_COLUMNS else "TEXT"}'
                     for c in TABLES[table])
    return f'CREATE TABLE IF NOT EXISTS "{table}" ({cols})'


def create_log_db(path):
    """Create the log at path, or any missing tables. Raises OldLogError for an old log."""
    con = sqlite3.connect(path)
    try:
        cols = [r[1] for r in con.execute('PRAGMA table_info(equipconfig)')]
        if cols and 'instrument_id' not in cols:
            raise OldLogError(f'"{path}" was created by an older version of the app '
                              '(equipment configurations use short codes).')
        with con:
            for table in TABLES:
                con.execute(_create_sql(table))
    finally:
        con.close()


class LogDB:
    """Read and write the log's tables. Every write is committed immediately, so
    nothing is lost if the app is closed or crashes."""

    def __init__(self, path):
        create_log_db(path)
        self.path = path
        self.con = sqlite3.connect(path)
        self.con.row_factory = sqlite3.Row

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
