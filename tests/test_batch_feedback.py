"""Доработки по итогам массового прогона PCAD (66 библиотек)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from component_import.kicad import Symbol, Pin
from component_import import rules as R
from component_import.importer import ImportSession

def test_power_symbols_skip_v2():
    pwr = Symbol(name='GND', props={'Reference': '#PWR', 'Footprint': ''},
                 pins=[Pin('1', 'GND', 'power_in')], raw='(symbol "GND" (power)')
    assert R.is_power_symbol(pwr)
    assert R.v2_symbol_footprint(pwr, {}) == []          # нет ошибки «место не найдено»
    usual = Symbol(name='C1x', props={'Reference': 'C', 'Footprint': 'NOPE'},
                   pins=[Pin('1', '1', 'passive')], raw='(symbol "C1x"')
    assert R.v2_symbol_footprint(usual, {})              # а у обычного — есть

def test_v5_aggregated_per_footprint():
    from component_import.kicad import Footprint, Pad
    fp = Footprint(name='DIP16', file='x', pads=[
        Pad(str(i), 'thru_hole', (0, 0), (0.02, 0.02), 0.01) for i in range(1, 17)])
    issues = R.v5_footprint_geometry(fp)
    inch = [i for i in issues if 'дюймы' in i.message]
    assert len(inch) == 1 and '16 из 16' in inch[0].message   # одна запись, не 16

def test_composite_field_map(tmp_path):
    src = os.path.join(os.path.dirname(__file__), 'golden_k50')
    s = ImportSession(src, field_map={'Вид+Раздел': 'Тип', 'Гост-Ту': 'Документ'},
                      config={'lib_name': 'K50-35'})
    s.validate(); s.group()
    out = s.write_fixed(str(tmp_path / 'K50-35'))
    text = open(os.path.join(out, 'K50-35.kicad_sym'), encoding='utf-8').read()
    assert '(property "Документ"' in text and '(property "Гост-Ту"' not in text
    assert '(property "Тип" "Сданы в архив Прочие изделия"' in text  # собрано из Вид+Раздел (в К50-35 «Вид» — статус!)
