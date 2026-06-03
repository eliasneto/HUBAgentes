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

# Cria migrations para mudancas de model ainda nao mapeadas
python manage.py makemigrations --no-input

# Aplica todas as migrations pendentes
python manage.py migrate --noinput

python manage.py collectstatic --noinput

# Cria superusuario padrao se nao existir nenhum admin
python - <<'PY'
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()
from django.contrib.auth.models import User
if not User.objects.filter(is_superuser=True).exists():
    User.objects.create_superuser(
        username=os.environ.get("DJANGO_ADMIN_USER", "admin"),
        password=os.environ.get("DJANGO_ADMIN_PASSWORD", "admin"),
        email="",
    )
    print("Superusuario criado:", os.environ.get("DJANGO_ADMIN_USER", "admin"))
else:
    print("Superusuario ja existe, nenhum criado.")
PY

exec "$@"
