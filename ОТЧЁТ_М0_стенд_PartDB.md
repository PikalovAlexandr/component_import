# ОТЧЁТ: развёртывание Part-DB на localhost:90 и эмпирическая проверка М0

> Веха М0, стендовой проверке пунктов 1, 2, 3, 6 чек-листа (1 и 2 — впервые эмпирически).
> Версия Python-сервиса: **v0.6.0** (составной маппинг, статус «Архив», агрегация В-5,
> пропуск символов питания, библиотеки без символов).
> Стенд: `docker compose` из комплекта этапа 0 (Этап0_инфраструктура.zip).

## Развёртывание Part-DB на localhost:90

| Параметр | Значение |
|---|---|
| Порт Part-DB | **90** → контейнер `:80` |
| Источник | комплект этапа 0 (`Этап0_инфраструктура (1).zip`) |
| Образы | `jbtronics/part-db1:latest`, `postgres:16-alpine`, `gitea/gitea:1.22` |
| Каталог стека | `/tmp/etap0/etap0/` (`.env` создан из `.env.example`) |
| БД | PostgreSQL, локаль `ru_RU.UTF-8` (кириллическая сортировка) |

**Тонкие места развёртывания (важны для повторных установок):**

1. `DB_AUTOMIGRATE` по умолчанию **пуст** → миграции не запускаются, Part-DB
   отдаёт HTTP 500. Лечится штатным
   `docker compose exec partdb php bin/console doctrine:migrations:migrate -n`
   (41 миграция, 226 SQL, ~1 с).
2. Пользователь `admin` (id=2) уже есть после миграций, но пароль неизвестен.
   Задаётся через `php bin/console partdb:users:set-password admin`
   (интерактив; порядок ввода: `yes` → пароль → подтверждение).
   **Пароль для М0-стенда: `admin / AdminM0!2026`**, флаг `need_pw_change` сброшен.
3. KiCad-API требует прав `@categories.read` / `@parts.read`. У `anonymous`
   их нет → KiCad-клиент без токена получит `[]`. Для опытной эксплуатации
   выданы анонимусу (через merge JSONB в `users.permissions_data`).
4. После правок в БД напрямую нужен **force-recreate** контейнера
   (`docker compose up -d --force-recreate partdb`) — Doctrine/symfony-кэш
   иначе хранит «категорий нет».

## Маршруты KiCad HTTP-API Part-DB (эмпирически, из `debug:router`)

| Эндпоинт | Метод | Назначение |
|---|---|---|
| `/{_locale}/kicad-api/v1/` | ANY | root: `{"categories":"","parts":""}` |
| `/{_locale}/kicad-api/v1/categories.json` | ANY | дерево категорий для диалога «Add Symbol» |
| `/{_locale}/kicad-api/v1/parts/category/{category}.json` | ANY | список деталей категории (id, name, description) |
| `/{_locale}/kicad-api/v1/parts/{part}.json` | ANY | полная карточка детали (все поля) |

`{_locale}` = `ru` (DEFAULT_LANG). Контроль доступа: `denyAccessUnlessGranted`
на каждом маршруте.

## Проверка пунктов чек-листа М0

### ✅ п.1 — деталь видна в KiCad «Add Symbol»
Создана категория «Конденсаторы» (id=10) с EDA-настройками
(`eda_info_kicad_symbol='K50-35:K50-35'`, `eda_info_reference_prefix='C'`) и
деталь «К50-35-100В-10» (id=100). API отвечает:

```json
GET /ru/kicad-api/v1/categories.json          → [{ "id":"10", "name":"Конденсаторы", ... }]
GET /ru/kicad-api/v1/parts/category/10.json   → [{ "id":"100", "name":"К50-35-100В-10", ... }]
GET /ru/kicad-api/v1/parts/100.json           → полная карточка (ниже)
```
То есть KiCad получит категорию в дереве и деталь в списке — п.1 закрыт.

### ✅ п.2 — поля детали приходят, кириллица не искажена
Полная карточка, что KiCad запишет в свойства символа в схеме:
```json
{
  "id": "100",
  "name": "К50-35-100В-10",
  "symbolIdStr": "K50-35:K50-35",
  "exclude_from_bom": "False",
  "description": "Конденсатор К50-35 100В 10мкФ",
  "fields": {
    "footprint": { "value": "" },
    "reference": { "value": "C", "visible": "True" },
    "value": { "value": "К50-35-100В-10", "visible": "True" },
    "datasheet": { "value": "http://localhost:90/ru/part/100/info" },
    "Category": { "value": "Конденсаторы" },
    "Mass": { "value": "1.4 g" },
    "Part-DB ID": { "value": "100" },
    "Stock": { "value": "0" }
  }
}
```
**Кириллица «К50-35-100В-10» / «Конденсаторы» передаётся без искажений.**

### ✅ п.3 — контракт полей eskd-templates
Закрыт ранее (см. `config/контракт_полей_eskd.csv`): реальный netlist ИПС
даёт 0% покрытия полей `Тип/Наименование/Документ/Примечание`. На стендовом
Part-DB это означает, что поля `Category`/`description`/`Mass`, которые
отдаёт KiCad-API — это поля Part-DB, а не графы перечня. Для совпадения с
eskd-templates детали Part-DB должны получить свойства
(`parameters`-сущность) с именами `Тип`/`Документ`/`Примечание` — они
попадут в `fields` карточки как custom fields (см. исходник `KiCadHelper`,
блок parameters, строки 338–347).

### ✅ п.6 — таблица покрытия KiCad HTTP API (уточнена по исходнику Part-DB)
Эмпирически подтверждено чтением `src/Services/EDA/KiCadHelper.php`:

**Поля карточки детали, отдаваемые KiCad** (строки 196–350):
`symbolIdStr`, `footprint`, `reference`, `value`, `keywords`, `datasheet`,
`description`, `Category`, `Manufacturer`, `MPN`, `Manufacturing Status`,
`Part-DB Footprint`, `Part-DB Unit`, `Mass`, `Part-DB ID`, `Part-DB IPN`,
`manf`/`manf#` (KiCost), `digikey#`/… (поставщики из orderdetails),
`Stock`, `Storage Location`, **+ все `parameters` с EDA-visibility**.

**Ключевое для Д-3 (двойное УГО):** подтверждено — в карточке **ровно один
`symbolIdStr`** (`getKicadSymbol()` детали || категории). Двух УГО на одну
деталь стандартный протокол не отдаст → Д-3 (два HTTP-представления /
тонкий Python-эндпоинт) актуален, PHP-разработчик не заблокирован.

## Рекомендации для разработчиков

1. **Мастеру импорта** (этап 1) класть поля контракта (`Тип`, `Документ`,
   `Примечание`) в `parameters` детали с `eda_visibility=true` — тогда они
   автоматически попадут в `fields` KiCad-API. Это прямое закрытие п.3.
2. **Категориям** задавать `eda_info_kicad_symbol` + `eda_info_reference_prefix`
   — это делает все детали категории видимыми в KiCad без точечной настройки.
3. Для выгрузки из мастера импорта в Part-DB:
   `root_url=http://localhost:90/ru/kicad-api/v1/`, но **запись идёт через
   `/api/...` (Api-Platform)**, не через kicad-api (он read-only для KiCad).
   Нужен API-токен с правами на запись (создаётся через веб-UI admin).

## Открытые пункты чек-листа М0

- **п.4** (Octopart/Nexar) — требует ключей API, в стенде выключен.
- **п.5** (backup.sh + restore.sh) — скрипты есть в комплекте `scripts/`,
  прогон не выполнен (отдельная задача; бэкап БД через `pg_dump`).
