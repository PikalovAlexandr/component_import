"""Этап 2: операции над проектом KiCad (.kicad_sch).
- switch_view: переключение библиотек ГОСТ<->IEC для всего проекта (Р-2);
  позиционные обозначения и netlist не меняются — заменяется только lib_id.
- audit: аудит проекта (FR-7): все ли компоненты из выпущенных библиотек,
  нет ли деталей со статусами «не для новых разработок»/«запрещён»."""
from __future__ import annotations
import re
import shutil
from dataclasses import dataclass
from .kicad import load_symbol_lib
from .rules import Issue

LIB_ID = re.compile(r'\(lib_id\s+"([^":]+):([^"]+)"\)')


@dataclass
class SchComponent:
    lib: str
    name: str
    reference: str


def list_components(sch_path: str) -> list[SchComponent]:
    text = open(sch_path, encoding='utf-8').read()
    comps = []
    # блоки размещённых символов: (symbol (lib_id "LIB:NAME") ... (property "Reference" "C1" ...
    for m in re.finditer(r'\(symbol\s*\n?\s*\(lib_id\s+"([^":]+):([^"]+)"\)'
                         r'[\s\S]*?\(property "Reference" "([^"]+)"', text):
        comps.append(SchComponent(lib=m.group(1), name=m.group(2), reference=m.group(3)))
    return comps


def switch_view(sch_path: str, lib_map: dict, out_path: str | None = None,
                backup: bool = True) -> dict:
    """Заменить имена библиотек по словарю {'K50-35-GOST': 'K50-35-IEC', ...}.
    Имена символов и все свойства не трогаются -> позиционные обозначения сохранены."""
    text = open(sch_path, encoding='utf-8').read()
    before = [c.reference for c in list_components(sch_path)]
    counts = {}
    def repl(m):
        lib, name = m.group(1), m.group(2)
        new = lib_map.get(lib, lib)
        if new != lib:
            counts[lib] = counts.get(lib, 0) + 1
        return f'(lib_id "{new}:{name}")'
    text = LIB_ID.sub(repl, text)
    dst = out_path or sch_path
    if backup and dst == sch_path:
        shutil.copy2(sch_path, sch_path + '.bak')
    open(dst, 'w', encoding='utf-8').write(text)
    after = [c.reference for c in list_components(dst)]
    assert before == after, 'позиционные обозначения изменились — откатите .bak'
    return counts


FORBIDDEN = {'Запрещён', 'Архив'}
WARN = {'Не для новых разработок'}


def audit(sch_path: str, lib_paths: dict) -> list[Issue]:
    """lib_paths: {'K50-35-GOST': путь к .kicad_sym, ...} (до появления БД —
    проверка по выпущенным файловым библиотекам)."""
    issues = []
    cache = {}
    for lib, path in lib_paths.items():
        _, syms = load_symbol_lib(path)
        cache[lib] = {s.name: s for s in syms}
    for c in list_components(sch_path):
        if c.lib not in cache:
            issues.append(Issue('FR-7', 'error', c.reference,
                                f'библиотека "{c.lib}" не входит в выпущенные'))
            continue
        sym = cache[c.lib].get(c.name)
        if sym is None:
            issues.append(Issue('FR-7', 'error', c.reference,
                                f'символ "{c.name}" не найден в "{c.lib}"'))
            continue
        status = sym.props.get('Статус', '').strip()
        if status in FORBIDDEN:
            issues.append(Issue('FR-7', 'error', c.reference,
                                f'{c.name}: статус «{status}» — применение запрещено'))
        elif status in WARN:
            issues.append(Issue('FR-7', 'warning', c.reference,
                                f'{c.name}: статус «{status}»'))
    return issues
