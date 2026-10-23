# NDST Dive Logging App

Note: This project has been imported to DFO MSEA's gitlab page. You can find the version that is still being activitely developed here: https://gitlab.com/dfo-msea/Dive-Logging-App

__Main author:__  Jessica Nephin     
__Contact:__      jessica.nephin@dfo-mpo.gc.ca

- [Objective](#objective)
- [Summary](#summary)
- [Status](#status)
- [Contents](#contents)
- [Methods](#methods)
- [Requirements](#requirements)

## Objective
To provide a user interface for logging survey events (dives and transects) during field operations by the Non-Destructive Survey Tools program

## Summary
The user interface is written with R shiny. The app allows users to add, edit and delete dives and transects and associated metadata (e.g., personnel, configurations). All data logged with the app are saved in an sqlite database. Data can also be exported to csv using the export button on the dashboard header.

## Status
Under development

## Contents

### app.R
The R shiny app. The app allows users to add, edit and delete records in cruise, equipment configuration, dive configuration, dives, and transect tables. The app can be started and stopped multiple times without resulting in data loss. The data from each session are continually saved to the sqlite db. No data loss will result from a crash unless any form data was left un-submitted. Other inputs are the lookups db (see lookups.R) and config-variables.csv.

The log db (`divelogging-db.sqlite`), lookups db (`lookups.sqlite`) and the `Exports` folder are kept in the folder given by the `DIVELOG_DATA_DIR` environment variable, or the working directory if it isn't set.

### db.R
Creates the tables of the log db. The app creates `divelogging-db.sqlite` on start-up if it doesn't exist, so to start a new survey, move the old db file out of the way. Logs made by earlier versions of the app (which referenced equipment by short code) can't be opened.

### lookups.R
People and instruments are lookups downloaded from the MSEA ReST API (msea-rov-db) at `MSEA_API_URL` (default `http://localhost/api/v2`): `/shared/people/` and `/rov/instruments/`. The log stores their IDs: dive pilots are a `;`-separated list of person IDs and equipment configurations have an `instrument_id`. The user sees people's first and last names, and instruments' names and serial numbers.

Because the app is often used offline, the lookups are cached in `lookups.sqlite` and only refreshed when the user clicks **Update lookups**. Everything is downloaded before the cache is touched, and the cache is replaced in one transaction, so a failed update leaves the lookups as they were. The cache starts empty, so update the lookups before first use. Exports include the lookups as `people.csv` and `instruments.csv`.


## Deployment
The app runs in a Docker container under Shiny Server as the `shiny` user, behind an nginx reverse proxy.

1. Build and start the container: `docker compose up -d --build`. It listens on `127.0.0.1:3841` only (3838-3840 are used by integrated_gf_shiny, shiny-qc and future_habitats_gf_shiny) and restarts automatically.
2. Add the location blocks in `configs/nginx/dive_logging.conf` to the site's nginx `server { }` block, then `sudo nginx -t && sudo systemctl reload nginx`. The app is served at `/dive_logging/`.

The log db, lookups db and exports are in `./data`, which is mounted into the container. The container's `shiny` user is given UID/GID 1000 to match the owner of `./data`; set `DIVELOG_UID` and `DIVELOG_GID` when building if the owner is different.

The API defaults to `http://host.docker.internal/api/v2`, i.e. an msea-rov-db stack running on the same host. To use another, set `MSEA_API_URL` (e.g. in a `.env` file next to `docker-compose.yml`) and rerun `docker compose up -d`. The API's `ALLOWED_HOSTS` must include the host name in that URL.

Logs: `docker compose logs -f`. To update, pull the changes and rerun `docker compose up -d --build`.


## Requirements
R version 4.2.1 or greater (the image uses 4.5.1)
shiny, shinydashboard, shinyjs, DT, RSQLite, pool, uuid, dplyr, purrr, ggplot2, httr2
sqlite3
