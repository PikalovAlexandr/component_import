"""Д-5: вложения ТУ/SPICE, Sim-поля, проверка В-8."""
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from component_import import attachments as A
from component_import import cli_attach

GOLD = os.path.join(os.path.dirname(__file__), 'golden_k50')

def test_sim_params_and_v8():
    sim = {'Device': 'C', 'Type': 'elec', 'Pins': '1 2'}
    prm = A.sim_params(sim)
    assert {p['name'] for p in prm} == {'Sim.Device', 'Sim.Type', 'Sim.Pins'}
    assert all(p['group'] == 'SPICE' for p in prm)
    assert A.check_sim_pins(sim, ['1', '2']) == []
    assert A.check_sim_pins({'Pins': '1 3'}, ['1', '2'])          # чужой вывод
    assert A.check_sim_pins({}, ['1', '2'])                        # Pins не задан

def test_gitea_url():
    u = A.gitea_raw_url('http://g:3000/', 'libraries', 'docs',
                        'tu/OZh0464214.pdf', rev='abc123')
    assert u == 'http://g:3000/libraries/docs/raw/abc123/tu/OZh0464214.pdf'

def test_cli_tu_and_spice(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc = cli_attach.main(['tu', '--doc', 'ОЖ0.464.214 ТУ', '--category', 'K50-35',
                          '--gitea', 'http://g:3000', '--repo', 'docs',
                          '--path', 'tu/OZh0464214.pdf', '--dry-run'])
    assert rc == 0
    rc = cli_attach.main(['spice', '--part', 'K50-35-100В-10',
                          '--parts-lib', GOLD,
                          '--sim', 'Device=C', '--sim', 'Pins=1 2',
                          '--git-url', 'http://g/raw/m/c.lib', '--dry-run'])
    assert rc == 0
    data = json.load(open('attach_payloads.json', encoding='utf-8'))
    eps = [p['endpoint'] for p in data]
    assert eps.count('/api/attachments') == 1        # spice-вызов перезаписал файл
    assert eps.count('/api/parameters') == 2         # Sim.Device + Sim.Pins
    # В-8 ловит чужой вывод до выгрузки
    rc = cli_attach.main(['spice', '--part', 'K50-35-100В-10',
                          '--parts-lib', GOLD, '--sim', 'Pins=1 7',
                          '--git-url', 'http://g/x', '--dry-run'])
    assert rc == 1
