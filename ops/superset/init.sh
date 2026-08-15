#!/bin/sh
set -e
superset db upgrade
superset fab create-admin \
  --username admin --firstname Admin --lastname User \
  --email admin@example.com --password "$SUPERSET_ADMIN_PASSWORD" || true
superset init
