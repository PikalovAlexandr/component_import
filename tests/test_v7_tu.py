"""В-7 на золотом наборе: должны найтись те же 10 деталей, что в пилотном отчёте."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from component_import.importer import ImportSession
from component_import.tudoc import TuDoc, v7_check

HERE = os.path.dirname(__file__)

def test_v7_known_discrepancies():
    s = ImportSession(os.path.join(HERE, 'golden_k50'), config={'lib_name': 'K50-35'})
    s.validate(); s.group()
    doc = TuDoc(os.path.join(HERE, '..', 'config', 'tu_OZh0464214.yaml'))
    issues = v7_check(s.parts, {x.name: x for x in s.symbols}, doc)
    parts_flagged = sorted({i.obj for i in issues})
    expected = ['K50-35-100В-100', 'K50-35-16В-100', 'K50-35-16В-1000', 'K50-35-16В-220',
                'K50-35-16В-2200', 'K50-35-16В-470', 'K50-35-25В-47', 'K50-35-63В-22',
                'K50-35-6,3В-1000', 'K50-35-6,3В-2200']
    assert parts_flagged == sorted(expected)
    # шаг выводов у 100В-100 пойман отдельно
    assert any('шаг выводов' in i.message for i in issues if i.obj == 'K50-35-100В-100')
