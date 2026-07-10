"""Этап 2: двойное УГО (FR-8, Л-2/Л-3).
Пара символов ГОСТ/IEC на деталь; сверка В-1; генерация двух представлений
библиотеки: <lib>-GOST.kicad_sym и <lib>-IEC.kicad_sym с одинаковыми именами
деталей и полями — отличается только графика."""
from __future__ import annotations
import os
import re
import csv
from .kicad import load_symbol_lib, Symbol
from . import rules as R


def load_pairs(gost_lib: str, iec_lib: str, mapping: dict | None = None):
    """Загрузка двух библиотек и сопоставление пар по имени (или по mapping
    'имя_гост -> имя_iec'). Возвращает (pairs, only_gost, only_iec)."""
    _, gsyms = load_symbol_lib(gost_lib)
    _, isyms = load_symbol_lib(iec_lib)
    g = {s.name: s for s in gsyms}
    i = {s.name: s for s in isyms}
    mapping = mapping or {}
    pairs, used_i = [], set()
    for name, gs in g.items():
        iname = mapping.get(name, name)
        if iname in i:
            pairs.append((gs, i[iname]))
            used_i.add(iname)
    only_gost = sorted(set(g) - {p[0].name for p in pairs})
    only_iec = sorted(set(i) - used_i)
    return pairs, only_gost, only_iec


def check_pairs(pairs) -> list[R.Issue]:
    """В-1 для всех пар."""
    issues = []
    for gs, is_ in pairs:
        issues += R.v1_symbol_pair(gs, is_)
    return issues


def release_gate(pairs, only_gost, only_iec, require_both=False) -> list[R.Issue]:
    """Условие перевода в 'разрешён' (ТЗ п.4.3): пары без ошибок В-1;
    при require_both — наличие обоих УГО обязательно."""
    issues = check_pairs(pairs)
    if require_both:
        for n in only_gost:
            issues.append(R.Issue('В-1', 'error', n, 'нет варианта УГО IEC'))
        for n in only_iec:
            issues.append(R.Issue('В-1', 'error', n, 'нет варианта УГО ГОСТ'))
    else:
        for n in only_gost + only_iec:
            issues.append(R.Issue('В-1', 'warning', n, 'заполнен только один вариант УГО'))
    return issues


def emit_views(gost_lib: str, iec_lib: str, out_dir: str, base_name: str,
               mapping: dict | None = None):
    """Два представления: -GOST (полная библиотека) и -IEC (графика IEC, поля из ГОСТ-
    варианта — источник истины полей один). Имена символов в обоих одинаковы."""
    os.makedirs(out_dir, exist_ok=True)
    header_g, gsyms = load_symbol_lib(gost_lib)
    _, isyms = load_symbol_lib(iec_lib)
    i = {s.name: s for s in isyms}
    mapping = mapping or {}
    out_g, out_i = [], []
    for gs in gsyms:
        out_g.append(gs.raw)
        iname = mapping.get(gs.name, gs.name)
        if iname in i:
            it = i[iname].raw
            # имя символа в IEC-представлении = имени детали (как в ГОСТ)
            it = re.sub(r'^\t\(symbol "[^"]*"', f'\t(symbol "{gs.name}"', it, count=1, flags=re.M)
            it = re.sub(r'\(symbol "[^"]*_(\d+_\d+)"', rf'(symbol "{gs.name}_\1"', it)
            # поля — из ГОСТ-варианта (источник истины), кроме графических якорей
            it = _replace_props(it, gs)
            out_i.append(it)
        else:
            out_i.append(gs.raw)   # пары нет — временно та же графика (warning в release_gate)
    for suffix, blocks in (('GOST', out_g), ('IEC', out_i)):
        path = os.path.join(out_dir, f'{base_name}-{suffix}.kicad_sym')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(header_g + ''.join(blocks) + ')\n')
    return (os.path.join(out_dir, f'{base_name}-GOST.kicad_sym'),
            os.path.join(out_dir, f'{base_name}-IEC.kicad_sym'))


def _replace_props(iec_raw: str, gost_sym: Symbol) -> str:
    """Значения свойств IEC-блока <- из ГОСТ-символа (кроме Reference/Value позиций)."""
    for k, v in gost_sym.props.items():
        v_esc = v.replace('\\', '\\\\').replace('"', '\\"')
        iec_raw = re.sub(
            rf'(^\s*\(property "{re.escape(k)}" ").*?("\s*$)',
            lambda m: m.group(1) + v_esc + m.group(2),
            iec_raw, count=1, flags=re.M)
    return iec_raw


def load_pair_mapping(path: str) -> dict:
    """CSV 'имя_гост;имя_iec'."""
    out = {}
    with open(path, encoding='utf-8-sig') as f:
        for row in csv.reader(f, delimiter=';'):
            if len(row) >= 2 and row[0].strip() and not row[0].startswith('#'):
                out[row[0].strip()] = row[1].strip()
    return out
