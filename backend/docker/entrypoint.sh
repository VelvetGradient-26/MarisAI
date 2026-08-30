#!/bin/sh
set -e

if [ -n "$DATABASE_URL" ]; then
    echo "Running database migrations..."
    alembic upgrade head
else
    echo "DATABASE_URL not set — skipping migrations (chat persistence disabled)."
fi

echo "Starting application..."
exec "$@"
