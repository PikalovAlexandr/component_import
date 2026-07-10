#!/usr/bin/env bash
# Ежедневный бэкап (НД-2 ТЗ): БД + вложения Part-DB + Gitea. Ротация 30 дней.
# cron: 30 2 * * * /opt/component/scripts/backup.sh >> /var/log/component-backup.log 2>&1
set -euo pipefail
DIR="${BACKUP_DIR:-/opt/component/backups}"
STAMP=$(date +%Y%m%d_%H%M%S)
mkdir -p "$DIR/$STAMP"
cd "$(dirname "$0")/.."
PROJECT=$(basename "$PWD")

echo "[$STAMP] БД PostgreSQL..."
# stderr docker exec направляем в /dev/null: при -T без TTY предупреждения
# docker (напр. «version obsolete») смешиваются с бинарным stdout pg_dump и
# ломают дамп (сигнатура PGDMP затирается → pg_restore падает).
docker compose exec -T database pg_dump -U partdb -Fc partdb > "$DIR/$STAMP/partdb.dump" 2>/dev/null

echo "[$STAMP] Вложения Part-DB (ТУ, datasheet, SPICE, прайсы)..."
docker run --rm -v "${PROJECT}_partdb_uploads":/src:ro -v "$DIR/$STAMP":/dst alpine tar czf /dst/uploads.tgz -C /src .
docker run --rm -v "${PROJECT}_partdb_media":/src:ro   -v "$DIR/$STAMP":/dst alpine tar czf /dst/media.tgz -C /src .

echo "[$STAMP] Gitea (репозитории графики и 3D)..."
docker run --rm -v "${PROJECT}_gitea_data":/src:ro -v "$DIR/$STAMP":/dst alpine tar czf /dst/gitea.tgz -C /src .

find "$DIR" -mindepth 1 -maxdepth 1 -type d -mtime +30 -exec rm -rf {} \;
echo "[$STAMP] Готово: $DIR/$STAMP"
