NDST Dive Logging App
=====================

Starting the app
----------------
1. Extract this zip anywhere you can write to, for example your Documents folder.
   If Windows warns about files from the internet, right-click the zip, choose
   Properties, tick "Unblock", and extract again.
2. Double-click DiveLogging.bat.

The app needs Python 3.10 or later. If it can't find Python, it tells you how to
install it (from python.org; the per-user install needs no administrator rights)
or lets you type the path to python.exe.

The first start installs the app's libraries and needs network access. It takes a
few minutes. After that the app starts in seconds and works offline. Start it once
before going to the field, and again after installing a new version.

Before logging dives
--------------------
1. Click "Update lookups" while connected to the network. This downloads the people,
   instruments and platforms (ships and subs) from the MSEA database. The app keeps
   them, so it works offline afterwards. Update again whenever they change. If an
   update fails, the existing lookups are kept.
2. On the Cruises page, click "New cruise", fill in the cruise (name, leg, dates,
   ship, ...) and submit. Each cruise gets its own log file.
3. Everything you enter from then on (configurations, dives, transects) goes into the
   selected cruise. To switch cruises, select another one on the Cruises page. The
   app reopens the last cruise when it starts.

Your data
---------
Each cruise's log is created in
    %LOCALAPPDATA%\DiveLogging\logs
(Settings can change this folder for new cruises). To keep a log somewhere else,
for example on a USB drive, edit the cruise and change its log file: the app asks
before moving it. "Open log folder" opens the current cruise's folder; exports are
saved there, in Exports. "Open log file" on the Cruises page adds a log made on
another computer. Updating the app doesn't touch your logs.

Settings
--------
- MSEA API URL: where the lookups come from (default https://msea.science/api/v2).
- Proxy: leave empty to use Windows' settings.
- Default log folder: where new cruises' logs are created.
