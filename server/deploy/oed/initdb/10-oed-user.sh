#!/bin/sh
# DRAFT, NOT TESTED.
# Runs once, when the PostgreSQL data folder is empty (official postgres image).
# Same as OED v1.0.0 containers/database/init.sql, but the password comes from oed.env
# instead of the fixed "opened". OED's own file makes "oed" a superuser: kept as it is.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -v oedpw="$OED_DB_PASSWORD" <<'EOSQL'
CREATE USER oed WITH SUPERUSER PASSWORD :'oedpw';
CREATE DATABASE oed WITH OWNER oed;
EOSQL
