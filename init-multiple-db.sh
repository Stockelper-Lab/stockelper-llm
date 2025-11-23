#!/bin/bash
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    CREATE DATABASE llm_users;
    CREATE DATABASE checkpoint;
    CREATE DATABASE ksic;
EOSQL
