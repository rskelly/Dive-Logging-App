"""Lookups of people, instruments and platforms from the MSEA ReST API (msea-rov-db).

They are cached in a SQLite file because the app is often used offline, and are
only refreshed when the user asks. A failed refresh leaves the cache as it was.
"""

import json
import sqlite3
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from . import __version__

try:
    import truststore
except ImportError:  # e.g. running the tests without it
    truststore = None

TIMEOUT = 30
PAGE_SIZE = 500

SCHEMA = [
    'CREATE TABLE IF NOT EXISTS people ('
    'id INTEGER PRIMARY KEY, first_name TEXT NOT NULL, last_name TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS instruments ('
    'id INTEGER PRIMARY KEY, name TEXT, serial_number TEXT NOT NULL, '
    'brand TEXT, model TEXT, type TEXT, retired TEXT)',
    # Ships, ROVs, submersibles, ... type is the equipment type: 'Ship' for ships
    'CREATE TABLE IF NOT EXISTS platforms ('
    'id INTEGER PRIMARY KEY, name TEXT NOT NULL, serial_number TEXT, '
    'brand TEXT, model TEXT, type TEXT, retired TEXT)',
    # One row: when and from where the lookups were last updated
    'CREATE TABLE IF NOT EXISTS lookups_info (updated_on TEXT NOT NULL, source TEXT NOT NULL)',
]
PEOPLE_COLUMNS = ['id', 'first_name', 'last_name']
INSTRUMENT_COLUMNS = ['id', 'name', 'serial_number', 'brand', 'model', 'type', 'retired']
PLATFORM_COLUMNS = INSTRUMENT_COLUMNS
SHIP_TYPE = 'Ship'  # the API's equipment type for ships


class LookupsError(Exception):
    pass


def create_lookups_db(path):
    """Create the lookup tables at path if they don't exist. They start empty."""
    con = sqlite3.connect(path)
    try:
        with con:
            for sql in SCHEMA:
                con.execute(sql)
    finally:
        con.close()


def _ssl_context():
    # Verify certificates with Windows (or the OS), like the browser does, so
    # certificates re-signed by a corporate proxy are trusted. See the plan, section 6.
    if truststore is not None:
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return ssl.create_default_context()


def _opener(proxy):
    """A URL opener. With no proxy given, urllib uses the system's proxy settings."""
    handlers = [urllib.request.HTTPSHandler(context=_ssl_context())]
    if proxy:
        handlers.append(urllib.request.ProxyHandler({'http': proxy, 'https': proxy}))
    return urllib.request.build_opener(*handlers)


def fetch_all(url, opener):
    """Get all records from a paginated list endpoint. The API returns
    {count, next, previous, results}; pages are requested by number rather than
    by following 'next', which is built from the Host header the API sees."""
    results = []
    page = 1
    while True:
        query = urllib.parse.urlencode({'detail': 'ref', 'count': PAGE_SIZE, 'page': page})
        req = urllib.request.Request(f'{url}?{query}', headers={
            'Accept': 'application/json', 'User-Agent': f'DiveLogging/{__version__}'})
        with opener.open(req, timeout=TIMEOUT) as resp:
            body = json.load(resp)
        results.extend(body['results'])
        if not body.get('next'):
            return results
        page += 1


def _get(record, *keys):
    """A (possibly nested, possibly null) field of a record."""
    for key in keys:
        if not isinstance(record, dict):
            return None
        record = record.get(key)
    return record


def _equipment_row(item):
    return (item['id'], item.get('name'), item.get('serial_number'),
            _get(item, 'model', 'brand_name'), _get(item, 'model', 'model_name'),
            _get(item, 'model', 'equipment_type', 'name'), item.get('retired'))


def fetch_lookups(api_url, proxy=''):
    """Download people, instruments and platforms as lists of row tuples. Raises
    on any error, including an empty list."""
    opener = _opener(proxy)
    lookups = {
        'people': fetch_all(f'{api_url}/shared/people/', opener),
        'instruments': fetch_all(f'{api_url}/rov/instruments/', opener),
        'platforms': fetch_all(f'{api_url}/rov/platforms/', opener),
    }
    for kind, records in lookups.items():
        if not records:
            raise LookupsError(f'The API returned no {kind}.')
    return {
        'people': [(p['id'], p['first_name'], p['last_name']) for p in lookups['people']],
        'instruments': [_equipment_row(i) for i in lookups['instruments']],
        'platforms': [_equipment_row(p) for p in lookups['platforms']],
    }


def update_lookups(path, api_url, proxy=''):
    """Replace the lookups in the db at path with the API's. Everything is
    downloaded before the db is touched, and the replacement is one transaction.
    Returns the number of people, instruments and platforms."""
    api_url = api_url.rstrip('/')
    lookups = fetch_lookups(api_url, proxy)
    updated_on = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    con = sqlite3.connect(path)
    try:
        with con:
            con.execute('DELETE FROM people')
            con.executemany('INSERT INTO people VALUES (?, ?, ?)', lookups['people'])
            for table in ('instruments', 'platforms'):
                con.execute(f'DELETE FROM {table}')
                con.executemany(f'INSERT INTO {table} VALUES (?, ?, ?, ?, ?, ?, ?)', lookups[table])
            con.execute('DELETE FROM lookups_info')
            con.execute('INSERT INTO lookups_info VALUES (?, ?)', (updated_on, api_url))
    finally:
        con.close()
    return {k: len(v) for k, v in lookups.items()}


def describe_error(error):
    """A short explanation of a failed update, for the user."""
    if isinstance(error, urllib.error.HTTPError):
        return f'The API answered with an error: HTTP {error.code} {error.reason}.'
    if isinstance(error, urllib.error.URLError):
        reason = error.reason
        if isinstance(reason, ssl.SSLCertVerificationError):
            return f"The server's certificate could not be verified: {reason.verify_message}."
        return f'The API could not be reached: {reason}.'
    if isinstance(error, TimeoutError):
        return 'The API did not answer in time.'
    if isinstance(error, (json.JSONDecodeError, KeyError, TypeError)):
        return f'The API sent something unexpected ({type(error).__name__}: {error}).'
    return str(error)


class Lookups:
    """Read the cached lookups, with labels for display."""

    def __init__(self, path):
        create_lookups_db(path)
        self.path = path
        self.con = sqlite3.connect(path)
        self.con.row_factory = sqlite3.Row

    def close(self):
        self.con.close()

    def people(self):
        return [dict(r) for r in self.con.execute(
            'SELECT id, first_name, last_name FROM people ORDER BY last_name, first_name')]

    def instruments(self):
        return [dict(r) for r in self.con.execute(
            f'SELECT {", ".join(INSTRUMENT_COLUMNS)} FROM instruments ORDER BY brand, model, name')]

    def platforms(self):
        return [dict(r) for r in self.con.execute(
            f'SELECT {", ".join(PLATFORM_COLUMNS)} FROM platforms ORDER BY name')]

    def ships(self):
        return [p for p in self.platforms() if p['type'] == SHIP_TYPE]

    def subs(self):
        """Platforms that dive: everything but ships."""
        return [p for p in self.platforms() if p['type'] != SHIP_TYPE]

    def info(self):
        """{'updated_on', 'source'} of the last update, or None if never updated."""
        row = self.con.execute('SELECT updated_on, source FROM lookups_info').fetchone()
        return dict(row) if row else None


def person_label(person):
    return f"{person['first_name']} {person['last_name']}"


def platform_label(platform):
    """'name (serial)', or 'name' when there's no serial; retired ones marked."""
    label = platform['name'] + (f" ({platform['serial_number']})" if platform['serial_number'] else '')
    return label + ' [retired]' if platform['retired'] else label


def instrument_label(instrument):
    """'name (serial)', or 'brand model (serial)' when there's no name; retired ones marked."""
    name = instrument['name'] or ' '.join(p for p in (instrument['brand'], instrument['model']) if p)
    label = f"{name} ({instrument['serial_number']})"
    return label + ' [retired]' if instrument['retired'] else label
