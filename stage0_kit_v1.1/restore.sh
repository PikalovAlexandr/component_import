#!/usr/bin/env bash
# Восстановление из бэкапа (проверка — ежеквартально, НД-2; норматив ПИ-8: <= 4 ч).
# Использование: ./restore.sh /opt/component/backups/20260703_023000
set -euo pipefail
SRC="$1"
cd "$(dirname "$0")/.."
PROJECT=$(basename "$PWD")
docker compose up -d database 2>/dev/null && sleep 5
# stderr docker (предупреждения про version) глушим, stderr psql/pg_restore — оставляем:
docker compose exec -T database psql -U partdb -d postgres 2>/dev/null \
  -c "DROP DATABASE IF EXISTS partdb;" -c "CREATE DATABASE partdb OWNER partdb;"
docker compose exec -T database pg_restore -U partdb -d partdb < "$SRC/partdb.dump" 2>/dev/null
docker run --rm -v "${PROJECT}_partdb_uploads":/dst -v "$SRC":/src:ro alpine sh -c "rm -rf /dst/* && tar xzf /src/uploads.tgz -C /dst"
docker run --rm -v "${PROJECT}_partdb_media":/dst   -v "$SRC":/src:ro alpine sh -c "rm -rf /dst/* && tar xzf /src/media.tgz -C /dst"
docker run --rm -v "${PROJECT}_gitea_data":/dst     -v "$SRC":/src:ro alpine sh -c "rm -rf /dst/* && tar xzf /src/gitea.tgz -C /dst"
docker compose up -d
echo "Восстановлено из $SRC. Проверьте вход в Part-DB и открытие детали с вложением."
