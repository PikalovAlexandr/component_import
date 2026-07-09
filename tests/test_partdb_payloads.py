"""Клиент Part-DB: контрактные поля уходят в parameters (рекомендация стенда М0)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from component_import.importer import ImportSession
from component_import.cli import PartDBClient

def test_params_pushed():
    src = os.path.join(os.path.dirname(__file__), 'golden_k50')
    s = ImportSession(src, field_map={'Гост-Ту': 'Документ', 'Вид+Раздел': 'Тип'},
                      config={'lib_name': 'K50-35'})
    s.validate(); s.group()
    s.apply_field_map_props()
    cli = PartDBClient('http://dry', '', dry_run=True)
    cat = cli.ensure_category('K50-35')
    base = 'K50-35-100В-10'
    cli.push_part(base, s.parts[base], cat['@id'])
    eps = [p['endpoint'] for p in cli.payloads]
    assert eps.count('/api/parts') == 1
    params = [p['payload'] for p in cli.payloads if p['endpoint'] == '/api/parameters']
    names = {p['name'] for p in params}
    # поля из исходной библиотеки: Масса/Высота есть всегда; Документ — после маппинга
    # (маппинг применяется при write_fixed; в props исходное имя) -> проверяем сырые
    assert {'Масса', 'Высота', 'Документ', 'Тип'} <= names
    doc = [p for p in params if p['name'] == 'Документ'][0]
    assert doc['value_text'] == 'ОЖ0.464.214 ТУ'
    assert all(p['element'].startswith('dry://') for p in params)
