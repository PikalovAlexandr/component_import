"""Этап 4 (Р-10, З-8): калькуляция стоимости изделия по схеме или BOM.

Конвейер: BOM (из .kicad_sch или CSV) -> сопоставление с деталями ->
потребность на тираж (с техотходом) -> покрытие складом -> подбор предложений
(ценовые пороги кол-во_от, MOQ, свежесть цены) -> калькуляция (JSON версия +
XLSX/CSV) -> сравнение версий.

Правила подбора цены для позиции:
- заказ = max(потребность_к_закупке, MOQ предложения);
- в предложении действует порог с максимальным кол-во_от <= заказ;
- из всех поставщиков берётся минимальная СТОИМОСТЬ ЗАКАЗА (не цена штуки);
- предложения старше max_age помечаются «цена устарела» и в подборе не
  участвуют, если есть свежие; если свежих нет — берутся с пометкой."""
from __future__ import annotations
import os
import csv
import json
import math
from dataclasses import dataclass, asdict
from datetime import date, datetime
from .pricing import Offer
from . import project


@dataclass
class BomLine:
    part: str
    acceptance: str
    refs: list
    qty_per_unit: int


@dataclass
class CostLine:
    part: str
    acceptance: str
    refs: str
    qty_per_unit: int
    need: int              # на тираж, с техотходом
    from_stock: int
    to_buy: int
    order_qty: int = 0     # с учётом MOQ
    supplier: str = ''
    sku: str = ''
    unit_price: float = 0.0
    currency: str = ''
    line_cost: float = 0.0
    price_date: str = ''
    stale: bool = False
    note: str = ''


def bom_from_sch(sch_path: str, acceptance: str = '') -> list[BomLine]:
    """BOM из схемы: имя символа = базовое имя детали (Р-1: источник истины — база).
    acceptance — выбор приёмки на уровень проекта (Р-9)."""
    groups = {}
    for c in project.list_components(sch_path):
        groups.setdefault(c.name, []).append(c.reference)
    return [BomLine(part=n, acceptance=acceptance, refs=sorted(r), qty_per_unit=len(r))
            for n, r in sorted(groups.items())]


def bom_from_csv(path: str) -> list[BomLine]:
    """CSV ';': Деталь;Приёмка;Кол-во[;Обозначения]"""
    out = []
    with open(path, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f, delimiter=';'):
            out.append(BomLine(part=r['Деталь'].strip(),
                               acceptance=(r.get('Приёмка') or '').strip(),
                               refs=[x for x in (r.get('Обозначения') or '').split(',') if x],
                               qty_per_unit=int(r['Кол-во'])))
    return out


def load_stock(path: str | None) -> dict:
    """CSV ';': Деталь;Приёмка;Остаток -> {(part, acc): qty}"""
    if not path:
        return {}
    out = {}
    with open(path, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f, delimiter=';'):
            out[(r['Деталь'].strip(), (r.get('Приёмка') or '').strip())] = int(r['Остаток'])
    return out


def _pick_offer(offers: list[Offer], to_buy: int, max_age: int, today: date):
    """-> (offer, order_qty, unit_price, stale) | None"""
    best = None
    fresh = [o for o in offers if not o.is_stale(max_age, today)]
    pool, stale = (fresh, False) if fresh else (offers, True)
    # группируем по (supplier, sku): пороги одного предложения
    by_sku = {}
    for o in pool:
        by_sku.setdefault((o.supplier, o.sku), []).append(o)
    for tiers in by_sku.values():
        moq = max(t.moq for t in tiers)
        order = max(to_buy, moq)
        applicable = [t for t in tiers if t.qty_from <= order]
        if not applicable:
            continue
        tier = max(applicable, key=lambda t: t.qty_from)
        cost = order * tier.price
        if best is None or cost < best[0]:
            best = (cost, tier, order)
    if best is None:
        return None
    cost, tier, order = best
    return tier, order, tier.price, stale


def calculate(bom: list[BomLine], parts: dict, offers_path: str,
              qty: int, stock: dict | None = None, attrition_pct: float = 0.0,
              max_age: int = 90, today: date | None = None):
    today = today or date.today()
    stock = dict(stock or {})
    offers = [Offer(**o) for o in json.load(open(offers_path, encoding='utf-8'))] \
        if os.path.exists(offers_path) else []
    by_part = {}
    for o in offers:
        by_part.setdefault((o.part, o.acceptance), []).append(o)
    lines, unmatched = [], []
    total = 0.0
    for b in bom:
        if b.part not in parts:
            unmatched.append({'part': b.part, 'reason': 'нет в базе деталей',
                              'refs': ','.join(b.refs)})
            continue
        if b.acceptance and b.acceptance not in parts[b.part]['acceptances']:
            unmatched.append({'part': b.part,
                              'reason': f'нет варианта приёмки «{b.acceptance}»',
                              'refs': ','.join(b.refs)})
            continue
        need = math.ceil(b.qty_per_unit * qty * (1 + attrition_pct / 100))
        have = stock.get((b.part, b.acceptance), 0)
        use = min(have, need)
        stock[(b.part, b.acceptance)] = have - use
        line = CostLine(part=b.part, acceptance=b.acceptance, refs=','.join(b.refs),
                        qty_per_unit=b.qty_per_unit, need=need,
                        from_stock=use, to_buy=need - use)
        if line.to_buy > 0:
            pick = _pick_offer(by_part.get((b.part, b.acceptance), []),
                               line.to_buy, max_age, today)
            if pick is None:
                line.note = 'нет предложений — цена неизвестна'
                unmatched.append({'part': b.part, 'reason': 'нет цены',
                                  'refs': line.refs})
            else:
                o, order, price, stale = pick
                line.order_qty, line.supplier, line.sku = order, o.supplier, o.sku
                line.unit_price, line.currency = price, o.currency
                line.line_cost = round(order * price, 2)
                line.price_date, line.stale = o.price_date, stale
                if stale:
                    line.note = 'цена устарела'
                total += line.line_cost
        lines.append(line)
    return {'дата': today.isoformat(), 'тираж': qty, 'техотход_%': attrition_pct,
            'итого_закупка': round(total, 2),
            'строк': len(lines), 'без_цены_или_детали': len(unmatched),
            'позиции': [asdict(l) for l in lines], 'несопоставлено': unmatched}


def save_calc(calc: dict, out_dir: str, name: str):
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    jpath = os.path.join(out_dir, f'калькуляция_{name}_{stamp}.json')
    json.dump(calc, open(jpath, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    cpath = jpath[:-5] + '.csv'
    cols = ['part', 'acceptance', 'refs', 'qty_per_unit', 'need', 'from_stock',
            'to_buy', 'order_qty', 'supplier', 'unit_price', 'currency',
            'line_cost', 'price_date', 'note']
    with open(cpath, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=cols, delimiter=';', extrasaction='ignore')
        w.writeheader()
        for l in calc['позиции']:
            w.writerow(l)
    return jpath, cpath


def compare(a_path: str, b_path: str) -> list[str]:
    """Сравнение версий калькуляции (ТЗ: версии для отслеживания по мере доработки)."""
    a = json.load(open(a_path, encoding='utf-8'))
    b = json.load(open(b_path, encoding='utf-8'))
    la = {(l['part'], l['acceptance']): l for l in a['позиции']}
    lb = {(l['part'], l['acceptance']): l for l in b['позиции']}
    out = [f"Итого: {a['итого_закупка']} -> {b['итого_закупка']} "
           f"(Δ {round(b['итого_закупка'] - a['итого_закупка'], 2)})"]
    for k in sorted(lb.keys() - la.keys()):
        out.append(f"+ {k[0]}: добавлена, {lb[k]['line_cost']}")
    for k in sorted(la.keys() - lb.keys()):
        out.append(f"- {k[0]}: удалена, была {la[k]['line_cost']}")
    for k in sorted(la.keys() & lb.keys()):
        if la[k]['line_cost'] != lb[k]['line_cost']:
            out.append(f"~ {k[0]}: {la[k]['line_cost']} -> {lb[k]['line_cost']}")
    return out
