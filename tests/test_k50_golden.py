# -*- coding: utf-8 -*-
"""«Золотой» тест на серии К50-35 = приёмочные испытания ПИ-1/ПИ-2 в виде CI-теста."""
import os, sys, collections
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from component_import.importer import ImportSession

SRC = os.environ.get('K50_SRC', os.path.join(os.path.dirname(__file__), 'golden_k50'))

def make():
    s = ImportSession(SRC, config={'lib_name': 'K50-35'})
    s.validate(); s.group()
    return s

def test_pi1_grouping():
    s = make()
    assert len(s.symbols) == 130
    assert len(s.parts) == 65
    # каждая деталь имеет базовый вариант и приёмку «5»
    assert all(set(p['acceptances']) == {'', '5'} for p in s.parts.values())
    # у всех пар различается «Код ОКП»
    diff = sum(1 for p in s.parts.values()
               if p['acceptances']['']['Код ОКП'] != p['acceptances']['5']['Код ОКП'])
    assert diff == 65

def test_pi1_defect_counts():
    s = make()
    c = collections.Counter((i.rule, i.severity) for i in s.issues)
    assert c[('В-3', 'error')] == 8          # имя != номер (по 1 выводу в 8 символах)
    assert c[('В-4', 'error')] == 8          # типы input/output
    assert sum(n for (r, sev), n in c.items() if r == 'В-6' and sev == 'error') == 260
    assert c[('В-5', 'error')] == 13         # футпринтов с дюймовым дефектом (агрегировано)
    assert c[('В-2', 'manual')] > 0          # неклассифицированные площадки 3/4

def test_pi2_fix_and_verify(tmp_path):
    s = make()
    out = s.write_fixed(str(tmp_path / 'K50-35'))
    check = ImportSession(out, config={'lib_name': 'K50-35'})
    check.validate()
    errors = [i for i in check.issues
              if i.severity == 'error' and i.rule in ('В-3', 'В-4', 'В-5', 'В-6')]
    assert errors == []
    # 3D-заглушки созданы для всех используемых футпринтов
    assert len(os.listdir(os.path.join(out, 'K50-35.3dshapes'))) == 12
