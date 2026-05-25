#!/bin/sh
set -e

mkdir -p /app/data /app/media /app/staticfiles

if [ "$DATABASE_ENGINE" = "mysql" ]; then
  python - <<'PY'
import os
import time

import MySQLdb

host = os.environ.get("DATABASE_HOST", "db")
port = int(os.environ.get("DATABASE_PORT", "3306"))
user = os.environ.get("DATABASE_USER", "")
password = os.environ.get("DATABASE_PASSWORD", "")
database = os.environ.get("DATABASE_NAME", "")

for attempt in range(1, 31):
    try:
        connection = MySQLdb.connect(
            host=host,
            port=port,
            user=user,
            passwd=password,
            db=database,
            connect_timeout=5,
        )
        connection.close()
        print("MySQL disponivel.")
        break
    except Exception as exc:
        print(f"Aguardando MySQL ({attempt}/30): {exc}")
        time.sleep(2)
else:
    raise SystemExit("MySQL nao ficou disponivel dentro do tempo esperado.")
PY
fi

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec "$@"
