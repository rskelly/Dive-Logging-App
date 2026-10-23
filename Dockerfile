# NDST Dive Logging Shiny app, served by Shiny Server as user "shiny".
# Meant to sit behind a reverse proxy; see configs/nginx/dive_logging.conf.
#
#   docker compose up -d --build

# rocker/shiny installs CRAN binaries from a dated snapshot matching the R
# version, so package versions stay fixed for a given tag.
FROM rocker/shiny:4.5.1

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

RUN install2.r --error --skipinstalled \
      DT RSQLite pool shinyjs uuid dplyr shinydashboard purrr ggplot2 httr2

# The log db, lookups db and exports are kept in /data, which is bind-mounted
# from the host. Give "shiny" the host user's IDs so both can write there.
ARG SHINY_UID=1000
ARG SHINY_GID=1000
RUN groupmod -g ${SHINY_GID} shiny \
 && usermod -u ${SHINY_UID} -g ${SHINY_GID} shiny

RUN rm -rf /srv/shiny-server/* \
 && mkdir -p /var/log/shiny-server /var/lib/shiny-server /data \
 && chown -R shiny:shiny /var/log/shiny-server /var/lib/shiny-server /data

COPY configs/docker/shiny-server.conf /etc/shiny-server/shiny-server.conf
COPY configs/docker/entrypoint.sh /usr/local/bin/entrypoint.sh

WORKDIR /srv/shiny-server/app
COPY app.R db.R lookups.R config-variables.csv ./

# send app logs to the container log (docker logs / docker compose logs)
ENV SHINY_LOG_STDERR=1
ENV DIVELOG_DATA_DIR=/data

USER shiny
EXPOSE 3841
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s \
  CMD curl -fsS http://localhost:3841/ > /dev/null || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["/usr/bin/shiny-server"]
