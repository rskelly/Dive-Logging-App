"""Where the app keeps its files, and the user's settings.

Everything lives in one folder (the "home"): %LOCALAPPDATA%\\DiveLogging on
Windows, ~/.local/share/DiveLogging elsewhere, or DIVELOG_HOME if set.

  home/settings.json    API URL, proxy, default log folder, the list of cruises,
                        configuration properties
  home/lookups.sqlite   people, instruments and platforms from the API
  home/logs/            cruise logs, unless the default folder is changed or a
                        cruise's log is moved
  home/venv/            Python libraries, managed by run.py
"""

import csv
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import APP_ROOT

DEFAULT_API_URL = 'https://msea.science/api/v2'
LOOKUPS_DB = 'lookups.sqlite'
EXPORTS = 'Exports'
# Fields of each entry in Settings.cruises
CRUISE_FIELDS = ('id', 'name', 'leg', 'log', 'last_dive', 'last_dive_config')
# Fields of each configuration property (a variable an equipment configuration can set)
PROPERTY_FIELDS = ('variable', 'unit', 'description')


def default_config_properties():
    """The properties the app starts with, from config-variables.csv."""
    with open(APP_ROOT / 'config-variables.csv', newline='', encoding='utf-8') as f:
        return [{k: (r.get(k) or '').strip() for k in PROPERTY_FIELDS} for r in csv.DictReader(f) if r.get('variable')]


def home_dir():
    if os.environ.get('DIVELOG_HOME'):
        return Path(os.environ['DIVELOG_HOME'])
    if sys.platform == 'win32':
        return Path(os.environ['LOCALAPPDATA']) / 'DiveLogging'
    return Path.home() / '.local' / 'share' / 'DiveLogging'


@dataclass
class Settings:
    api_url: str = DEFAULT_API_URL
    # Empty: use the system's proxy settings
    proxy: str = ''
    # Where new cruise logs are created. Empty: home/logs
    logs_dir: str = ''
    # One entry per cruise: id (generated when it's added), name and leg (for
    # the list, kept in step with the log), log (the log file's path), and the
    # last dive and dive config used, which new transects and dives default to
    cruises: list = field(default_factory=list)
    # id of the cruise open when the app was last closed
    current: str = ''
    # Variables equipment configurations can set: {variable, unit, description}
    config_properties: list = field(default_factory=default_config_properties)

    @property
    def logs_path(self):
        return Path(self.logs_dir) if self.logs_dir else home_dir() / 'logs'

    @property
    def lookups_path(self):
        return home_dir() / LOOKUPS_DB

    def cruise(self, cruise_id):
        return next((c for c in self.cruises if c['id'] == cruise_id), None)

    @classmethod
    def load(cls):
        try:
            saved = json.loads((home_dir() / 'settings.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            saved = {}
        settings = cls(**{k: v for k, v in saved.items()
                          if k in ('api_url', 'proxy', 'logs_dir', 'current') and isinstance(v, str)})
        for c in saved.get('cruises', []) if isinstance(saved.get('cruises'), list) else []:
            if isinstance(c, dict) and c.get('id') and c.get('log'):
                settings.cruises.append({k: str(c.get(k) or '') for k in CRUISE_FIELDS})
        if isinstance(saved.get('config_properties'), list):
            settings.config_properties = [{k: str(p.get(k) or '') for k in PROPERTY_FIELDS}
                                          for p in saved['config_properties'] if isinstance(p, dict) and p.get('variable')]
        return settings

    def save(self):
        home_dir().mkdir(parents=True, exist_ok=True)
        path = home_dir() / 'settings.json'
        # Write a new file, then replace, so a crash can't leave half a file
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding='utf-8')
        tmp.replace(path)
