"""CLI этапа 2: component-project {views|switch|audit}."""
from __future__ import annotations
import sys, argparse
from . import dual, project


def main(argv=None):
    ap = argparse.ArgumentParser(prog='component-project',
                                 description='Инструменты проекта: двойное УГО, аудит (этап 2)')
    sub = ap.add_subparsers(dest='cmd', required=True)

    v = sub.add_parser('views', help='собрать представления -GOST/-IEC из двух библиотек')
    v.add_argument('gost'); v.add_argument('iec')
    v.add_argument('-o', '--out', required=True); v.add_argument('--name', required=True)
    v.add_argument('--pairs', help='CSV имя_гост;имя_iec (по умолчанию — по совпадению имён)')
    v.add_argument('--require-both', action='store_true',
                   help='оба УГО обязательны для статуса «разрешён»')

    s = sub.add_parser('switch', help='переключить проект между представлениями')
    s.add_argument('sch'); s.add_argument('--map', required=True, action='append',
                   metavar='СТАРАЯ=НОВАЯ', help='например K50-35-GOST=K50-35-IEC')
    s.add_argument('-o', '--out', help='записать в новый файл (по умолчанию in-place с .bak)')

    a = sub.add_parser('audit', help='аудит проекта: библиотеки и статусы (FR-7)')
    a.add_argument('sch'); a.add_argument('--lib', required=True, action='append',
                   metavar='ИМЯ=ПУТЬ', help='выпущенная библиотека, например K50-35-GOST=./K50-35-GOST.kicad_sym')

    args = ap.parse_args(argv)

    if args.cmd == 'views':
        mapping = dual.load_pair_mapping(args.pairs) if args.pairs else {}
        pairs, og, oi = dual.load_pairs(args.gost, args.iec, mapping)
        issues = dual.release_gate(pairs, og, oi, require_both=args.require_both)
        errors = [i for i in issues if i.severity == 'error']
        for i in issues:
            print(f'[{i.severity:7s}] {i.obj} {i.rule}: {i.message}')
        if errors:
            print(f'В-1: {len(errors)} ошибок — представления НЕ собраны '
                  f'(детали не могут получить статус «разрешён»)')
            return 1
        g, i_ = dual.emit_views(args.gost, args.iec, args.out, args.name, mapping)
        print(f'Пар УГО: {len(pairs)} | только ГОСТ: {len(og)} | только IEC: {len(oi)}')
        print(f'Собрано: {g}\n         {i_}')
        return 0

    if args.cmd == 'switch':
        lib_map = dict(m.split('=', 1) for m in args.map)
        counts = project.switch_view(args.sch, lib_map, out_path=args.out)
        total = sum(counts.values())
        print(f'Заменено ссылок: {total} ({counts}); позиционные обозначения сохранены.')
        return 0

    if args.cmd == 'audit':
        libs = dict(m.split('=', 1) for m in args.lib)
        issues = project.audit(args.sch, libs)
        for i in issues:
            print(f'[{i.severity:7s}] {i.obj}: {i.message}')
        errors = sum(1 for i in issues if i.severity == 'error')
        print(f'Компонентов проверено: {len(project.list_components(args.sch))} | '
              f'ошибок: {errors} | предупреждений: {len(issues) - errors}')
        return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
