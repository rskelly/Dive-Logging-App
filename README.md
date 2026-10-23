# NDST Dive Logging App

Note: This project has been imported to DFO MSEA's gitlab page. You can find the version that is still being activitely developed here: https://gitlab.com/dfo-msea/Dive-Logging-App

__Main author:__  Jessica Nephin     
__Contact:__      jessica.nephin@dfo-mpo.gc.ca

- [Objective](#objective)
- [Summary](#summary)
- [Status](#status)
- [How it runs](#how-it-runs)
- [Cruises](#cruises)
- [Lookups](#lookups)
- [Data](#data)
- [Entering data](#entering-data)
- [Log format](#log-format)
- [Development](#development)
- [Contents](#contents)
- [Requirements](#requirements)

## Objective
To provide a user interface for logging survey events (dives and transects) during field operations by the Non-Destructive Survey Tools program

## Summary
A Windows desktop app written in Python with Qt. The user creates or selects a cruise, then adds, edits and deletes its dives and transects and their equipment and dive configurations. Personnel, instruments and platforms come from the MSEA database. Each cruise has its own SQLite log, and everything is saved as soon as it's entered, so nothing is lost if the app is closed or crashes. Data can also be exported to CSV with the **Export** button.

The app replaces an earlier R Shiny version; its logs aren't compatible. The design and its reasons are in [WINDOWS_APP_PLAN.md](WINDOWS_APP_PLAN.md); user instructions are in [README-desktop.txt](README-desktop.txt), which ships in the zip.

## Status
Under development

## How it runs
Users extract a zip and start `DiveLogging.bat`. The batch file finds Python 3.10 or later (asking for its path, or to install it, if it can't), then runs `run.py --setup`. That creates a virtual environment in `%LOCALAPPDATA%\DiveLogging\venv` and installs the pinned libraries from `requirements.txt`, but only on first use, after an update that changes the requirements, or after Python changes. A failed setup keeps the previous environment. The app then starts with that environment's `pythonw.exe`.

## Cruises
Everything is logged in the current cruise. The **Cruises** page lists the cruises: create one (**New cruise**), add a log made elsewhere (**Open log file**, e.g. on another laptop), **Select** the one to log, **Edit** its properties, or **Remove** it from the list (its log file is kept). The configuration, dive, transect and checks pages are disabled until a cruise is selected, and the app reopens the last cruise on start.

A cruise has a name, leg, start and end dates, ship (a platform from the lookups), objective, summary and note. Each cruise has its own log, created in the default log folder when the cruise is created (named `<cruise>_leg<leg>.sqlite`; the folder can be changed in Settings). Editing a cruise can also move its log: the user confirms the move, and if they decline or it fails, the log stays where it was. A log that was moved outside the app can be located again from the list.

Dives and transects have no cruise or leg fields; they record the current cruise's name and leg, and renaming the cruise renames them. The ship is the cruise's, so dive configurations don't include it. New dives preselect the last dive configuration used, and new transects the last dive used (also from the Transects page), remembered per cruise.

## Lookups
People, instruments and platforms are downloaded from the MSEA ReST API (msea-rov-db), `/shared/people/`, `/rov/instruments/` and `/rov/platforms/`, at the API URL set in Settings (default `https://msea.science/api/v2`). The log stores their IDs: dive pilots are a `;`-separated list of person IDs, equipment configurations have an `instrument_id` or a `platform_id`, and the cruise has a `ship_id`. Platforms whose equipment type is "Ship" are ships, offered for the cruise; the rest (ROVs, submersibles, drop cameras, ...) are subs, offered for platform configurations. The user sees names and serial numbers.

Because the app is often used offline, the lookups are cached in `lookups.sqlite` and only refreshed when the user clicks **Update lookups**. Everything is downloaded before the cache is touched, and the cache is replaced in one transaction, so a failed update leaves the lookups as they were. The cache starts empty, so update the lookups before first use. Exports include the lookups as `people.csv`, `instruments.csv` and `platforms.csv`.

## Data
Everything lives in `%LOCALAPPDATA%\DiveLogging` (or `DIVELOG_HOME`):
- `settings.json`: the API URL, proxy, default log folder, and the list of cruises with their log locations (and the last dive and dive config used).
- `lookups.sqlite`: the lookups, shared by all cruises.
- `logs\`: the default log folder.

A cruise's log keeps its properties in its `cruise` table, so the log describes itself. Exports go next to the log: `Exports\YYYY-MM-DD\<cruise>_<table>.csv`.

## Entering data
- **Dive configurations** need a name and a sub; ship and sub instruments are optional. The "+" next to the sub and each instrument list opens the equipment configuration form (preset to a platform or an instrument) and chooses the new configuration in that field.
- **Times** are UTC. Each has a calendar drop-down and a **Now** button, and must be set to save a dive or transect.
- **Configuration properties** are the variables an equipment configuration can set (pan, tilt, offsets, ...), with units and descriptions. They're edited from **Settings > Configuration Properties**, or the "+" next to the variable drop-down in the equipment configuration form, which then selects the property just added. They're kept in `settings.json`; the first run starts with `config-variables.csv`.
- Duplicate dive, transect and configuration names can't be saved. New transects are numbered after their dive's existing ones, and can be added from the dive form, also while editing a dive.
- **Checks** shows totals, warnings (missing dives, duplicate names, unreadable times, records that end before they start) and charts.

## Log format
- Times are ISO 8601 UTC (`2026-10-23T19:46:23Z`).
- Pilots are `;`-separated person IDs; the dive configuration instrument lists are `;`-separated equipment configuration names; configuration strings are `{'pan':10, 'tilt':-5.5}`.
- CSV exports are standard CSV (UTF-8, Windows line endings), with empty fields for missing values.
- Columns added in a later version go at the end of their table and are added to older logs when they're opened.
- `extract_log.py` in msea-rov-db, which turns a log into an import for the MSEA database, will be adapted to this model.

## Development
```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt pytest pip-tools
.venv/bin/python -m divelog                      # run the app
.venv/bin/python -m pytest tests                 # run the tests (offscreen, against a mock API)
```
- **Libraries.** Only PySide6-Essentials and truststore (plus the standard library). Both work on any Python 3.10+, so one set of Windows wheels fits every Python version. To change versions, edit `requirements.in` and run `pip-compile --generate-hashes --strip-extras --no-emit-index-url -o requirements.txt requirements.in`.
- **Releases.** `python tools/make_zip.py` writes `dist/DiveLogging-<version>.zip`. With `--wheels` it also bundles the Windows libraries, so setup works without access to PyPI. Bump `__version__` in `divelog/__init__.py` for each release.

## Contents
- `DiveLogging.bat`: launcher; finds Python and starts `run.py`.
- `run.py`: sets up the virtual environment and starts the app (standard library only).
- `divelog/`: the app. `db.py` (cruise logs), `lookups.py` (API and cache), `export.py`, `formats.py`, `settings.py` (settings, the cruise list, configuration properties), `store.py` (the session: current cruise, lookups, cruise list operations), `app.py`, and `ui/` (main window, cruises page, other pages, forms, configuration properties editor, charts).
- `config-variables.csv`: the configuration properties a new installation starts with (after that they're edited in the app).
- `requirements.in`, `requirements.txt`: library versions, pinned with hashes.
- `tools/make_zip.py`: builds the release zip.
- `tests/`: tests, run offscreen against a mock API.

## Requirements
Windows with Python 3.10 or later. Network access for the first start (to install the libraries, unless the zip includes them) and for updating the lookups.
