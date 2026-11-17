# Bootstrap SQL

Canonical location: `apps/backend/db/bootstrap/sql`

This directory is the source of truth for the initial installation executed by the frontend through `/setup/installation`.

## Standard

- One primary table per file.
- The file name defines the execution order.
- Files are grouped by dependency and domain in this order:
  - core
  - file catalog and file storage
  - chat
  - agent
  - ingest
- Each file may include:
  - `CREATE TABLE`
  - related indexes
  - `SEQUENCE`
  - `TRIGGER`
  - minimal seed data
- The `--` separator is preserved because it is used by the setup parser.

## Notes

- Keep operational compatibility with the frontend installation flow.
- The only source of truth is `apps/backend/db/bootstrap/sql`.
