"""Этап 3 = сценарий ПИ-6: импорт прайса через конвертер, подтверждение
соответствий с запоминанием, слияние/обновление цен, устаревание."""
import os
import sys
import json
import csv
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from datetime import date, timedelta
from component_import.importer import ImportSession
from component_import import pricing
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'converters'))
import demo_distributor

HERE = os.path.dirname(__file__)

def _parts():
    s = ImportSession(os.path.join(HERE, 'golden_k50'), config={'lib_name': 'K50-35'})
    s.group()
    return s.parts

def _write_supplier_csv(path, rows):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['Code', 'Product', 'Price RUB', 'Min Order', 'Delivery weeks'])
        w.writeheader(); w.writerows(rows)

def test_pi6_pricelist_cycle(tmp_path):
    parts = _parts()
    src = tmp_path / 'demo_price.csv'
    _write_supplier_csv(src, [
        # авто по наименованию (в т.ч. приёмка «5» и латиница-двойники в 'K50')
        {'Code': 'D-001', 'Product': 'К50-35 -100В-10 мкФ-В', 'Price RUB': '12,50',
         'Min Order': '10', 'Delivery weeks': '2'},
        {'Code': 'D-002', 'Product': 'К50-35 -100В-10 мкФ-В-А', 'Price RUB': '45,00',
         'Min Order': '5', 'Delivery weeks': '6'},
        # не сопоставится: чужой компонент
        {'Code': 'D-777', 'Product': 'КМ-6-Н90-1мкФ', 'Price RUB': '3,10',
         'Min Order': '100', 'Delivery weeks': '1'},
    ])
    rows = demo_distributor.convert(str(src), price_date='2026-07-01')
    store = pricing.MapStore(str(tmp_path / 'map.json'))
    offers, to_confirm = pricing.match_pricelist(rows, parts, store, 'Демо')
    assert len(offers) == 2 and len(to_confirm) == 1
    acc = {(o.part, o.acceptance): o for o in offers}
    assert ('K50-35-100В-10', '') in acc and ('K50-35-100В-10', '5') in acc
    assert acc[('K50-35-100В-10', '5')].price == 45.0        # приёмка «5» — своя цена
    assert acc[('K50-35-100В-10', '')].lead_days == 14

    # подтверждение вручную -> запоминается -> повторный импорт матчится сам
    store.put('Демо', 'D-777', 'K50-35-6,3В-1000')
    offers2, tc2 = pricing.match_pricelist(rows, parts, store, 'Демо')
    assert len(offers2) == 3 and not tc2
    assert [o for o in offers2 if o.sku == 'D-777'][0].matched_by == 'mapping'

    # слияние: новый прайс перебивает цену, offers.json хранит актуальное
    opath = str(tmp_path / 'offers.json')
    pricing.save_offers(offers2, opath)
    rows2 = [dict(r) for r in rows]
    rows2[0]['цена'] = '13.90'; rows2[0]['дата_прайса'] = '2026-07-08'
    offers3, _ = pricing.match_pricelist(rows2, parts, store, 'Демо')
    pricing.save_offers(offers3, opath)
    data = json.load(open(opath, encoding='utf-8'))
    o = [x for x in data if x['sku'] == 'D-001'][0]
    assert o['price'] == 13.9 and o['price_date'] == '2026-07-08'

    # устаревание
    fresh = pricing.Offer(**o)
    assert not fresh.is_stale(90, today=date(2026, 7, 9))
    assert fresh.is_stale(90, today=date(2026, 7, 9) + timedelta(days=120))
