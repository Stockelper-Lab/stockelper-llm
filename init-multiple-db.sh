#!/bin/bash
set -e

# stockelper-llm에서 사용하는 DB 3종을 생성합니다.
# - stockelper_web: 사용자/자격증명(users)
# - checkpoint: LangGraph 체크포인터
# - ksic: (선택) 산업분류

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    CREATE DATABASE stockelper_web;
    CREATE DATABASE checkpoint;
    CREATE DATABASE ksic;
EOSQL

