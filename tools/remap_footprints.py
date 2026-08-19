"""Путь B: перевод футпринтов деталей на стандартные библиотеки KiCad.

Читает CSV-маппинг (разделитель ';', колонки: old;new[, comment]) и через
Part-DB API меняет parts.eda_info_kicad_footprint. Поддержка dry-run.

Правила матчинга (порядок):
  exact   — строка old совпадает с lib_id целиком ('K50-35:8X2.5');
  prefix  — old заканчивается '*' — матчится префикс ('K50-35:8*').

Пример config/remap_footprints.example.csv:
    old;new
    K50-35:8X2.5;Capacitor_THT:CP_Radial_D8.0mm_P2.50mm
    K50-35:6.3X2.5;Capacitor_THT:CP_Radial_D6.3mm_P2.50mm
"""
from __future__ import annotations
import argparse, csv, sys
import requests


def load_map(path: str) -> list[tuple[str, str, bool]]:
    out = []
    with open(path, encoding='utf-8-sig') as f:
        for row in csv.reader(f, delimiter=';'):
            if len(row) < 2 or row[0].lstrip().startswith(('#', '//')) \
                    or row[0].strip().lower() == 'old':
                continue
            old, new = row[0].strip(), row[1].strip()
            out.append((old.rstrip('*').strip(), new, old.endswith('*')))
    return out


def match(fp: str, rules) -> str | None:
    for old, new, is_prefix in rules:
        if is_prefix:
            if fp.startswith(old):
                return new
        elif fp == old:
            return new
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog='remap-footprints',
        description='Перевод футпринтов деталей на стандартные библиотеки KiCad '
                    '(путь B: графика из коробки KiCad вместо PCAD-конвертации)')
    ap.add_argument('mapping', help='CSV: old;new (exact или old* для префикса)')
    ap.add_argument('--url', required=True, help='Part-DB, напр. http://localhost:90')
    ap.add_argument('--token', required=True)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--only-lib', help='обработать только детали с этим префиксом '
                                       '(напр. K50-35), без :имени')
    a = ap.parse_args(argv)

    rules = load_map(a.mapping)
    if not rules:
        print('маппинг пуст'); return 1
    hdr = {'Authorization': f'Bearer {a.token}', 'Accept': 'application/ld+json'}
    page = 1
    seen = patched = skipped = 0
    while True:
        r = requests.get(f'{a.url}/api/parts', headers=hdr,
                         params={'page': page, 'itemsPerPage': 100}, timeout=30)
        r.raise_for_status()
        members = r.json().get('hydra:member', [])
        if not members:
            break
        for m in members:
            # в коллекции eda_info не встраивается — берём карточку детали
            p = requests.get(f"{a.url}{m['@id']}", headers=hdr, timeout=30).json()
            ei = p.get('eda_info')
            fp = ei.get('kicad_footprint') if isinstance(ei, dict) else None
            fp = fp or ''
            if not fp:
                continue
            if a.only_lib and not fp.startswith(a.only_lib):
                continue
            seen += 1
            new = match(fp, rules)
            if not new:
                skipped += 1
                continue
            print(f"{'DRY ' if a.dry_run else ''}{p['@id']}: {fp} -> {new}  ({p.get('name')})")
            if not a.dry_run:
                requests.patch(f"{a.url}{p['@id']}", headers={
                    **hdr, 'Content-Type': 'application/merge-patch+json'},
                    json={'eda_info': {'kicad_footprint': new}}, timeout=30).raise_for_status()
            patched += 1
        page += 1
    print(f'Деталей с футпринтом: {seen} | переведено: {patched} | без правила: {skipped}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
