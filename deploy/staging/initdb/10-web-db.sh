#!/bin/sh
# First start only: a separate database for web/'s Auth.js tables, so they
# never mix with the API server's schema.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -c 'CREATE DATABASE holt_web'
