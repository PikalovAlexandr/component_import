"""CLI Д-5: component-attach {tu|spice} — вложения ТУ и SPICE-моделей."""
from __future__ import annotations
import sys, argparse
from .attachments import (sim_params, check_sim_pins, attachment_payload,
                          gitea_raw_url)
from .cli import PartDBClient
from .importer import ImportSession


def _client(a) -> PartDBClient:
    return PartDBClient(a.url or 'http://dry-run', a.token or '',
                        dry_run=a.dry_run or not a.url)


def _atype(cli: PartDBClient, name: str) -> str:
    """IRI типа вложения («ТУ»/«SPICE»), с созданием при отсутствии."""
    for t in cli._get('/api/attachment_types', {'name': name}):
        if t.get('name') == name:
            return t['@id']
    return cli._post('/api/attachment_types', {'name': name})['@id']


def main(argv=None):
    ap = argparse.ArgumentParser(prog='component-attach',
                                 description='Вложения ТУ и SPICE (Д-5, FR-4a/4b)')
    sub = ap.add_subparsers(dest='cmd', required=True)

    def common(p):
        p.add_argument('--url', help='Part-DB, напр. http://localhost:90')
        p.add_argument('--token', default='')
        p.add_argument('--dry-run', action='store_true')
        p.add_argument('--git-url', help='raw-ссылка на файл в Gitea целиком '
                                         'ИЛИ используйте --gitea/--repo/--path/--rev')
        p.add_argument('--gitea', help='база Gitea, напр. http://сервер:3000')
        p.add_argument('--org', default='libraries')
        p.add_argument('--repo')
        p.add_argument('--path')
        p.add_argument('--rev', default='main',
                       help='ревизия/коммит (коммит = иммутабельная версия, FR-4a)')

    tu = sub.add_parser('tu', help='документ ТУ -> вложение категории')
    common(tu)
    tu.add_argument('--doc', required=True, help='номер, напр. "ОЖ0.464.214 ТУ"')
    tu.add_argument('--category', required=True, help='имя категории Part-DB')

    sp = sub.add_parser('spice', help='SPICE-модель -> вложение детали + Sim.* поля')
    common(sp)
    sp.add_argument('--part', required=True, help='имя детали в Part-DB')
    sp.add_argument('--parts-lib', help='каталог библиотеки для проверки В-8 '
                                        '(сверка Sim.Pins с выводами)')
    sp.add_argument('--sim', action='append', default=[], metavar='КЛЮЧ=ЗНАЧ',
                    help='Sim-поля: Device=C Type=... Pins="1 2" Library=... Name=...')

    a = ap.parse_args(argv)
    url = a.git_url or gitea_raw_url(a.gitea or 'http://gitea:3000',
                                     a.org, a.repo or '', a.path or '', a.rev)
    cli = _client(a)

    if a.cmd == 'tu':
        cat = cli.ensure_category(a.category)
        payload = attachment_payload(a.doc, url, cat['@id'], _atype(cli, 'ТУ'))
        cli._post('/api/attachments', payload)
        print(f'ТУ «{a.doc}» -> категория {a.category}: {url}')

    if a.cmd == 'spice':
        sim = dict(kv.split('=', 1) for kv in a.sim)
        # В-8: сверка Sim.Pins с выводами детали до выгрузки
        if a.parts_lib:
            s = ImportSession(a.parts_lib, config={'lib_name': 'x'})
            s.group()
            if a.part not in s.parts:
                print(f'!! деталь {a.part} не найдена в {a.parts_lib}')
                return 1
            sym = s.parts[a.part]['symbols'].get('') \
                or next(iter(s.parts[a.part]['symbols'].values()))
            problems = check_sim_pins(sim, [p.number for p in sym.pins])
            for pr in problems:
                print('!! В-8:', pr)
            if problems:
                return 1
        part = cli.find_part(a.part)
        part_iri = (part or {}).get('@id', f'dry://parts/{a.part}')
        if part is None and not cli.dry_run:
            print(f'!! детали {a.part} нет в Part-DB'); return 1
        cli._post('/api/attachments', attachment_payload(
            f'SPICE: {a.part}', url, part_iri, _atype(cli, 'SPICE')))
        for prm in sim_params(sim):
            cli._post('/api/parameters', {**prm, 'element': part_iri})
        print(f'SPICE-модель + {len(sim_params(sim))} Sim-полей -> {a.part}')

    if cli.dry_run:
        cli.dump('attach_payloads.json')
        print(f'dry-run: {len(cli.payloads)} payloads -> attach_payloads.json')
    return 0


if __name__ == '__main__':
    sys.exit(main())
