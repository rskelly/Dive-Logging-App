# Create the tables of the dive logging database

# Packages
library(RSQLite)


# Create any missing tables in the log db at 'dbname'. The app calls this on
# start-up, so a new survey starts by moving the old db file out of the way.
# People and instruments are not stored here: they are lookups (see lookups.R)
# and the log stores their IDs.
create_log_db <- function(dbname) {

  # Create or open db
  mydb <- dbConnect(RSQLite::SQLite(), dbname)
  on.exit(dbDisconnect(mydb))

  # Logs made before the lookups came from the API reference equipment by short code
  if(dbExistsTable(mydb, 'equipconfig') && !'instrument_id' %in% dbListFields(mydb, 'equipconfig')){
    stop('"', dbname, '" was created by an older version of the app ',
         '(equipment configurations use short codes). Move it aside to start a new log.')
  }

  # Empty tables to fill
  cruise <- data.frame(row_id=character(),name=character(0),leg=character(0),
                       objective=character(0), summary=character(0), note=character(0))
  # pilot is a ';'-separated list of person IDs
  dives <- data.frame(row_id=character(),cruise_name=character(0),leg=character(0),
                      name=character(0),pilot=character(0),start_time=character(0),
                      end_time=character(0),site_name=character(0),dive_config=character(0),
                      objective=character(0),summary=character(0),note=character(0))
  transects <- data.frame(row_id=character(),cruise_name=character(0),leg=character(0),
                          dive_name=character(0),name=character(0),start_time=character(0),
                          end_time=character(0),objective=character(0),summary=character(0),note=character(0))
  equipconfig <- data.frame(row_id=character(),name=character(0),instrument_id=integer(0),
                            type=character(0),configuration=character(0),note=character(0))
  diveconfig <- data.frame(row_id=character(),name=character(0),ship_config=character(0),
                           sub_config=character(0), ship_instrument_configs=character(0),
                           sub_instrument_configs=character(0),note=character(0))
  tables <- list(cruise=cruise, dives=dives, transects=transects,
                 equipconfig=equipconfig, diveconfig=diveconfig)

  # Write tables that don't exist yet
  for(i in names(tables)){
    if(!dbExistsTable(mydb, i)) dbWriteTable(mydb, i, tables[[i]])
  }
}
