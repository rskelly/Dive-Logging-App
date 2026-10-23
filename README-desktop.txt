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
Click "Update lookups" while connected to the network. This downloads the people and
instruments from the MSEA database. The app keeps them, so it works offline
afterwards. Update again whenever people or instruments change. If an update fails,
the existing lookups are kept.

Your data
---------
The log, the lookups and the exports are in
    %LOCALAPPDATA%\DiveLogging\data
("Open data folder" in the app opens it; Settings can move it). Updating the app
doesn't touch them. To start a new survey, use "New survey": the current log is
renamed and kept, and an empty one is started.

Settings
--------
- MSEA API URL: where the lookups come from (default https://msea.science/api/v2).
- Proxy: leave empty to use Windows' settings.
- Data folder.
