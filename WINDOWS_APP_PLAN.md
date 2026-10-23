# Plan: Dive Logging App as a Windows desktop application

Status: implemented in `divelog/`, `run.py` and `DiveLogging.bat` (see the README). The Shiny app has been removed, and compatibility with it is no longer required (see [Later changes](#later-changes)); sections 1 and 3 describe the original plan. Where the implementation differs from the original plan, this document has been updated to match, and the differences are listed under [Implementation notes](#implementation-notes).

## Goal
Replace the Shiny app (and its Docker container) with a native Windows program that does the same things and writes the same data: the same SQLite log, the same lookups, and the same CSV exports. It doesn't need R, Docker or a browser.

The output only has to be *equivalent*, not byte-identical. Two formats deliberately change (see [Output contract](#1-output-contract)).

## Approach
Rewrite the app in **Python with PySide6 (Qt)** and package it with **PyInstaller**.

- The app is forms over two SQLite files, four plots, a CSV export and one HTTP fetch. The Python standard library covers most of that (`sqlite3`, `csv`, `uuid`, `urllib`). The only extra libraries are PySide6-Essentials for the windows (the charts are drawn with Qt's own painter) and `truststore` for certificates (section 6).
- Keep it to those two. The libraries are downloaded into a virtual environment on first run (section 5), so fewer and smaller libraries mean a faster, more reliable first start. Both also work on any Python 3.10 or later (PySide6's Windows wheels are "abi3"; `truststore` is pure Python), which keeps the option of shipping them in the zip.
- msea-rov-db and its importer (`extract_log.py`) are already Python, so the logger, the API and the importer share one language.
- A native app calls the API directly, so the Docker networking problems (`host.docker.internal`, `ALLOWED_HOSTS`) go away.

Not chosen: bundling portable R with the Shiny app behind a browser or Electron wrapper. It isn't one file, it starts slowly, it's hard to sign, and it's still a web page rather than a desktop app.

## 1. Output contract
Write this down before any UI work, and test against it.

**Cruise logs** (one per cruise; originally one `divelogging-db.sqlite`)
- Same tables as `db.R`: `cruise`, `dives`, `transects`, `equipconfig`, `diveconfig`, starting with the same columns in the same order. All are TEXT except the `*_id` columns, which are INTEGER.
- **Added later** (see [Cruise sessions](#cruise-sessions)), at the end of their tables so Shiny columns stay first: `cruise.start_date`, `end_date` (YYYY-MM-DD) and `ship_id` (a platform), and `equipconfig.platform_id`. Older logs get them when opened. `cruise` holds one row, the log's cruise; `diveconfig.ship_config` is only set in Shiny logs.
- Same guard: refuse to open an old log whose `equipconfig` has `short_code` instead of `instrument_id`.
- `row_id`: UUID4.
- Pilots and dive-config instrument lists: `;`-separated (pilots are person IDs).
- Configuration strings: `{'pan':10, 'tilt':5}`.
- **Change:** times are ISO 8601 UTC, `%Y-%m-%dT%H:%M:%SZ` (e.g. `2026-10-23T19:46:23Z`), with no dash after the `T`.
  - The importer's `fix_times()` (`replace('T-', 'T')`) leaves the new format unchanged, so it keeps working.
  - When *reading* a log (Checks plots, editing), accept both formats, since logs written by the current Shiny version use `T-`.

**`lookups.sqlite`**
- Same tables: `people (id, first_name, last_name)`, `instruments (id, name, serial_number, brand, model, type, retired)` and `lookups_info (updated_on, source)`, plus (added later) `platforms`, with the same columns as `instruments`.
- Same update rule: download every page of every endpoint first, then replace the tables and `lookups_info` in one transaction. A failed or empty download changes nothing.

**Exports**
- Same names: `Exports/YYYY-MM-DD/<cruise>_<table>.csv`, one file per log table plus `people`, `instruments` and (added later) `platforms`. `Exports` is next to the cruise's log.
- Same columns, in the same order, with a header row.
- **Change:** standard CSV as written by Python's `csv` module: UTF-8, Windows (CRLF) line endings, values quoted only when needed, missing values as empty fields rather than `NA`.

**Equivalence tests:** script the same session in both apps (cruise, two equipment configs, a dive config, a dive with a transect, an edit, a delete, an export). Then compare:
- the SQLite *contents*, ignoring `row_id` and normalising both time formats;
- the CSVs *parsed as tables*, treating `NA` and empty as equal.

Run these in CI for as long as both apps exist.

## 2. Structure
```
DiveLogging.bat   launcher: finds Python, runs setup, starts the app (section 5)
run.py            bootstrap, standard library only: builds/checks the virtual environment, starts the app
requirements.txt  exact versions and hashes of PySide6 and truststore
divelog/
  db.py         cruise log schema, upgrades of older logs, old-log guard
  lookups.py    people, instruments, platforms: fetch_all(), update_lookups()
  export.py     CSV export
  formats.py    time (read both formats), config-string, ID-list helpers
  ui/
    main_window.py   sidebar + stacked pages, toolbar, settings dialog
    cruises.py       the Cruises page: create, open, select, edit, move, remove
    pages.py         generic Add/Edit/Delete page, read-only lookup pages, Checks
    forms.py         cruise, equipconfig, diveconfig, dive, transect dialogs
    widgets.py       form building blocks
    charts.py        bar and timeline charts, drawn with QPainter
  settings.py   home folder, settings.json (API URL, proxy, default log folder, cruise list)
  store.py      the session: current cruise's log, lookups, cruise list operations, single-copy lock
  app.py        start-up (python -m divelog)
tests/          unit tests + compatibility tests against the Shiny version's output
```

## 3. Feature mapping

| Shiny today | Desktop version |
|---|---|
| Sidebar tabs | `QListWidget` sidebar and a `QStackedWidget` of pages |
| DT tables with single-row selection | `QTableView` over a SQL query model, selecting whole rows |
| Modal entry forms | `QDialog`. Submit stays disabled until required fields are filled (same rule as `obsFieldsMandatory`) |
| Edit with locked key fields (cruise name/leg, config names) | Same dialog, with those fields read-only |
| Delete confirmation | `QMessageBox` saying "cannot be undone" |
| Dive name **Check** button | Same button, or check as the user types |
| **Start** / **End** time buttons | Fill the field with the current UTC time in the new format |
| **Add Transect** inside the dive form | Opens the transect dialog on top of the dive dialog. The dive dialog keeps its unsaved values, which replaces the `current_dive` global |
| Config variable/value **Add** | Same controls, building the same string from `config-variables.csv`, which is bundled with the app |
| Pilot multi-select (names shown, IDs stored) | Checkable list or multi-select combo box showing labels and storing IDs |
| Instrument label "name (serial) [retired]" | Same label rule |
| **Update lookups** | Runs in a background thread with a progress indicator. Errors show in a dialog and the lookups stay unchanged |
| First-run "no lookups" prompt | Same prompt on startup when `lookups_info` is empty |
| Checks tab | Four info boxes, a warnings panel and four charts (dive durations, transect durations, timeline, hours per pilot) |
| **Export** | Same files, plus an "Open folder" link afterwards |

Port existing quirks deliberately rather than by accident. For example, editing an equipment config rebuilds the variable list by stripping the braces and commas and splitting on spaces. Decide whether to keep or fix each one, and note the decision in the code.

**Platforms** (originally deferred, now done; see [Cruise sessions](#cruise-sessions)): ships and subs come from `/rov/platforms/`. The ship is a property of the cruise, and platform configurations reference a sub.

## 4. Windows specifics
- **Data:** the program may be installed somewhere read-only, so don't store data next to it. Settings and the lookups are in `%LOCALAPPDATA%\DiveLogging\`; cruise logs default to `%LOCALAPPDATA%\DiveLogging\logs\`, which can be changed in settings, and each log can be moved. Add **Open log folder**.
- **Settings:** stored in `%LOCALAPPDATA%\DiveLogging\settings.json`, not environment variables or the registry, so everything the app keeps is in one folder. API URL default: `https://msea.science/api/v2`. Optional proxy setting (see [Network access](#6-network-access-to-msea-science)).
- **Single writer:** only one copy of the app may run at a time (`QLockFile` in the data folder), so two windows can't write to the same log.

## 5. Packaging and security policy
Two ways to ship it:

| | Single EXE (`--onefile`) | Zip of a folder build (`--onedir`) |
|---|---|---|
| What users get | One `.exe`, about 80–120 MB | A zip to extract: a small `.exe` plus DLLs and Python modules |
| How it runs | Unpacks itself to `%TEMP%\_MEIxxxxx` on every launch and loads its DLLs from there | Runs in place; nothing is unpacked |
| Startup | Several seconds (unpacking) | About 1 second |
| Antivirus (Defender) | Flagged more often: "unpack to Temp and run" looks like malware droppers | Flagged less often |
| Policies blocking code in `%TEMP%` (AppLocker/WDAC) | Blocked | Not affected, unless the extracted folder is in a blocked location too |
| SmartScreen ("Windows protected your PC") | Shows for an unsigned exe | Also shows: files extracted from a downloaded zip keep the "downloaded from the internet" mark |
| Allow-listing by file hash | One file per release | Many files per release |
| Allow-listing by publisher (needs signing) | Sign one file | Sign the exe and our own DLLs |

**Conclusion:** the zip (`--onedir`) is *somewhat* less trouble with antivirus and with policies that block running code from Temp. It doesn't help with SmartScreen or with allow-listing. Code signing is what really fixes those.

**Third option, with no executable of our own:** a zip containing the official *Python embeddable package* (python.org), the libraries and the app's `.py` files, started from a shortcut to `pythonw.exe`. `pythonw.exe` and the Python DLLs are signed by the Python Software Foundation, and the app itself is just script files. Under publisher-based policies this can be the easiest to get approved. Some organisations block `python.exe` itself, though, so check first.

**Fourth option (recommended): a launcher script and the user's installed Python.** Installing Python is allowed on DFO machines, so the zip can contain no executables at all: just a batch file, the app's `.py` files and a requirements list. The libraries are installed into a virtual environment on first run.

How it works:
1. The user extracts the zip anywhere (e.g. `%LOCALAPPDATA%\DiveLogging\app`) and starts `DiveLogging.bat`, or a desktop shortcut to it.
2. The batch file finds a working Python. It tries these in order and stops at the first one that works:
   1. the path saved by a previous run (`%LOCALAPPDATA%\DiveLogging\python.txt`);
   2. the Python launcher (`py -3`), which the python.org installer adds;
   3. `python` on `PATH`;
   4. the standard install folders: `%LOCALAPPDATA%\Programs\Python\Python3*` (per-user installs) and `%ProgramFiles%\Python3*`.
3. "Works" means the batch file actually runs the candidate with a version check (3.10 or later), rather than trusting the path. This matters because Windows ships a fake `python.exe` in `%LOCALAPPDATA%\Microsoft\WindowsApps` that opens the Microsoft Store instead of running Python.
4. **If nothing is found**, the console explains the two choices:
   - install Python from python.org: the per-user install needs no admin rights, and the "Add to PATH" option isn't required because step 2.4 finds it;
   - or type the full path to an existing `python.exe`. The path is checked the same way, then saved.
5. It saves the working path and runs `python run.py --setup` **in the console**, so the user can see the install's progress (see below). This step takes well under a second when the environment is already up to date.
6. It then starts the app with `pythonw.exe` from the virtual environment, so no console window stays open.

**Setup (`run.py --setup`, standard library only):**
- The virtual environment lives in `%LOCALAPPDATA%\DiveLogging\venv`. It records a hash of `requirements.txt` and the Python version it was built with.
- If the environment exists and both match, setup does nothing. **No network access on normal startups**, which matters because the laptops are often offline.
- Otherwise (first run, a new app version with different requirements, or Python upgraded or reinstalled), it builds a new environment:
  1. `python -m venv` into `venv.new`;
  2. `pip install --require-hashes -r requirements.txt` into it;
  3. check that PySide6 imports;
  4. only then replace `venv` with `venv.new`.
- A failed install, for example offline or PyPI blocked, deletes `venv.new` and leaves the existing environment untouched. This is the same rule as the lookups update.
  - If a working environment already exists, the app starts with it, and the console says the update will be retried next time.
  - If none exists, the console explains that the first run needs network access to PyPI, and shows pip's error.
- `requirements.txt` pins exact versions with hashes (`pip-compile --generate-hashes`), so every laptop gets the same libraries and pip refuses anything that has been tampered with.
- If anything else goes wrong at startup, `run.py` shows a Windows message box through `ctypes`, which needs no extra libraries.

**Network access for pip:** pip downloads from PyPI (`pypi.org` and `files.pythonhosted.org`), which may be blocked on the intranet in the same way as msea.science (section 6).
- pip respects proxy settings and a `pip.ini` that points at an internal package mirror, if DFO provides one. Ask IT.
- Recent pip versions verify certificates through Windows by default (pip includes truststore), so TLS inspection shouldn't be a problem for pip.
- If PyPI isn't reachable from field laptops, ship the wheels in the zip as well and have setup try `pip install --no-index --find-links wheels` first. Because PySide6 and `truststore` work on any Python 3.10+, one set of wheels is enough.

Why it's less hassle:
- There are no unsigned executables of our own. `python.exe`, `pythonw.exe` and the `py` launcher are signed by the Python Software Foundation, and Python is installed through an approved channel.
- Nothing unpacks to `%TEMP%`.
- It's a batch file rather than PowerShell, because managed machines often block `.ps1` scripts through the execution policy, and batch files aren't affected.
- Updating means replacing the app folder. Data lives in `%LOCALAPPDATA%\DiveLogging\data\` and isn't touched. If the new version's requirements differ, setup rebuilds the environment on the next start, which needs network access once.
- Do the first run, and any update, before going to the field.

Things to watch:
- Windows marks files from a downloaded zip as "from the internet" and may warn when the `.bat` is run. Unblocking the zip before extracting (Properties → Unblock) avoids that.
- The Qt DLLs in the virtual environment load from a user-writable folder. That's only a problem if DLL rules are enforced (rare, but ask).
- The batch file must be careful with paths containing spaces and parentheses (e.g. `Program Files (x86)`). Keep it to finding Python and quote every path; everything else belongs in `run.py`.

**Before choosing, ask DFO IT:**
1. Is application control (AppLocker or WDAC) enforced on field laptops, and is it based on publisher, path or hash? Does it cover scripts (`.bat`) or DLLs?
2. Are executables blocked in user-writable folders (`%LOCALAPPDATA%`, `Downloads`, `%TEMP%`)?
3. Is a DFO code-signing certificate available, or does IT sign or package approved software (e.g. through Software Center/Intune)?

If IT can deploy it through their own software distribution, packaging and signing mostly become their job, and `--onedir` is the usual format for that.

PyInstaller builds (the first two options) must run on Windows, because PyInstaller doesn't cross-compile: use a GitLab Windows runner or a Windows VM. The launcher option needs no build: a CI job just zips the folder, adding the wheels if they're shipped, and can run on Linux.

## 6. Network access to msea.science
The lookups come from `https://msea.science/api/v2`, which is currently blocked from inside the DFO intranet. Three different problems can look like "the update fails", and they have different fixes.

**1. TLS inspection (certificate errors).** Many corporate networks decrypt HTTPS at a proxy and re-encrypt it with their own certificate authority, which IT installs into Windows. A program that doesn't trust that authority fails with `SSL: CERTIFICATE_VERIFY_FAILED`, even though Edge works fine.
- `requests` would fail this way, because it uses its own bundled certificate list (`certifi`). That's one reason the app uses the standard library's `urllib` instead.
- `urllib` loads the root certificates from the Windows certificate store, which usually covers the corporate authority. It still checks the certificates with OpenSSL rather than with Windows, though.
- **`truststore`** closes the remaining gaps. One call at startup (`truststore.inject_into_ssl()`) makes Python ask Windows to verify certificates, the same way Edge does. That includes enterprise trust settings and fetching missing intermediate certificates.
- Include it regardless: it's small, pure Python, and the right default on managed Windows machines.

**2. A proxy the app doesn't find.** If the intranet only reaches the internet through a proxy, the app has to use it.
- `requests` reads a manually configured Windows proxy, but not automatic configuration scripts (PAC/WPAD). It also can't log in to proxies that require Windows authentication.
- If that's the setup, use `pypac` (reads the PAC script and supports Windows authentication) or let the user enter a proxy in settings.
- Symptoms: timeouts or connection errors rather than certificate errors.

**3. A policy block.** If the firewall or proxy *forbids* msea.science, nothing in the app can or should get around it. `truststore` won't help here.
- Fix: ask IT to allow `msea.science` (only `GET` requests to `/api/v2/shared/people/` and `/api/v2/rov/instruments/` are needed).
- Interim: update the lookups on a network where msea.science is reachable, if that's permitted for the device. Lookups are cached and only refreshed on request, so the app works offline afterwards.

**How to tell which one you have:** open `https://msea.science/api/v2/shared/people/?detail=ref` in Edge on the intranet.
- If Edge shows a block page or can't connect, it's problem 3.
- If Edge works but the app fails with a certificate error, it's problem 1 (`truststore`).
- If Edge works but the app times out, it's problem 2 (proxy).

The update error dialog should show the underlying error, so users can tell these apart.

## 7. Phases (rough, one developer)
1. **Data layer and equivalence tests** (2–3 days): `db.py`, `lookups.py` (with `truststore` and proxy settings), `export.py`, `formats.py`.
2. **Generic table page and simple forms** (3–4 days): cruise, equipment configs, dive configs, read-only lookup pages, Update lookups.
3. **Dive/transect flow and Checks** (3–4 days): the nested transect dialog, time buttons, duplicate check, plots, warnings.
4. **Packaging** (1–2 days, more if signing or IT approval is involved): with the launcher option, `DiveLogging.bat`, `run.py`, pinned `requirements.txt`, and a CI job that builds the zip. Test on a clean Windows machine: without Python, first run online, first run offline, a later run offline, and an update that changes requirements. Plus settings and the data folder.
5. **Field trial** (one survey). The Shiny version has already been removed, so the trial checks the desktop app on its own.

About 2–3 weeks of development before the field trial, not counting IT approval.

## Open decisions
- ~~**One codebase or two?**~~ Decided: one. The Shiny/Docker version has been removed.
- **Packaging:** the launcher script with the user's installed Python is recommended (section 5). Confirm with DFO IT that `.bat` scripts and DLLs in user folders aren't restricted, and whether PyPI (or an internal mirror) is reachable. If PyPI isn't reachable, ship the wheels in the zip. If scripts or DLLs are restricted, fall back to a `--onedir` zip.
- **Network access:** allow-listing msea.science on the intranet, or an agreed procedure for updating lookups elsewhere (section 6).

## Implementation notes
Where the implementation differs from the plan above, and why:
- **No Qt Charts.** The charts are drawn with `QPainter` (`divelog/ui/charts.py`). Qt Charts lives in PySide6-Addons, about twice the download of PySide6-Essentials, for four simple charts.
- **Settings in a JSON file** (`settings.json` in the home folder) instead of `QSettings`. That keeps everything in one folder, which is easy to inspect, back up and test (`DIVELOG_HOME` moves it all).
- **Cruise sessions** replaced the single log in `home\data\` and **New survey** (see below).
- **Small behaviour changes,** listed in the README: duplicate names and invalid times are blocked, transects can be added while editing a dive, and Checks has two more warnings.
- **Garbage collection and threads.** The lookups download runs in a background thread. Python's garbage collector can run in any thread, and if it frees Qt widgets outside the GUI thread, their timers later fire at freed memory and crash the app (found by the tests). The app collects on the GUI thread and pauses collection while the download runs; dialogs are deleted on the GUI thread after use.
- **Tested on Windows** (Python 3.12, through WSL): first start online, a second start (no setup, about 2 s), Python not found (asks for the path and rejects the Microsoft Store stand-in), a failed update (keeps the old environment), the offline zip (installs from bundled wheels), and a lookups update from the real msea-rov-db API.
- **Not done yet:** a CI job for the tests and the zip, code signing, and updating `extract_log.py` for the ID-based log.

## Cruise sessions
Added after the first version, at the user's request: a cruise is loaded into a session, and everything entered applies to it.
- **One log per cruise.** The Cruises page creates a cruise (its log is created in the default log folder, `home\logs\` unless changed in settings), adds an existing log, selects the current cruise, edits a cruise, or removes it from the list (keeping the file).
- **The cruise list is in `settings.json`,** with each log's location, alongside the other settings. A cruise's properties (name, leg, start and end dates, ship, objective, summary, note) are in its log's `cruise` table, so the log describes itself and exports include them; the list keeps a copy of the name and leg so a missing log can still be shown.
- **Moving a log.** Editing a cruise can change its log's location. The user confirms the move; if they decline or it fails (e.g. the target exists or the drive is gone), the location is unchanged. A log moved outside the app can be located from the list.
- **No cruise or leg fields** on dives and transects. They still record `cruise_name` and `leg` (filled in from the cruise, and renamed with it), so exports and the importer keep working.
- **The ship belongs to the cruise** (as in the API's `Cruise.ship`), chosen from the platforms whose equipment type is "Ship". Dive configurations no longer choose a ship; platform configurations choose a sub (any other platform).
- **Last used.** New dives preselect the last dive configuration used, and new transects the last dive used (also when added from the Transects page). Both are remembered per cruise in the settings.

## Later changes
- **No Shiny compatibility.** The Shiny app is gone and its logs don't need to open, so the parts of the output contract that kept its format are dropped: the legacy `T-` times aren't read, the old-log guard and `diveconfig.ship_config` are gone, and the Shiny reference fixtures and comparison tests are removed. `extract_log.py` in msea-rov-db will be adapted to the new model.
- **Dive configurations** need only a name and a sub; ship and sub instruments are optional. A "+" beside each field opens the equipment configuration form, preset to a platform or an instrument, and chooses the new configuration.
- **Times** use a date-time picker (calendar drop-down, UTC) with a **Now** button.
- **Configuration properties** (the variables an equipment configuration can set, with units and descriptions) are kept in `settings.json`, seeded from `config-variables.csv`, and edited from **Settings > Configuration Properties** or a "+" beside the variable drop-down, which then selects the property just added.
