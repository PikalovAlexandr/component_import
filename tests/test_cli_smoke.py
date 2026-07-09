"""CLI-обвязки: контракт аргументов всех четырёх утилит (закрытие 0% покрытия)."""
import os
import sys
import csv
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from component_import import cli, cli_project, cli_price, cli_cost

HERE = os.path.dirname(__file__)
GOLD = os.path.join(HERE, 'golden_k50')

def test_cli_import(tmp_path):
    rc = cli.main([GOLD, '-o', str(tmp_path), '--lib-name', 'K50-35',
                   '--tu', os.path.join(HERE, '..', 'config', 'tu_OZh0464214.yaml'),
                   '--dry-run'])
    assert rc == 0
    assert (tmp_path / 'ОТЧЁТ_K50-35.md').exists()
    assert (tmp_path / 'partdb_payloads.json').exists()
    assert (tmp_path / 'K50-35' / 'K50-35.kicad_sym').exists()

def test_cli_project_views_switch_audit(tmp_path):
    cli.main([GOLD, '-o', str(tmp_path / 'imp'), '--lib-name', 'K50-35', '--no-fix'])
    cli.main([GOLD, '-o', str(tmp_path / 'imp'), '--lib-name', 'K50-35'])
    lib = str(tmp_path / 'imp' / 'K50-35' / 'K50-35.kicad_sym')
    assert cli_project.main(['views', lib, lib, '-o', str(tmp_path), '--name', 'K50-35']) == 0
    sch = tmp_path / 'p.kicad_sch'
    sch.write_text('(kicad_sch\n\t(symbol\n\t\t(lib_id "K50-35-GOST:K50-35-100В-10")\n'
                   '\t\t(property "Reference" "C1"\n\t\t)\n\t)\n)\n', encoding='utf-8')
    assert cli_project.main(['switch', str(sch), '--map', 'K50-35-GOST=K50-35-IEC']) == 0
    rc = cli_project.main(['audit', str(sch), '--lib',
                           f'K50-35-IEC={tmp_path}/K50-35-IEC.kicad_sym'])
    assert rc == 1                       # статус «Архив» -> ошибка -> код 1

def test_cli_price_and_cost(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    price = tmp_path / 'p.csv'
    with open(price, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['Code', 'Product', 'Price RUB', 'Min Order', 'Delivery weeks'])
        w.writeheader()
        w.writerow({'Code': 'D-1', 'Product': 'К50-35 -100В-10 мкФ-В',
                    'Price RUB': '12,50', 'Min Order': '10', 'Delivery weeks': '2'})
    conv = os.path.join(HERE, '..', 'converters', 'demo_distributor.py')
    assert cli_price.main(['import', str(price), '--supplier', 'Демо', '--parts', GOLD,
                           '--converter', conv, '--price-date', '2026-07-01']) == 0
    assert cli_price.main(['status', 'offers.json', '--max-age', '90']) == 0
    assert cli_price.main(['push', 'offers.json', '--url', 'http://dry', '--dry-run']) == 0
    assert (tmp_path / 'partdb_offers_payloads.json').exists()
    bom = tmp_path / 'bom.csv'
    bom.write_text('Деталь;Приёмка;Кол-во\nK50-35-100В-10;;2\n', encoding='utf-8')
    rc = cli_cost.main(['calc', str(bom), '--parts', GOLD, '--offers', 'offers.json',
                        '--qty', '10', '-o', str(tmp_path), '--name', 'т'])
    assert rc == 0
    assert cli_cost.main(['compare',
                          *sorted(str(p) for p in tmp_path.glob('калькуляция_т_*.json'))[:1] * 2]) == 0
