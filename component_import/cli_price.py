"""CLI этапа 3: component-price {import|confirm|status}."""
from __future__ import annotations
import sys
import json
import argparse
import importlib.util
from .pricing import (read_internal, match_pricelist, save_offers,
                      MapStore, Offer)
from .importer import ImportSession


def _load_converter(path: str):
    spec = importlib.util.spec_from_file_location('conv', path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod.convert


def _parts(lib_dir: str):
    s = ImportSession(lib_dir, config={'lib_name': 'x'})
    s.group()
    return s.parts


def main(argv=None):
    ap = argparse.ArgumentParser(prog='component-price',
                                 description='Импорт прайс-листов (этап 3, З-9)')
    sub = ap.add_subparsers(dest='cmd', required=True)

    im = sub.add_parser('import', help='импорт прайса')
    im.add_argument('file'); im.add_argument('--supplier', required=True)
    im.add_argument('--parts', required=True, help='каталог библиотеки (источник деталей)')
    im.add_argument('--converter', help='py-файл конвертера; без него — внутренний формат')
    im.add_argument('--price-date', help='дата прайса YYYY-MM-DD (для конвертера)')
    im.add_argument('--map-store', default='price_mappings.json')
    im.add_argument('--offers', default='offers.json')

    cf = sub.add_parser('confirm', help='подтвердить соответствие артикул=деталь[.приёмка]')
    cf.add_argument('--supplier', required=True)
    cf.add_argument('--map-store', default='price_mappings.json')
    cf.add_argument('pair', nargs='+', metavar='АРТИКУЛ=ДЕТАЛЬ[.ПРИЁМКА]')

    st = sub.add_parser('status', help='свежесть цен в накопителе offers.json')
    st.add_argument('offers'); st.add_argument('--max-age', type=int, default=90)

    ps = sub.add_parser('push', help='выгрузить offers.json в Part-DB (штатные сущности:'
                                     ' suppliers/orderdetails/pricedetails; Д-1 не требуется)')
    ps.add_argument('offers')
    ps.add_argument('--url', required=True); ps.add_argument('--token', default='')
    ps.add_argument('--dry-run', action='store_true')

    a = ap.parse_args(argv)

    if a.cmd == 'import':
        rows = (_load_converter(a.converter)(a.file, a.price_date)
                if a.converter else read_internal(a.file))
        store = MapStore(a.map_store)
        offers, to_confirm = match_pricelist(rows, _parts(a.parts), store, a.supplier)
        n = save_offers(offers, a.offers)
        by = {}
        for o in offers: by[o.matched_by] = by.get(o.matched_by, 0) + 1
        print(f'Строк прайса: {len(rows)} | сопоставлено: {len(offers)} {by} | '
              f'на подтверждение: {len(to_confirm)} | всего предложений: {n}')
        for t in to_confirm:
            r = t['строка']
            print(f'  ? {r["артикул_поставщика"]} "{r["наименование"]}" -> '
                  f'кандидаты: {t["кандидаты"] or "нет"}')
        if to_confirm:
            print(f'Подтвердите: component-price confirm --supplier {a.supplier} АРТИКУЛ=ДЕТАЛЬ')
        return 0

    if a.cmd == 'confirm':
        store = MapStore(a.map_store)
        for p in a.pair:
            sku, target = p.split('=', 1)
            base, _, acc = target.partition('.')
            store.put(a.supplier, sku, base, acc)
            print(f'Запомнено: {a.supplier}/{sku} -> {target}')
        return 0

    if a.cmd == 'push':
        from .cli import PartDBClient
        cli = PartDBClient(a.url, a.token, dry_run=a.dry_run)
        offers = [Offer(**o) for o in json.load(open(a.offers, encoding='utf-8'))]
        pushed = skipped = 0
        sup_cache, od_cache = {}, {}
        for o in offers:
            part = cli.find_part(o.part)
            if part is None and not cli.dry_run:
                skipped += 1
                print(f'  ? {o.part}: детали нет в Part-DB — пропуск (сначала component-import --upload)')
                continue
            part_iri = (part or {}).get('@id', f'dry://parts/{o.part}')
            if o.supplier not in sup_cache:
                found = [s for s in cli._get('/api/suppliers', {'name': o.supplier})
                         if s.get('name') == o.supplier]
                sup_cache[o.supplier] = (found[0] if found
                                         else cli._post('/api/suppliers', {'name': o.supplier}))
            sup_iri = sup_cache[o.supplier]['@id']
            od_key = (o.part, o.supplier, o.sku)
            if od_key not in od_cache:
                od_cache[od_key] = cli._post('/api/orderdetails', {
                    'part': part_iri, 'supplier': sup_iri,
                    'supplierpartnr': o.sku, 'obsolete': False})
            cli._post('/api/pricedetails', {
                'orderdetail': od_cache[od_key]['@id'],
                'price': str(o.price), 'min_discount_quantity': o.qty_from,
                'price_related_quantity': 1})
            pushed += 1
        print(f'Выгружено предложений: {pushed} | пропущено (нет детали): {skipped}')
        if cli.dry_run:
            import os as _os
            out = _os.path.join(_os.path.dirname(_os.path.abspath(a.offers)) or '.',
                                'partdb_offers_payloads.json')
            cli.dump(out)
            print(f'Payloads: {len(cli.payloads)} -> {out}')
        return 0

    if a.cmd == 'status':
        offers = [Offer(**o) for o in json.load(open(a.offers, encoding='utf-8'))]
        stale = [o for o in offers if o.is_stale(a.max_age)]
        print(f'Предложений: {len(offers)} | устарело (> {a.max_age} дн): {len(stale)}')
        for o in stale[:20]:
            print(f'  ! {o.part} {o.supplier}/{o.sku}: цена от {o.price_date}')
        return 1 if stale else 0


if __name__ == '__main__':
    sys.exit(main())
