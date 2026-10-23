"""The open log and lookups, shared by all pages."""

import csv
import re
from datetime import datetime

from PySide6.QtCore import QLockFile, QObject, Signal

from . import APP_ROOT
from .db import LogDB
from .lookups import Lookups
from .settings import EXPORTS, LOG_DB, LOOKUPS_DB


class AlreadyOpenError(Exception):
    """Another copy of the app is using the data folder."""


def read_config_variables():
    """Equipment configuration variables (edit config-variables.csv as needed)."""
    with open(APP_ROOT / 'config-variables.csv', newline='', encoding='utf-8') as f:
        return [r['variable'] for r in csv.DictReader(f) if r.get('variable')]


class Store(QObject):
    # Emitted after any change to the log or lookups
    changed = Signal()

    def __init__(self, data_path):
        super().__init__()
        self.config_variables = read_config_variables()
        self.log = self.lookups = self._lock = None
        self.open(data_path)

    def open(self, data_path):
        """Open the log and lookups in data_path, creating them if needed.
        Raises AlreadyOpenError, or OldLogError (from db) for an old log."""
        data_path.mkdir(parents=True, exist_ok=True)
        same = self._lock is not None and data_path.resolve() == self.data_path.resolve()
        if same:
            lock = self._lock
        else:
            lock = QLockFile(str(data_path / '.divelog.lock'))
            # Never time out: a lock is only stale if the process that took it has gone
            lock.setStaleLockTime(0)
            if not lock.tryLock(100):
                raise AlreadyOpenError(str(data_path))
        try:
            log = LogDB(data_path / LOG_DB)
            lookups = Lookups(data_path / LOOKUPS_DB)
        except Exception:
            if not same:
                lock.unlock()
            raise
        self.close(keep_lock=same)
        self.data_path, self.log, self.lookups, self._lock = data_path, log, lookups, lock
        self.notify()

    def close(self, keep_lock=False):
        for thing in (self.log, self.lookups):
            if thing is not None:
                thing.close()
        if self._lock is not None and not keep_lock:
            self._lock.unlock()
        self.log = self.lookups = None
        if not keep_lock:
            self._lock = None

    @property
    def log_path(self):
        return self.data_path / LOG_DB

    @property
    def lookups_path(self):
        return self.data_path / LOOKUPS_DB

    @property
    def export_path(self):
        return self.data_path / EXPORTS

    def notify(self):
        self.changed.emit()


def set_aside(log_path, cruise=None):
    """Rename a log so a new one can be started. Returns the new name."""
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    cruise = re.sub(r'[^A-Za-z0-9._-]+', '_', cruise or '')
    target = log_path.with_name(f'{log_path.stem}_{cruise + "_" if cruise else ""}{stamp}{log_path.suffix}')
    log_path.rename(target)
    return target
