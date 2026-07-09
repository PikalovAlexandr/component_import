"""CLI этапа 4: component-cost {calc|compare}."""
from __future__ import annotations
import sys, argparse
from . import costing
from .importer import ImportSession


def main(argv=None):
    ap = argparse.ArgumentParser(prog='component-cost',
                                 description='Калькуляция стоимости изделия (этап 4, Р-10/З-8)')
    sub = ap.add_subparsers(dest='cmd', required=True)

    c = sub.add_parser('calc', help='рассчитать стоимость по схеме или BOM')
    c.add_argument('source', help='.kicad_sch или BOM.csv (Деталь;Приёмка;Кол-во)')
    c.add_argument('--parts', required=True, help='каталог библиотеки (источник деталей)')
    c.add_argument('--offers', default='offers.json')
    c.add_argument('--qty', type=int, required=True, help='тираж, шт изделий')
    c.add_argument('--acceptance', default='', help='приёмка проекта (Р-9), напр. 5')
    c.add_argument('--stock', help='CSV остатков: Деталь;Приёмка;Остаток')
    c.add_argument('--attrition', type=float, default=0.0, help='техотход, %%')
    c.add_argument('--max-age', type=int, default=90, help='свежесть цен, дней')
    c.add_argument('-o', '--out', default='.')
    c.add_argument('--name', default='изделие')

    d = sub.add_parser('compare', help='сравнить две версии калькуляции')
    d.add_argument('a'); d.add_argument('b')

    a = ap.parse_args(argv)

    if a.cmd == 'calc':
        s = ImportSession(a.parts, config={'lib_name': 'x'}); s.group()
        bom = (costing.bom_from_sch(a.source, a.acceptance)
               if a.source.endswith('.kicad_sch') else costing.bom_from_csv(a.source))
        calc = costing.calculate(bom, s.parts, a.offers, a.qty,
                                 stock=costing.load_stock(a.stock),
                                 attrition_pct=a.attrition, max_age=a.max_age)
        jp, cp = costing.save_calc(calc, a.out, a.name)
        print(f"Тираж {calc['тираж']} шт | позиций {calc['строк']} | "
              f"ИТОГО закупка: {calc['итого_закупка']} | "
              f"без цены/детали: {calc['без_цены_или_детали']}")
        for u in calc['несопоставлено']:
            print(f"  ? {u['part']} ({u['refs']}): {u['reason']}")
        for l in calc['позиции']:
            if l['note']:
                print(f"  ! {l['part']}: {l['note']}")
        print(f'Сохранено: {jp}\n           {cp}')
        return 1 if calc['несопоставлено'] else 0

    if a.cmd == 'compare':
        for line in costing.compare(a.a, a.b):
            print(line)
        return 0


if __name__ == '__main__':
    sys.exit(main())
