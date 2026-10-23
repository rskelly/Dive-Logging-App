"""Export all tables as CSV: Exports/YYYY-MM-DD/<cruise>_<table>.csv."""

import csv
import re
from datetime import date

from .db import TABLES
from .lookups import INSTRUMENT_COLUMNS, PEOPLE_COLUMNS, PLATFORM_COLUMNS

# Characters Windows doesn't allow in file names
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def export_all(log, lookups, export_dir, today=None):
    """Write every log table, plus the people, instruments and platforms their IDs
    refer to. Files are named after the log's cruise. Returns the folder written to."""
    cruise = log.cruise()
    cruise = _BAD_CHARS.sub('_', cruise['name']) if cruise and cruise['name'] else 'NA'
    folder = export_dir / (today or date.today()).isoformat()
    folder.mkdir(parents=True, exist_ok=True)

    tables = {t: (TABLES[t], log.rows(t)) for t in sorted(TABLES)}
    tables['people'] = (PEOPLE_COLUMNS, lookups.people())
    tables['instruments'] = (INSTRUMENT_COLUMNS, lookups.instruments())
    tables['platforms'] = (PLATFORM_COLUMNS, lookups.platforms())
    for table, (columns, rows) in tables.items():
        # csv's default: Windows line endings, quotes only where needed
        with open(folder / f'{cruise}_{table}.csv', 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            writer.writerows([['' if r[c] is None else r[c] for c in columns] for r in rows])
    return folder
