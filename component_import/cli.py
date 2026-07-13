"""Отчёт (MD), выгрузка в Part-DB (REST API, JSON-LD) и CLI."""
from __future__ import annotations
import os, sys, json, argparse
from collections import Counter
from .importer import ImportSession, load_field_map
from .rules import ENC_ARTIFACT

def _norm(v):
    return ENC_ARTIFACT.sub(lambda m: m.group(0)[0] + 'я', v) if isinstance(v, str) else v


def make_report(sess: ImportSession, path: str, title: str):
    by_rule = Counter((i.rule, i.severity) for i in sess.issues)
    lines = [f'# Отчёт мастера импорта: {title}', '',
             f'Символов: {len(sess.symbols)} | Футпринтов: {len(sess.footprints)} | '
             f'Деталей после группировки: {len(sess.parts)}', '',
             '## Сводка по правилам', '',
             '| Правило | Уровень | Кол-во |', '|---|---|---|']
    for (rule, sev), n in sorted(by_rule.items()):
        lines.append(f'| {rule} | {sev} | {n} |')
    lines += ['', '## Требуют решения библиотекаря (manual)', '']
    for i in sess.issues:
        if i.severity == 'manual':
            lines.append(f'- **{i.obj}** [{i.rule}]: {i.message}')
    lines += ['', '## Ошибки (error)', '']
    for i in sess.issues:
        if i.severity == 'error':
            lines.append(f'- {i.obj} [{i.rule}]: {i.message}')
    lines += ['', f'## Протокол автоисправлений ({len(sess.fix_log)})', '']
    lines += [f'- {x}' for x in sess.fix_log]
    open(path, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    return path


class PartDBClient:
    """Минимальный клиент REST API Part-DB (Api-Platform, JSON-LD).
    dry_run=True: вместо запросов пишет payloads в файл (для стенда без сервера)."""
    def __init__(self, base_url: str, token: str, dry_run: bool = False):
        self.base = base_url.rstrip('/')
        self.token = token
        self.dry_run = dry_run
        self.payloads = []
        self.skipped = 0

    def _get(self, ep: str, params: dict | None = None):
        if self.dry_run:
            return []                      # на сухом прогоне считаем, что базы пустые
        import requests
        r = requests.get(f'{self.base}{ep}', params=params or {}, timeout=30, headers={
            'Authorization': f'Bearer {self.token}',
            'Accept': 'application/ld+json'})
        r.raise_for_status()
        d = r.json()
        return d.get('hydra:member', d if isinstance(d, list) else [])

    def _post(self, ep: str, payload: dict):
        if self.dry_run:
            self.payloads.append({'endpoint': ep, 'payload': payload})
            return {'@id': f'dry://{ep}/{len(self.payloads)}'}
        import requests
        r = requests.post(f'{self.base}{ep}', json=payload, timeout=30, headers={
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/ld+json'})
        r.raise_for_status()
        return r.json()

    def ensure_category(self, name: str):
        for c in self._get('/api/categories', {'name': name}):
            if c.get('name') == name:
                return c                   # уже есть — не создаём дубль
        return self._post('/api/categories', {'name': name})

    def find_part(self, name: str):
        for p in self._get('/api/parts', {'name': name}):
            if p.get('name') == name:
                return p
        return None

    # Поля, публикуемые в parameters детали: KiCad-API Part-DB отдаёт parameters
    # в fields карточки (KiCadHelper), т.е. они доезжают до свойств символа в схеме
    # и далее в netlist -> eskd-templates (закрытие п.3 чек-листа М0).
    ESKD_PARAM_FIELDS = ('Тип', 'Документ', 'Примечание', 'Группа',
                         'Класс точности', 'Исключён из ПЭ', 'Масса', 'Высота')

    def push_part(self, base: str, part: dict, category_iri: str, status: str = '',
                  skip_existing: bool = True, lib_name: str = ''):
        if skip_existing:
            existing = self.find_part(base)
            if existing is not None:
                self.skipped += 1
                return existing            # идемпотентность: деталь уже в базе
        s = part['symbols'].get('') or next(iter(part['symbols'].values()))
        p = {k: _norm(v) for k, v in s.props.items()}
        payload = {
            'name': base,
            'description': p.get('Наименование', '').strip(),
            'category': category_iri,
            'manufacturer_product_number': p.get('Value', ''),
            'comment': p.get('Примечание', '').strip(),
        }
        # eda_info: что KiCad-API отдаёт как symbolIdStr/footprint/reference.
        # Только при указанном lib_name (иначе lib_id собрать нельзя) — это и есть
        # условие видимости детали в дереве Part-DB (KiCadHelper::shouldPartBeVisible).
        eda = {}
        if lib_name:
            eda['kicad_symbol'] = f'{lib_name}:{base}'
            fp = p.get('Footprint', '').strip()
            if fp:
                eda['kicad_footprint'] = fp if ':' in fp else f'{lib_name}:{fp}'
            ref = (p.get('Reference') or ' ')[0].upper()
            if ref.isalpha():
                eda['reference_prefix'] = ref
        if eda:
            payload['eda_info'] = eda
        extra = {f'Приёмка {c}. {k}': _norm(v) for c, flds in part['acceptances'].items()
                 if c for k, v in flds.items()}
        if status:
            extra['Статус'] = status
        payload['_custom_fields'] = extra   # обрабатывается модулем PartAcceptance (Д-1 PHP)
        created = self._post('/api/parts', payload)
        part_iri = created.get('@id')
        # контрактные поля -> parameters (отдельные POST /api/parameters)
        for name in self.ESKD_PARAM_FIELDS:
            val = p.get(name, '').strip()
            if val:
                self._post('/api/parameters', {
                    'element': part_iri, 'name': name, 'value_text': val,
                    'group': 'ЕСКД'})
        return created

    def dump(self, path: str):
        json.dump(self.payloads, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def upload_session(sess, url: str, token: str, lib: str, dry_run: bool):
    """Выгрузка результатов ImportSession в Part-DB. Возвращает (client, создано)."""
    sess.apply_field_map_props()
    cli = PartDBClient(url or 'http://dry-run', token or '', dry_run=dry_run)
    cat = cli.ensure_category(lib)
    for base, part in sorted(sess.parts.items()):
        was_skipped = cli.skipped
        created = cli.push_part(base, part, cat['@id'], lib_name=lib)
        # Д-3: роль УГО «ГОСТ» (импорт из PCAD = ГОСТ-графика). Только для
        # новых деталей: у существующих роль уже есть (backfill миграции 002
        # или прошлый прогон) — идемпотентность без лишних GET.
        if cli.skipped == was_skipped:
            cli._post('/api/component_symbols', {
                'part': created.get('@id'),
                'role': 'gost',
                'symbol_id': f'{lib}:{base}',
            })
    return cli, len(sess.parts) - cli.skipped


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog='component-import',
        description='Мастер импорта библиотек KiCad в систему «КОМПОНЕНТ» (этап 1)')
    ap.add_argument('src', help='каталог с .kicad_sym и .kicad_mod')
    ap.add_argument('-o', '--out', required=True, help='каталог результатов')
    ap.add_argument('--lib-name', help='имя выходной библиотеки (по умолчанию из .kicad_sym)')
    ap.add_argument('--field-map', help='CSV "старое_поле;новое_поле"')
    ap.add_argument('--no-fix', action='store_true', help='только валидация, без записи')
    ap.add_argument('--tu', action='append', metavar='YAML',
                    help='эталон документа ТУ для сверки В-7 (можно несколько)')
    ap.add_argument('--upload', metavar='URL', help='базовый URL Part-DB для выгрузки')
    ap.add_argument('--token', help='API-токен Part-DB')
    ap.add_argument('--dry-run', action='store_true', help='payloads в файл вместо запросов')
    a = ap.parse_args(argv)

    fmap = load_field_map(a.field_map) if a.field_map else {}
    lib = a.lib_name or os.path.splitext(
        next(f for f in sorted(os.listdir(a.src)) if f.endswith('.kicad_sym')))[0].lstrip('C_')
    sess = ImportSession(a.src, field_map=fmap, config={'lib_name': lib})
    sess.validate()
    sess.group()
    for tu_cfg in (a.tu or []):
        from .tudoc import TuDoc, v7_check
        doc = TuDoc(tu_cfg)
        found = v7_check(sess.parts, {x.name: x for x in sess.symbols}, doc)
        sess.issues += found
        print(f'В-7 [{doc.name}]: расхождений {len(found)} '
              f'({len({i.obj for i in found})} деталей)')
    os.makedirs(a.out, exist_ok=True)
    if not a.no_fix:
        sess.write_fixed(os.path.join(a.out, lib))
        # верификация: повторный прогон на исправленном
        check = ImportSession(os.path.join(a.out, lib), config={'lib_name': lib})
        check.validate()
        residual = [i for i in check.issues if i.severity == 'error']
        print(f'Верификация после исправлений: ошибок {len(residual)}')
        if residual:
            for i in residual[:10]:
                print('  !', i.obj, i.rule, i.message)
    rep = make_report(sess, os.path.join(a.out, f'ОТЧЁТ_{lib}.md'), lib)
    if a.upload or a.dry_run:
        cli, created = upload_session(sess, a.upload, a.token, lib,
                                      dry_run=a.dry_run or not a.upload)
        if cli.dry_run:
            cli.dump(os.path.join(a.out, 'partdb_payloads.json'))
            print(f'Payloads для Part-DB: {len(cli.payloads)} шт -> partdb_payloads.json')
        else:
            print(f'Выгрузка: создано {len(sess.parts) - cli.skipped}, '
                  f'пропущено существующих {cli.skipped}')
    errors = sum(1 for i in sess.issues if i.severity == 'error')
    manual = sum(1 for i in sess.issues if i.severity == 'manual')
    print(f'Деталей: {len(sess.parts)} | ошибок: {errors} | на ручную проверку: {manual} | отчёт: {rep}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
