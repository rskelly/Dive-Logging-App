"""Where the app keeps its files, and the user's settings.

Everything lives in one folder (the "home"): %LOCALAPPDATA%\\DiveLogging on
Windows, ~/.local/share/DiveLogging elsewhere, or DIVELOG_HOME if set.

  home/settings.json   API URL, proxy, data folder
  home/data/           log db, lookups db, Exports (unless moved in settings)
  home/venv/           Python libraries, managed by run.py
"""

import json
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path

DEFAULT_API_URL = 'https://msea.science/api/v2'
LOG_DB = 'divelogging-db.sqlite'
LOOKUPS_DB = 'lookups.sqlite'
EXPORTS = 'Exports'


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
    # Empty: home/data
    data_dir: str = ''

    @property
    def data_path(self):
        return Path(self.data_dir) if self.data_dir else home_dir() / 'data'

    @classmethod
    def load(cls):
        try:
            saved = json.loads((home_dir() / 'settings.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            saved = {}
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in saved.items() if k in names and isinstance(v, str)})

    def save(self):
        home_dir().mkdir(parents=True, exist_ok=True)
        (home_dir() / 'settings.json').write_text(json.dumps(asdict(self), indent=2), encoding='utf-8')
