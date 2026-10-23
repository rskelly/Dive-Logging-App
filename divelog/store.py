"""The session: the current cruise's log, the lookups and the list of cruises."""

import csv
import re
import shutil
import uuid
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, Signal

from . import APP_ROOT
from .db import LogDB, LogExistsError, read_cruise
from .lookups import Lookups
from .settings import EXPORTS, home_dir


class AlreadyOpenError(Exception):
    """Another copy of the app is running."""


def read_config_variables():
    """Equipment configuration variables (edit config-variables.csv as needed)."""
    with open(APP_ROOT / 'config-variables.csv', newline='', encoding='utf-8') as f:
        return [r['variable'] for r in csv.DictReader(f) if r.get('variable')]


def safe_name(text):
    """Text usable in a file name."""
    return re.sub(r'[^A-Za-z0-9._-]+', '_', text or '').strip('_') or 'cruise'


class Store(QObject):
    # Emitted after any change to the log, the lookups or the list of cruises
    changed = Signal()

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.config_variables = read_config_variables()
        home_dir().mkdir(parents=True, exist_ok=True)
        self._lock = QLockFile(str(home_dir() / '.divelog.lock'))
        # Never time out: a lock is only stale if the process that took it has gone
        self._lock.setStaleLockTime(0)
        if not self._lock.tryLock(100):
            raise AlreadyOpenError(str(home_dir()))
        self.lookups = Lookups(settings.lookups_path)
        self.log = None
        self.cruise_id = ''

    def close(self):
        self.close_cruise()
        self.lookups.close()
        self._lock.unlock()

    def notify(self):
        self.changed.emit()

    # The current cruise

    @property
    def entry(self):
        """The current cruise's entry in the settings, or None."""
        return self.settings.cruise(self.cruise_id) if self.log else None

    @property
    def cruise(self):
        """The current cruise's row from its log, or None."""
        return self.log.cruise() if self.log else None

    @property
    def export_path(self):
        return Path(self.log.path).parent / EXPORTS

    def open_cruise(self, cruise_id):
        """Make a cruise current. Raises FileNotFoundError if its log is missing,
        or OldLogError (from db) for an old log."""
        entry = self.settings.cruise(cruise_id)
        path = Path(entry['log'])
        if not path.is_file():
            raise FileNotFoundError(str(path))
        log = LogDB(path)
        self.close_cruise()
        self.log, self.cruise_id = log, cruise_id
        self._sync_entry(entry, log.cruise())
        self.settings.current = cruise_id
        self.settings.save()
        self.notify()

    def close_cruise(self):
        if self.log is not None:
            self.log.close()
        self.log, self.cruise_id = None, ''

    def last(self, name):
        """The current cruise's last used dive or dive config ('last_dive', 'last_dive_config')."""
        return (self.entry or {}).get(name) or ''

    def remember(self, **values):
        """Record the last used dive or dive config for the current cruise."""
        if self.entry is not None:
            self.entry.update(values)
            self.settings.save()

    # The list of cruises

    def default_log_path(self, name, leg):
        return self.settings.logs_path / f'{safe_name(name)}_leg{safe_name(leg)}.sqlite'

    def create_cruise(self, values, path):
        """Create a cruise with a new log at path and make it current. Raises
        LogExistsError if path exists."""
        log = LogDB.create(Path(path), values)
        log.close()
        cruise_id = self._add_entry(values, path)
        self.open_cruise(cruise_id)
        return cruise_id

    def add_log(self, path):
        """Add an existing log (e.g. from another computer or the Shiny version) to
        the list. Returns its id; a log already in the list isn't added twice."""
        path = Path(path)
        for c in self.settings.cruises:
            if Path(c['log']).resolve() == path.resolve():
                return c['id']
        log = LogDB(path)  # adds any missing columns; OldLogError for an old log
        try:
            if log.cruise() is None:
                log.set_cruise({'name': path.stem, 'leg': '1'})
            cruise = log.cruise()
        finally:
            log.close()
        return self._add_entry(cruise, path)

    def _add_entry(self, cruise, path):
        entry = {'id': uuid.uuid4().hex, 'name': cruise.get('name') or '', 'leg': cruise.get('leg') or '',
                 'log': str(path), 'last_dive': '', 'last_dive_config': ''}
        self.settings.cruises.append(entry)
        self.settings.save()
        self.notify()
        return entry['id']

    def update_cruise(self, cruise_id, values):
        """Change a cruise's properties (in its log)."""
        entry = self.settings.cruise(cruise_id)
        if cruise_id == self.cruise_id:
            self.log.set_cruise(values)
            cruise = self.log.cruise()
        else:
            log = LogDB(Path(entry['log']))
            try:
                log.set_cruise(values)
                cruise = log.cruise()
            finally:
                log.close()
        self._sync_entry(entry, cruise)
        self.settings.save()
        self.notify()

    def move_log(self, cruise_id, new_path):
        """Move a cruise's log to new_path. On failure the log stays where it was
        and the error is raised."""
        entry = self.settings.cruise(cruise_id)
        old, new = Path(entry['log']), Path(new_path)
        if new.exists():
            raise LogExistsError(str(new))
        current = cruise_id == self.cruise_id
        if current:
            self.close_cruise()  # Windows can't move an open file
        try:
            new.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old), str(new))
            entry['log'] = str(new)
            self.settings.save()
        finally:
            if current:
                self.open_cruise(cruise_id)
            self.notify()

    def locate_log(self, cruise_id, path):
        """Point a cruise at its log's new location, after it was moved outside the app."""
        LogDB(Path(path)).close()  # check it opens
        self.settings.cruise(cruise_id)['log'] = str(path)
        self.settings.save()
        self.notify()

    def remove_cruise(self, cruise_id):
        """Take a cruise off the list. Its log file is kept."""
        if cruise_id == self.cruise_id:
            self.close_cruise()
        self.settings.cruises = [c for c in self.settings.cruises if c['id'] != cruise_id]
        if self.settings.current == cruise_id:
            self.settings.current = ''
        self.settings.save()
        self.notify()

    def details(self, entry):
        """The cruise row in an entry's log, or None if it can't be read."""
        if entry['id'] == self.cruise_id:
            return self.log.cruise()
        return read_cruise(entry['log'])

    @staticmethod
    def _sync_entry(entry, cruise):
        # The list shows the name and leg even when a log is missing
        if cruise:
            entry['name'], entry['leg'] = cruise.get('name') or '', cruise.get('leg') or ''


__all__ = ['AlreadyOpenError', 'LogExistsError', 'Store', 'safe_name']
