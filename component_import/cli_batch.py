"""CLI массового импорта: component-batch {plan|run}."""
from __future__ import annotations
import sys, argparse
from . import batch
from .importer import load_field_map


def _common(p):
    p.add_argument('root', help='корень с библиотеками (*.kicad_sym + *.pretty)')
    p.add_argument('--field-map', help='CSV маппинга полей (общий)')
    p.add_argument('--tu', action='append', help='эталоны ТУ (yaml, можно несколько)')
    p.add_argument('--only', action='append', help='обрабатывать только эти имена')
    p.add_argument('--skip', action='append', help='пропустить эти имена')


def _libs(a):
    libs = batch.discover(a.root)
    if a.only:
        libs = [x for x in libs if x[0] in set(a.only)]
    if a.skip:
        libs = [x for x in libs if x[0] not in set(a.skip)]
    return libs


def _tu_docs(a):
    if not a.tu:
        return []
    from .tudoc import TuDoc
    return [TuDoc(p) for p in a.tu]


def main(argv=None):
    ap = argparse.ArgumentParser(prog='component-batch',
                                 description='Массовый импорт библиотек (веха М1)')
    sub = ap.add_subparsers(dest='cmd', required=True)

    pl = sub.add_parser('plan', help='анализ и ранжирование «от чистых к грязным»')
    _common(pl)

    rn = sub.add_parser('run', help='обработка потока: исправление, отчёты, выгрузка')
    _common(rn)
    rn.add_argument('-o', '--out', required=True, help='каталог результатов')
    rn.add_argument('--upload', metavar='URL', help='боевая выгрузка в Part-DB')
    rn.add_argument('--token', default='')
    rn.add_argument('--dry-run', action='store_true')
    rn.add_argument('--limit', type=int, help='обработать первые N по рангу')

    a = ap.parse_args(argv)
    fmap = load_field_map(a.field_map) if a.field_map else {}
    tu = _tu_docs(a)
    libs = _libs(a)
    if not libs:
        print('Библиотеки не найдены'); return 1

    print(f'Найдено библиотек: {len(libs)}. Анализ...')
    ranked = []
    for name, sym, fps in libs:
        r, _ = batch.analyze(name, sym, fps, fmap, tu)
        ranked.append((r, sym, fps))
        print(f'  {r.name}: {r.status}, деталей {r.parts}, '
              f'error {r.errors} (испр. {r.fixable}), manual {r.manual}')
    ranked.sort(key=lambda x: (x[0].status.startswith('СБОЙ'), x[0].dirt))

    if a.cmd == 'plan':
        print('\nПорядок обработки («грязность» = неисправимых ошибок/деталь):')
        for i, (r, _, _) in enumerate(ranked, 1):
            print(f'{i:3d}. {r.name:40s} грязность {r.dirt:6.2f} '
                  f'({r.parts} дет., manual {r.manual}) {r.error_text}')
        return 0

    results = []
    todo = ranked[:a.limit] if a.limit else ranked
    for r0, sym, fps in todo:
        print(f'\n=== {r0.name} ===')
        r = batch.process(r0.name, sym, fps, a.out, fmap, tu,
                          upload_url=a.upload or '', token=a.token,
                          dry_run=a.dry_run or not a.upload)
        results.append(r)
        print(f'  {r.status}; выгружено {r.created}, пропущено {r.skipped}')
    mpath, cpath = batch.summary(results, a.out)
    fails = sum(1 for r in results if r.status.startswith('СБОЙ'))
    print(f'\nСводка: {mpath}\n        {cpath}')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
