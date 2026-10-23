# Lookups of people and instruments, from the MSEA ReST API (msea-rov-db).
# They are cached in a SQLite file because the app is often used offline, and
# are only refreshed when the user asks. A failed refresh leaves the cache as it was.

# Packages
library(RSQLite)
library(httr2)
library(purrr)


# Create the lookup tables in the db at 'dbname' if they don't exist. They
# start empty and are filled by update_lookups().
create_lookups_db <- function(dbname) {
  mydb <- dbConnect(RSQLite::SQLite(), dbname)
  on.exit(dbDisconnect(mydb))

  dbExecute(mydb, 'CREATE TABLE IF NOT EXISTS people (
                     id INTEGER PRIMARY KEY, first_name TEXT NOT NULL, last_name TEXT NOT NULL)')
  dbExecute(mydb, 'CREATE TABLE IF NOT EXISTS instruments (
                     id INTEGER PRIMARY KEY, name TEXT, serial_number TEXT NOT NULL,
                     brand TEXT, model TEXT, type TEXT, retired TEXT)')
  # One row: when and from where the lookups were last updated
  dbExecute(mydb, 'CREATE TABLE IF NOT EXISTS lookups_info (updated_on TEXT NOT NULL, source TEXT NOT NULL)')
  invisible(NULL)
}


# Get all records from a paginated list endpoint. The API returns
# {count, next, previous, results}; pages are requested by number rather than
# by following 'next', which is built from the Host header the API sees.
fetch_all <- function(url) {
  results <- list()
  page <- 1
  repeat {
    body <- request(url) |>
      req_url_query(detail = 'ref', count = 500, page = page) |>
      req_timeout(30) |>
      req_perform() |>
      resp_body_json()
    results <- c(results, body$results)
    if(is.null(body[['next']])) break
    page <- page + 1
  }
  results
}

# Pull a (possibly nested, possibly null) field from each record
field <- function(records, ..., type = character(1)) {
  vapply(records, function(x) as(pluck(x, ..., .default = NA), class(type)), type)
}

# Download people and instruments from the API at 'api_url' (e.g. http://localhost/api/v2).
# Stops on any error, including an empty list.
fetch_lookups <- function(api_url) {
  people <- fetch_all(paste0(api_url, '/shared/people/'))
  instruments <- fetch_all(paste0(api_url, '/rov/instruments/'))
  if(length(people) == 0) stop('The API returned no people.')
  if(length(instruments) == 0) stop('The API returned no instruments.')

  list(
    people = data.frame(id = field(people, 'id', type = integer(1)),
                        first_name = field(people, 'first_name'),
                        last_name = field(people, 'last_name')),
    instruments = data.frame(id = field(instruments, 'id', type = integer(1)),
                             name = field(instruments, 'name'),
                             serial_number = field(instruments, 'serial_number'),
                             brand = field(instruments, 'model', 'brand_name'),
                             model = field(instruments, 'model', 'model_name'),
                             type = field(instruments, 'model', 'equipment_type', 'name'),
                             retired = field(instruments, 'retired'))
  )
}

# Replace the lookups in the db at 'dbname' with the API's. Everything is
# downloaded before the db is touched, and the replacement is one transaction.
# Returns the number of people and instruments.
update_lookups <- function(dbname, api_url) {
  api_url <- sub('/+$', '', api_url)
  lookups <- fetch_lookups(api_url)

  mydb <- dbConnect(RSQLite::SQLite(), dbname)
  on.exit(dbDisconnect(mydb))
  dbWithTransaction(mydb, {
    for(i in c('people', 'instruments')){
      dbExecute(mydb, sprintf('DELETE FROM "%s"', i))
      dbAppendTable(mydb, i, lookups[[i]])
    }
    dbExecute(mydb, 'DELETE FROM lookups_info')
    dbAppendTable(mydb, 'lookups_info',
                  data.frame(updated_on = format(Sys.time(), '%Y-%m-%d %H:%M UTC', tz = 'UTC'),
                             source = api_url))
  })

  sapply(lookups, nrow)
}
