"""Клиент Part-DB: контрактные поля уходят в parameters (рекомендация стенда М0)."""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from component_import.importer import ImportSession

def test_params_pushed():
    src = os.path.join(os.path.dirname(__file__), 'golden_k50')
    s = ImportSession(src, field_map={'Гост-Ту': 'Документ', 'Вид+Раздел': 'Тип'},
                      config={'lib_name': 'K50-35'})
    s.validate(); s.group()
    s.apply_field_map_props()
    from component_import.cli import upload_session
    cli, created = upload_session(s, '', '', 'K50-35', dry_run=True)
    assert created == 65
    syms = [p['payload'] for p in cli.payloads
            if p['endpoint'] == '/api/component_symbols']
    assert len(syms) == 65 and syms[0]['role'] == 'gost'
    assert any(x['symbol_id'] == 'K50-35:K50-35-100В-10' for x in syms)
    eps = [p['endpoint'] for p in cli.payloads]
    assert eps.count('/api/parts') == 65
    params = [p['payload'] for p in cli.payloads if p['endpoint'] == '/api/parameters']
    names = {p['name'] for p in params}
    # поля из исходной библиотеки: Масса/Высота есть всегда; Документ — после маппинга
    # (маппинг применяется при write_fixed; в props исходное имя) -> проверяем сырые
    assert {'Масса', 'Высота', 'Документ', 'Тип'} <= names
    doc = [p for p in params if p['name'] == 'Документ'][0]
    assert doc['value_text'] == 'ОЖ0.464.214 ТУ'
    assert all(p['element'].startswith('dry://') for p in params)
