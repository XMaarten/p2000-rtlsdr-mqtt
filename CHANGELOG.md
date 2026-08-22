# Changelog

## 0.2.0

- Use `XMaarten/p2000-capcodes` as the only supported capcode source artifact.
- Remove the legacy Bommel CSV importer.
- Split storage into replaceable `/data/capcodes.sqlite3` and local `/data/runtime.sqlite3`.
- Query enriched capcode metadata directly from the downloaded reference database.
- Keep route history, geocode cache and updater metadata exclusively in the runtime database.
- Validate downloads with SQLite `PRAGMA quick_check`, required tables/columns and record count.
- Install validated reference database updates atomically with `os.replace()`.
- Read the abbreviation table directly from the reference database.
