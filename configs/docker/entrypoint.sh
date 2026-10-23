#!/bin/sh
# Shiny Server doesn't pass the container's environment to the app, so write
# the app's settings to the shiny user's .Renviron, which R reads on start-up.
set -e
{
  echo "DIVELOG_DATA_DIR=${DIVELOG_DATA_DIR}"
  echo "MSEA_API_URL=${MSEA_API_URL}"
} > "${HOME:-/home/shiny}/.Renviron"
exec "$@"
