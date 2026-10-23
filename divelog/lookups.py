"""Lookups of people and instruments from the MSEA ReST API (msea-rov-db).

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
    # One row: when and from where the lookups were last updated
    'CREATE TABLE IF NOT EXISTS lookups_info (updated_on TEXT NOT NULL, source TEXT NOT NULL)',
]
PEOPLE_COLUMNS = ['id', 'first_name', 'last_name']
INSTRUMENT_COLUMNS = ['id', 'name', 'serial_number', 'brand', 'model', 'type', 'retired']


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


def fetch_lookups(api_url, proxy=''):
    """Download people and instruments as lists of row tuples. Raises on any
    error, including an empty list."""
    opener = _opener(proxy)
    people = fetch_all(f'{api_url}/shared/people/', opener)
    instruments = fetch_all(f'{api_url}/rov/instruments/', opener)
    if not people:
        raise LookupsError('The API returned no people.')
    if not instruments:
        raise LookupsError('The API returned no instruments.')
    return {
        'people': [(p['id'], p['first_name'], p['last_name']) for p in people],
        'instruments': [(i['id'], i.get('name'), i['serial_number'],
                         _get(i, 'model', 'brand_name'), _get(i, 'model', 'model_name'),
                         _get(i, 'model', 'equipment_type', 'name'), i.get('retired'))
                        for i in instruments],
    }


def update_lookups(path, api_url, proxy=''):
    """Replace the lookups in the db at path with the API's. Everything is
    downloaded before the db is touched, and the replacement is one transaction.
    Returns the number of people and instruments."""
    api_url = api_url.rstrip('/')
    lookups = fetch_lookups(api_url, proxy)
    updated_on = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    con = sqlite3.connect(path)
    try:
        with con:
            con.execute('DELETE FROM people')
            con.executemany('INSERT INTO people VALUES (?, ?, ?)', lookups['people'])
            con.execute('DELETE FROM instruments')
            con.executemany('INSERT INTO instruments VALUES (?, ?, ?, ?, ?, ?, ?)', lookups['instruments'])
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

    def info(self):
        """{'updated_on', 'source'} of the last update, or None if never updated."""
        row = self.con.execute('SELECT updated_on, source FROM lookups_info').fetchone()
        return dict(row) if row else None


def person_label(person):
    return f"{person['first_name']} {person['last_name']}"


def instrument_label(instrument):
    """'name (serial)', or 'brand model (serial)' when there's no name; retired ones marked."""
    name = instrument['name'] or ' '.join(p for p in (instrument['brand'], instrument['model']) if p)
    label = f"{name} ({instrument['serial_number']})"
    return label + ' [retired]' if instrument['retired'] else label
