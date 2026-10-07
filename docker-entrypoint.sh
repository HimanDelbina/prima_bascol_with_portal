#!/bin/sh
set -e

# Wait for PostgreSQL database to be reachable
echo "Waiting for PostgreSQL database at ${POSTGRES_HOST:-db}:${POSTGRES_PORT:-5432}..."

python << 'EOF'
import os
import sys
import time
import psycopg

host = os.environ.get('POSTGRES_HOST', 'db')
port = int(os.environ.get('POSTGRES_PORT', 5432))
user = os.environ.get('POSTGRES_USER', 'postgres')
password = os.environ.get('POSTGRES_PASSWORD', '')
dbname = os.environ.get('POSTGRES_DB', 'prima_bascol')

max_retries = 30
for attempt in range(1, max_retries + 1):
    try:
        conn = psycopg.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname=dbname,
            connect_timeout=3
        )
        conn.close()
        print(f"Database connection successful on attempt {attempt}.")
        sys.exit(0)
    except Exception as err:
        print(f"Attempt {attempt}/{max_retries}: Database unavailable ({err}). Retrying in 2 seconds...")
        time.sleep(2)

print("Error: Could not connect to PostgreSQL database after maximum retries.")
sys.exit(1)
EOF

echo "PostgreSQL is ready."

# Automatically apply database migrations on startup
echo "Applying database migrations..."
python manage.py migrate --noinput

# Execute the given command
exec "$@"
