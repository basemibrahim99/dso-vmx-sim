#!/bin/bash
# Runs once, automatically, on first Postgres container init (docker-entrypoint-initdb.d).
# Creates the second database used as the actual warehouse -- kept separate
# from Airflow's own metadata database.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE dso;
EOSQL
