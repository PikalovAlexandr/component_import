# -*- coding: utf-8 -*-
"""Этап 3 (З-9): импорт прайс-листов дистрибьюторов.

Внутренний формат прайса (ТЗ ПС-5) — CSV ';' с колонками:
    артикул_поставщика; наименование; цена; валюта; кол-во_от; MOQ; срок_дн; дата_прайса
Конвертер под конкретного дистрибьютора — отдельный python-модуль с функцией
convert(path) -> list[dict] в этом формате (см. converters/demo_distributor.py).

Сопоставление строк прайса с деталями:
1) по запомненному соответствию «поставщик+артикул -> деталь[.приёмка]» (map-store);
2) авто — по нормализованному наименованию (включая наименования приёмки «5»);
3) остальное — в список «на подтверждение»; подтверждённое запоминается навсегда.

Цены датируются датой прайса; старше max_age_days — «устарела» (в калькуляции
этапа 4 такие цены помечаются и не считаются достоверными)."""
from __future__ import annotations
import csv, json, os, re, unicodedata
from dataclasses import dataclass, asdict
from datetime import date, datetime

COLUMNS = ['артикул_поставщика', 'наименование', 'цена', 'валюта',
           'кол-во_от', 'MOQ', 'срок_дн', 'дата_прайса']

_LAT2CYR = str.maketrans('ABCEHKMOPTXacekopxy', 'АВСЕНКМОРТХасекорху')

def norm_name(s: str) -> str:
    """Нормализация наименования: регистр, пробелы, латиница-двойники -> кириллица."""
    s = unicodedata.normalize('NFC', s or '')
    s = s.translate(_LAT2CYR).upper()
    return re.sub(r'\s+', '', s)


@dataclass
class Offer:
    part: str                 # базовое имя детали
    acceptance: str           # '' | '5' | ...
    supplier: str
    sku: str
    name: str
    price: float
    currency: str
    qty_from: int
    moq: int
    lead_days: int
    price_date: str           # ISO
    matched_by: str           # mapping | auto | confirmed

    def is_stale(self, max_age_days: int, today: date | None = None) -> bool:
        d = datetime.strptime(self.price_date, '%Y-%m-%d').date()
        return ((today or date.today()) - d).days > max_age_days


class MapStore:
    """Память подтверждённых соответствий: {supplier: {sku: 'part[.acceptance]'}}."""
    def __init__(self, path: str):
        self.path = path
        self.data = json.load(open(path, encoding='utf-8')) if os.path.exists(path) else {}

    def get(self, supplier: str, sku: str):
        return self.data.get(supplier, {}).get(sku)

    def put(self, supplier: str, sku: str, part: str, acceptance: str = ''):
        self.data.setdefault(supplier, {})[sku] = (
            f'{part}.{acceptance}' if acceptance else part)
        json.dump(self.data, open(self.path, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)


def read_internal(path: str) -> list[dict]:
    with open(path, encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f, delimiter=';'))
    missing = set(COLUMNS) - set(rows[0] if rows else COLUMNS)
    if missing:
        raise ValueError(f'прайс не во внутреннем формате, нет колонок: {sorted(missing)}')
    return rows


def build_name_index(parts: dict) -> dict:
    """Индекс 'нормализованное наименование -> (деталь, приёмка)' по всем приёмкам."""
    idx = {}
    for base, part in parts.items():
        for acc, fields in part['acceptances'].items():
            nm = norm_name(fields.get('Наименование', ''))
            if nm:
                idx.setdefault(nm, (base, acc))
    return idx


def match_pricelist(rows: list[dict], parts: dict, store: MapStore,
                    supplier: str):
    """-> (offers, to_confirm) ; to_confirm: строки с кандидатами или без."""
    idx = build_name_index(parts)
    offers, to_confirm = [], []
    for r in rows:
        sku = r['артикул_поставщика'].strip()
        target, how = None, None
        saved = store.get(supplier, sku)
        if saved:
            base, _, acc = saved.partition('.')
            if base in parts:
                target, how = (base, acc), 'mapping'
        if target is None:
            hit = idx.get(norm_name(r['наименование']))
            if hit:
                target, how = hit, 'auto'
        if target is None:
            cands = [b for b in parts
                     if norm_name(b) in norm_name(r['наименование'])
                     or norm_name(r['наименование']) in norm_name(b)]
            to_confirm.append({'строка': r, 'кандидаты': sorted(cands)[:5]})
            continue
        offers.append(Offer(
            part=target[0], acceptance=target[1], supplier=supplier, sku=sku,
            name=r['наименование'].strip(),
            price=float(str(r['цена']).replace(',', '.')),
            currency=(r['валюта'] or 'RUB').strip().upper(),
            qty_from=int(r['кол-во_от'] or 1), moq=int(r['MOQ'] or 1),
            lead_days=int(r['срок_дн'] or 0),
            price_date=r['дата_прайса'].strip(), matched_by=how))
    return offers, to_confirm


def save_offers(offers: list[Offer], path: str, merge: bool = True):
    """offers.json — накопитель предложений (до появления PartAcceptance API Part-DB).
    Слияние: новее прайс того же поставщика/артикула/кол-ва вытесняет старый."""
    old = []
    if merge and os.path.exists(path):
        old = json.load(open(path, encoding='utf-8'))
    key = lambda o: (o['supplier'], o['sku'], o['qty_from'])
    merged = {key(o): o for o in old}
    for o in offers:
        d = asdict(o)
        if key(d) not in merged or d['price_date'] >= merged[key(d)]['price_date']:
            merged[key(d)] = d
    json.dump(sorted(merged.values(), key=lambda o: (o['part'], o['supplier'], o['qty_from'])),
              open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return len(merged)
