"""Тесты этапа 2 = приёмочные сценарии ПИ-3 (переключение ГОСТ/IEC без смены
позиционных обозначений, аудит) и ПИ-4 («сломанная» пара УГО не проходит)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from component_import.importer import ImportSession
from component_import import dual, project

SRC = os.path.join(os.path.dirname(__file__), 'golden_k50')

SCH_TEMPLATE = """(kicad_sch
\t(version 20241209)
\t(generator "test")
\t(symbol
\t\t(lib_id "{lib}:K50-35-100В-10")
\t\t(at 100 100 0)
\t\t(property "Reference" "C1"
\t\t\t(at 0 0 0)
\t\t)
\t)
\t(symbol
\t\t(lib_id "{lib}:K50-35-63В-470")
\t\t(at 120 100 0)
\t\t(property "Reference" "C2"
\t\t\t(at 0 0 0)
\t\t)
\t)
)
"""

def _make_views(tmp_path):
    s = ImportSession(SRC, config={'lib_name': 'K50-35'})
    s.validate(); s.group()
    fixed = s.write_fixed(str(tmp_path / 'K50-35'))
    lib = os.path.join(fixed, 'K50-35.kicad_sym')
    # «вторая» библиотека (роль IEC): пока — клон (пары валидны по построению)
    return dual.emit_views(lib, lib, str(tmp_path), 'K50-35')


def test_pi4_broken_pair_blocks_release(tmp_path):
    g_path, i_path = _make_views(tmp_path)
    pairs, og, oi = dual.load_pairs(g_path, i_path)
    assert len(pairs) == 65 and not og and not oi
    assert dual.check_pairs(pairs) == []          # исправная пара проходит
    # ломаем один вывод в IEC-представлении
    text = open(i_path, encoding='utf-8').read()
    text = text.replace('(number "2"', '(number "9"', 1)
    open(i_path, 'w', encoding='utf-8').write(text)
    pairs, _, _ = dual.load_pairs(g_path, i_path)
    issues = dual.release_gate(pairs, [], [])
    broken = [i for i in issues if i.severity == 'error' and i.rule == 'В-1']
    assert len(broken) >= 1                        # деталь не может стать «разрешён»


def test_pi3_switch_preserves_references(tmp_path):
    g_path, i_path = _make_views(tmp_path)
    sch = tmp_path / 'demo.kicad_sch'
    sch.write_text(SCH_TEMPLATE.format(lib='K50-35-GOST'), encoding='utf-8')
    before = [c.reference for c in project.list_components(str(sch))]
    counts = project.switch_view(str(sch), {'K50-35-GOST': 'K50-35-IEC'})
    assert counts == {'K50-35-GOST': 2}
    comps = project.list_components(str(sch))
    assert [c.reference for c in comps] == before == ['C1', 'C2']
    assert {c.lib for c in comps} == {'K50-35-IEC'}
    # обратно
    project.switch_view(str(sch), {'K50-35-IEC': 'K50-35-GOST'})
    assert {c.lib for c in project.list_components(str(sch))} == {'K50-35-GOST'}


def test_pi3_audit_statuses(tmp_path):
    g_path, i_path = _make_views(tmp_path)
    sch = tmp_path / 'demo.kicad_sch'
    sch.write_text(SCH_TEMPLATE.format(lib='K50-35-GOST'), encoding='utf-8')
    issues = project.audit(str(sch), {'K50-35-GOST': g_path})
    # у серии в поле «Вид» — «Сданы в архив»: статус «Архив» -> применение запрещено
    errs = [i for i in issues if i.severity == 'error']
    assert len(errs) == 2 and {i.obj for i in errs} == {'C1', 'C2'}
    assert all('Архив' in i.message for i in errs)
    # компонент из невыпущенной библиотеки -> ошибка
    sch2 = tmp_path / 'demo2.kicad_sch'
    sch2.write_text(SCH_TEMPLATE.format(lib='Старая_Либа'), encoding='utf-8')
    errs = project.audit(str(sch2), {'K50-35-GOST': g_path})
    assert all(i.severity == 'error' for i in errs) and len(errs) == 2
