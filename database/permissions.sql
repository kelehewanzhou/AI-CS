-- Deprecated compatibility entry point; use runtime_grants.sql or python -m cli.migrate.
-- psql resolves this include relative to this file. No independent grants live here.
\set ON_ERROR_STOP on
\ir runtime_grants.sql
