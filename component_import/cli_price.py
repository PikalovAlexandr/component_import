"""CLI этапа 3: component-price {import|confirm|status}."""
from __future__ import annotations
import sys, json, argparse, importlib.util
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

    if a.cmd == 'status':
        offers = [Offer(**o) for o in json.load(open(a.offers, encoding='utf-8'))]
        stale = [o for o in offers if o.is_stale(a.max_age)]
        print(f'Предложений: {len(offers)} | устарело (> {a.max_age} дн): {len(stale)}')
        for o in stale[:20]:
            print(f'  ! {o.part} {o.supplier}/{o.sku}: цена от {o.price_date}')
        return 1 if stale else 0


if __name__ == '__main__':
    sys.exit(main())
