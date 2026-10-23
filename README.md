# NDST Dive Logging App

Note: This project has been imported to DFO MSEA's gitlab page. You can find the version that is still being activitely developed here: https://gitlab.com/dfo-msea/Dive-Logging-App

__Main author:__  Jessica Nephin     
__Contact:__      jessica.nephin@dfo-mpo.gc.ca

- [Objective](#objective)
- [Summary](#summary)
- [Status](#status)
- [How it runs](#how-it-runs)
- [Lookups](#lookups)
- [Data](#data)
- [Compatibility with the Shiny version](#compatibility-with-the-shiny-version)
- [Development](#development)
- [Contents](#contents)
- [Requirements](#requirements)

## Objective
To provide a user interface for logging survey events (dives and transects) during field operations by the Non-Destructive Survey Tools program

## Summary
A Windows desktop app written in Python with Qt. The app allows users to add, edit and delete dives and transects and associated metadata (cruise, equipment and dive configurations). Personnel and instruments come from the MSEA database. All data logged with the app are saved in a SQLite database as soon as they are entered, so nothing is lost if the app is closed or crashes. Data can also be exported to CSV with the **Export** button.

The app replaces an earlier R Shiny version. The design and its reasons are in [WINDOWS_APP_PLAN.md](WINDOWS_APP_PLAN.md); user instructions are in [README-desktop.txt](README-desktop.txt), which ships in the zip.

## Status
Under development

## How it runs
Users extract a zip and start `DiveLogging.bat`. The batch file finds Python 3.10 or later (asking for its path, or to install it, if it can't), then runs `run.py --setup`. That creates a virtual environment in `%LOCALAPPDATA%\DiveLogging\venv` and installs the pinned libraries from `requirements.txt`, but only on first use, after an update that changes the requirements, or after Python changes. A failed setup keeps the previous environment. The app then starts with that environment's `pythonw.exe`.

## Lookups
People and instruments are downloaded from the MSEA ReST API (msea-rov-db), `/shared/people/` and `/rov/instruments/`, at the API URL set in Settings (default `https://msea.science/api/v2`). The log stores their IDs: dive pilots are a `;`-separated list of person IDs and equipment configurations have an `instrument_id`. The user sees people's first and last names, and instruments' names and serial numbers.

Because the app is often used offline, the lookups are cached in `lookups.sqlite` and only refreshed when the user clicks **Update lookups**. Everything is downloaded before the cache is touched, and the cache is replaced in one transaction, so a failed update leaves the lookups as they were. The cache starts empty, so update the lookups before first use. Exports include the lookups as `people.csv` and `instruments.csv`.

## Data
Everything lives in `%LOCALAPPDATA%\DiveLogging` (or `DIVELOG_HOME`):
- `data\` holds the log (`divelogging-db.sqlite`), the lookups (`lookups.sqlite`) and `Exports\`. The data folder can be moved in Settings.
- `settings.json` holds the API URL, proxy and data folder.

Exports go to `Exports\YYYY-MM-DD\<cruise>_<table>.csv`. **New survey** sets the log aside (renamed, not deleted) and starts an empty one.

## Compatibility with the Shiny version
The log has the same tables and columns as the Shiny version wrote, so its logs can be opened and exported. Logs from before the lookups came from the API (equipment referenced by short code) can't be opened; the app offers to set them aside.

Differences by design (the output contract is in section 1 of the plan):
- Times are ISO 8601 (`2026-10-23T19:46:23Z`) instead of `2026-10-23T-19:46:23Z`. The app reads both. The time fix in `extract_log.py` (msea-rov-db) leaves the new format unchanged; that script still needs updating for instrument and person IDs.
- CSV exports are standard CSV with Windows line endings and empty fields for missing values (the Shiny version wrote `NA` and quoted every text value).

Smaller changes:
- Duplicate dive, transect and configuration names can't be saved.
- Times must be valid to save a dive or transect.
- Transects can be added while editing a dive, and new transects are numbered after the dive's existing ones.
- Checks also warns about unreadable times and records that end before they start.

## Development
```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt pytest pip-tools
.venv/bin/python -m divelog                      # run the app
.venv/bin/python -m pytest tests                 # run the tests (offscreen, against a mock API)
```
- **Libraries.** Only PySide6-Essentials and truststore (plus the standard library). Both work on any Python 3.10+, so one set of Windows wheels fits every Python version. To change versions, edit `requirements.in` and run `pip-compile --generate-hashes --strip-extras --no-emit-index-url -o requirements.txt requirements.in`.
- **Releases.** `python tools/make_zip.py` writes `dist/DiveLogging-<version>.zip`. With `--wheels` it also bundles the Windows libraries, so setup works without access to PyPI. Bump `__version__` in `divelog/__init__.py` for each release.
- **Shiny compatibility tests.** `tests/fixtures/shiny/` holds the log, lookups and export the Shiny version wrote for a scripted session. `tests/test_equivalence.py` runs the same session in this app and compares, and checks that a Shiny log can be opened and exported. These files are a fixed reference: the Shiny app has been removed, so they can't be regenerated.

## Contents
- `DiveLogging.bat`: launcher; finds Python and starts `run.py`.
- `run.py`: sets up the virtual environment and starts the app (standard library only).
- `divelog/`: the app. `db.py` (log), `lookups.py` (API and cache), `export.py`, `formats.py`, `settings.py`, `store.py`, `app.py`, and `ui/` (main window, pages, forms, charts).
- `config-variables.csv`: variables offered when building an equipment configuration (edit as needed).
- `requirements.in`, `requirements.txt`: library versions, pinned with hashes.
- `tools/make_zip.py`: builds the release zip.
- `tests/`: tests and the Shiny reference fixtures.

## Requirements
Windows with Python 3.10 or later. Network access for the first start (to install the libraries, unless the zip includes them) and for updating the lookups.
