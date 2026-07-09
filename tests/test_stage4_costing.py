# -*- coding: utf-8 -*-
"""Этап 4 = сценарий ПИ-5: калькуляция для тиражей 10 и 100 с ценовыми
порогами, MOQ, складом, приёмкой и несопоставленной позицией."""
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from datetime import date
from component_import.importer import ImportSession
from component_import import costing

HERE = os.path.dirname(__file__)
TODAY = date(2026, 7, 9)

def _parts():
    s = ImportSession(os.path.join(HERE, 'golden_k50'), config={'lib_name': 'K50-35'})
    s.group()
    return s.parts

def _offers(tmp_path):
    mk = lambda part, acc, sku, price, qf, moq: dict(
        part=part, acceptance=acc, supplier='Демо', sku=sku, name=part,
        price=price, currency='RUB', qty_from=qf, moq=moq, lead_days=14,
        price_date='2026-07-01', matched_by='auto')
    data = [
        mk('K50-35-100В-10', '', 'D-001', 12.5, 1, 10),    # порог 1: 12.50
        mk('K50-35-100В-10', '', 'D-001', 9.9, 100, 10),   # порог 100: 9.90
        mk('K50-35-63В-470', '', 'D-005', 20.0, 1, 50),    # MOQ 50!
        mk('K50-35-100В-10', '5', 'D-002', 45.0, 1, 5),
    ]
    p = tmp_path / 'offers.json'
    p.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    return str(p)

BOM = [costing.BomLine('K50-35-100В-10', '', ['C1', 'C3'], 2),
       costing.BomLine('K50-35-63В-470', '', ['C2'], 1),
       costing.BomLine('КМ-6-Н90', '', ['C9'], 1)]          # нет в базе

def test_pi5_qty10_moq_stock_unmatched(tmp_path):
    offers = _offers(tmp_path)
    stock = {('K50-35-100В-10', ''): 15}
    calc = costing.calculate(BOM, _parts(), offers, qty=10, stock=stock, today=TODAY)
    l = {x['part']: x for x in calc['позиции']}
    c10 = l['K50-35-100В-10']
    assert (c10['need'], c10['from_stock'], c10['to_buy']) == (20, 15, 5)
    assert c10['order_qty'] == 10 and c10['unit_price'] == 12.5   # MOQ 10 > 5
    c470 = l['K50-35-63В-470']
    assert c470['order_qty'] == 50 and c470['line_cost'] == 1000.0  # MOQ 50 > 10
    assert calc['несопоставлено'][0]['part'] == 'КМ-6-Н90'

def test_pi5_qty100_price_break_and_acceptance(tmp_path):
    offers = _offers(tmp_path)
    calc = costing.calculate(BOM[:1], _parts(), offers, qty=100, today=TODAY)
    c = calc['позиции'][0]
    assert c['order_qty'] == 200 and c['unit_price'] == 9.9        # сработал порог 100
    # приёмка проекта «5» (Р-9): своё предложение и своя цена
    bom5 = [costing.BomLine('K50-35-100В-10', '5', ['C1'], 1)]
    calc5 = costing.calculate(bom5, _parts(), offers, qty=10, today=TODAY)
    assert calc5['позиции'][0]['unit_price'] == 45.0

def test_pi5_versions_compare(tmp_path):
    offers = _offers(tmp_path)
    a = costing.calculate(BOM[:2], _parts(), offers, qty=10, today=TODAY)
    b = costing.calculate(BOM[:1], _parts(), offers, qty=10, today=TODAY)
    ja, _ = costing.save_calc(a, str(tmp_path), 'v1')
    jb, _ = costing.save_calc(b, str(tmp_path), 'v2')
    diff = costing.compare(ja, jb)
    assert any('63В-470' in d and d.startswith('-') for d in diff)
    assert diff[0].startswith('Итого:')

def test_pi5_from_schematic(tmp_path):
    sch = tmp_path / 'demo.kicad_sch'
    sch.write_text('''(kicad_sch
\t(symbol
\t\t(lib_id "K50-35-GOST:K50-35-100В-10")
\t\t(property "Reference" "C1"
\t\t)
\t)
\t(symbol
\t\t(lib_id "K50-35-GOST:K50-35-100В-10")
\t\t(property "Reference" "C2"
\t\t)
\t)
)
''', encoding='utf-8')
    bom = costing.bom_from_sch(str(sch))
    assert bom == [costing.BomLine('K50-35-100В-10', '', ['C1', 'C2'], 2)]
