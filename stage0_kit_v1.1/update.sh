#!/usr/bin/env bash
# Обновление системы (НФ-1а ТЗ): пре-бэкап -> новые образы -> миграции БД.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "1/4 Пре-бэкап (обязателен перед миграцией)"; ./scripts/backup.sh
echo "2/4 Загрузка образов";                       docker compose pull
echo "3/4 Перезапуск";                             docker compose up -d
echo "4/4 Миграции схемы БД Part-DB"
docker compose exec partdb php bin/console doctrine:migrations:migrate --no-interaction
echo "Готово. Откат: docker compose down; ./scripts/restore.sh <последний_бэкап>; закрепить прежний тег образа."
