# -*- coding: utf-8 -*-
"""Образец конвертера: «Демо-Дистрибьютор» шлёт CSV с ',' и колонками
Code,Product,Price RUB,Min Order,Delivery weeks. Конвертер приводит его
к внутреннему формату. По этому шаблону пишутся конвертеры под реальных
поставщиков (~30 строк на поставщика)."""
import csv
from datetime import date

def convert(path: str, price_date: str | None = None) -> list[dict]:
    out = []
    with open(path, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            out.append({
                'артикул_поставщика': r['Code'].strip(),
                'наименование': r['Product'].strip(),
                'цена': r['Price RUB'].replace(' ', '').replace(',', '.'),
                'валюта': 'RUB',
                'кол-во_от': '1',
                'MOQ': r.get('Min Order', '1').strip() or '1',
                'срок_дн': str(int(float(r.get('Delivery weeks', '0') or 0) * 7)),
                'дата_прайса': price_date or date.today().isoformat(),
            })
    return out
