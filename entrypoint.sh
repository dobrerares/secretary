#!/bin/sh
set -e

alembic upgrade head

exec uvicorn secretary.main:app --host 0.0.0.0 --port 8000
