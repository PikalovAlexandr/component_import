# Подключение KiCad к стенду системы «КОМПОНЕНТ» (веха М0)

Стенд:
- **Part-DB** (метаданные деталей): http://localhost:90  (admin / AdminM0!2026)
- **Gitea** (графика символов/футпринтов/3D): http://localhost:3000  (libraries / LibM0!2026)
- Репозитории графики: `kicad-libs/symbols`, `kicad-libs/footprints`, `kicad-libs/3dmodels`
  (файлы по сериям в подпапках: `K50-35/K50-35.kicad_sym`, `K50-35/K50-35.pretty/`, `K50-35/K50-35.3dshapes/`)

## Как это устроено (важно)

По [спецификации HTTP Libraries](https://dev-docs.kicad.org/en/apis-and-binding/http-libraries/index.html)
Part-DB отдаёт **только lib_id** (ссылку), а сама графика лежит в **отдельной**
библиотеке. Поэтому подключаются ДВА источника:

1. **HTTP-библиотека Part-DB** → даёт дерево категорий + список деталей + поля.
2. **GIT-библиотека Gitea** (HTTP-Git) → даёт сами УГО и футпринты по lib_id.

## Шаг 1. Подключить графику из Gitea (GIT-библиотеки)

### УГО (символы)
Eeschema → **Preferences → Manage Symbol Libraries** → **Add**:
- Nickname: `K50-35`
- Type: `GIT`
- URI: `http://libraries@localhost:3000/kicad-libs/symbols.git`//* /K50-35/K50-35.kicad_sym
  (при первом обращении KiCad спросит пароль — использовать **API-токен**, не пароль: см. ниже)

Альтернатива (если ваша версия KiCad не поддерживает GIT-тип) — клонируйте локально:
```
git clone http://libraries@localhost:3000/kicad-libs/symbols.git ~/kicad-libs/symbols
```
и подключайте как обычную файловую:
- Type: `KiCad`
- URI: `/home/<user>/kicad-libs/symbols/K50-35/K50-35.kicad_sym`

### Футпринты
PcbNew → **Preferences → Manage Footprint Libraries** → **Add**:
- Nickname: `K50-35`
- Type: `KiCad` (из локального клона)
- URI: `/home/<user>/kicad-libs/footprints/K50-35/K50-35.pretty`

## Шаг 2. Подключить Part-DB (HTTP-библиотека метаданных)

Eeschema → **Preferences → Manage Symbol Libraries** → **Add**:
- Nickname: `КОМПОНЕНТ`
- Type: `HTTP`
- URI: путь к файлу `config/КОМПОНЕНТ.kicad_httplib`
  (в нём `root_url: http://localhost:90/ru/kicad-api/`, `api_version: v1`)

## Шаг 3. Проверить

В Eeschema **Add Symbol** → раскрыть **КОМПОНЕНТ** → категория **Конденсаторы** →
деталь **K50-35-100В-10**. УГО подгрузится из Gitea-репо `symbols`, посадочное
место `8X2.5` — из `footprints`, а поля (reference=C, value, Category, Mass и т.д.)
— из Part-DB.

## API-токен для GIT-аутентификации

Токен создаётся в Gitea:右上角 → Settings → Applications → Generate New Token,
scopes: `read:repository`, `write:repository`. Сохранённый токен М0:
`/tmp/gitea_token.txt` (для стенда; в продакшене — отдельный токен на роль
«KiCad-клиент» с правом только на чтение).

## Строки для sym-lib-table / fp-lib-table (готовые)

`~/.config/kicad/<version>/sym-lib-table`:
```
(lib (name "K50-35")(type "KiCad")(uri "/home/<user>/kicad-libs/symbols/K50-35/K50-35.kicad_sym")(options "")(descr "K50-35 symbols"))
```

`~/.config/kicad/<version>/fp-lib-table`:
```
(lib (name "K50-35")(type "KiCad")(uri "/home/<user>/kicad-libs/footprints/K50-35/K50-35.pretty")(options "")(descr "K50-35 footprints"))
```

## Уже готовая локальная копия графики (без Gitea)

На стенде уже лежит в `/home/user/ZCodeProject/kicad_libs/K50-35/`:
- `K50-35.kicad_sym` (65 символов)
- `K50-35.pretty/` (12 футпринтов)
- `K50-35.3dshapes/` (12 3D-заглушек)

Можно подключить напрямую из этого пути (Type: KiCad) — см. прошлый шаг.
