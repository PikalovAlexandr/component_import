"""Валидаторы нормоконтроля В-1…В-6, В-9 (ТЗ «КОМПОНЕНТ», п.4.3).
Каждая проверка возвращает список Issue; severity: error | warning | manual."""
from __future__ import annotations
import re
from dataclasses import dataclass
from .kicad import Symbol, Footprint, resolve_footprint

@dataclass
class Issue:
    rule: str          # 'В-1' ... 'В-9'
    severity: str      # error / warning / manual
    obj: str           # имя символа/футпринта/детали
    message: str
    fixable: bool = False

ENC_ARTIFACT = re.compile(r'[а-яё]Я')   # пополняемый набор (В-6)

DEFAULT_CLASS_RULES = {
    # класс определяется по префиксу Reference; None -> без ограничений
    'C': {'etype': 'passive', 'name_eq_number': True},
    'R': {'etype': 'passive', 'name_eq_number': True},
    'L': {'etype': 'passive', 'name_eq_number': True},
}

def _class_of(sym: Symbol):
    return (sym.props.get('Reference') or ' ')[0].upper()


def v1_symbol_pair(gost: Symbol, iec: Symbol) -> list[Issue]:
    """В-1: сверка пары УГО ГОСТ/IEC."""
    issues = []
    g = {p.number: p for p in gost.pins}
    i = {p.number: p for p in iec.pins}
    for num in sorted(g.keys() ^ i.keys()):
        issues.append(Issue('В-1', 'error', gost.name,
                            f'вывод {num} есть только в одном из УГО (ГОСТ: {num in g}, IEC: {num in i})'))
    for num in sorted(g.keys() & i.keys()):
        if g[num].etype != i[num].etype:
            issues.append(Issue('В-1', 'error', gost.name,
                                f'вывод {num}: электрический тип ГОСТ={g[num].etype} != IEC={i[num].etype}'))
        if g[num].name != i[num].name:
            issues.append(Issue('В-1', 'warning', gost.name,
                                f'вывод {num}: имя ГОСТ="{g[num].name}" != IEC="{i[num].name}"'))
    return issues


def is_power_symbol(sym: Symbol) -> bool:
    """Символ питания (GND/VCC): посадочного места не имеет по определению."""
    return (sym.props.get('Reference', '').startswith('#')
            or '(power)' in sym.raw.split('(property', 1)[0])


def v2_symbol_footprint(sym: Symbol, footprints: dict, pad_classes: dict | None = None) -> list[Issue]:
    """В-2: каждый вывод имеет площадку; лишние площадки должны быть классифицированы.
    Символы питания пропускаются."""
    if is_power_symbol(sym):
        return []
    issues = []
    fpname = resolve_footprint(sym.props.get('Footprint', ''), footprints)
    if fpname is None:
        issues.append(Issue('В-2', 'error', sym.name,
                            f'посадочное место "{sym.props.get("Footprint","")}" не найдено'))
        return issues
    fp = footprints[fpname]
    padnums = {p.number for p in fp.pads}
    pinnums = {p.number for p in sym.pins}
    for num in sorted(pinnums - padnums):
        issues.append(Issue('В-2', 'error', sym.name, f'вывод {num} не имеет площадки в {fpname}'))
    extra = padnums - pinnums
    unclassified = {n for n in extra if not (pad_classes or {}).get((fpname, n))}
    if unclassified:
        issues.append(Issue('В-2', 'manual', sym.name,
                            f'{fpname}: площадки {sorted(unclassified)} не подключены к выводам и не '
                            f'классифицированы (токовая/крепёжная/NC) — требуется решение библиотекаря'))
    return issues


def v3_pin_numbering(sym: Symbol, class_rules=DEFAULT_CLASS_RULES) -> list[Issue]:
    """В-3: имя = номеру (для пассивных классов); номера образуют ряд 1..N."""
    issues = []
    rules = class_rules.get(_class_of(sym), {})
    if rules.get('name_eq_number'):
        for p in sym.pins:
            if p.name != p.number:
                issues.append(Issue('В-3', 'error', sym.name,
                                    f'вывод: имя "{p.name}" != номер "{p.number}"', fixable=True))
    nums = sorted(int(p.number) for p in sym.pins if p.number.isdigit())
    if nums and nums != list(range(1, len(nums) + 1)):
        issues.append(Issue('В-3', 'manual', sym.name,
                            f'номера выводов {nums} не образуют ряд 1..N — проверить соответствие площадкам'))
    return issues


def v4_pin_types(sym: Symbol, class_rules=DEFAULT_CLASS_RULES) -> list[Issue]:
    """В-4: электрический тип соответствует классу."""
    issues = []
    want = class_rules.get(_class_of(sym), {}).get('etype')
    if want:
        bad = sorted({p.etype for p in sym.pins if p.etype != want})
        if bad:
            issues.append(Issue('В-4', 'error', sym.name,
                                f'типы выводов {bad}, для класса требуется "{want}"', fixable=True))
    return issues


def v5_footprint_geometry(fp: Footprint) -> list[Issue]:
    """В-5: правдоподобие геометрии; детектор «дюймы как мм».
    Дефекты единиц агрегируются: одна запись на футпринт (иначе на библиотеках
    ИС отчёт превращается в десятки тысяч однотипных строк)."""
    issues = []
    inch_pads = [p for p in fp.pads if p.size and max(p.size) < 0.13]
    if inch_pads:
        ex = inch_pads[0]
        issues.append(Issue('В-5', 'error', fp.name,
                            f'{len(inch_pads)} из {len(fp.pads)} площадок — дюймы записаны как мм '
                            f'(например {ex.number}: {ex.size} -> '
                            f'{tuple(round(v*25.4,3) for v in ex.size)})', fixable=True))
    for p in fp.pads:
        if p.size and max(p.size) < 0.13:
            continue
        if p.size and max(p.size) < 0.25 and p.ptype == 'smd':
            issues.append(Issue('В-5', 'warning', fp.name,
                                f'площадка {p.number}: мелкая SMD-площадка {p.size} мм — проверить'))
            continue
        if p.drill is not None:
            if not (0.15 <= p.drill <= 6.0):
                issues.append(Issue('В-5', 'error', fp.name,
                                    f'площадка {p.number}: сверло {p.drill} мм вне 0.15–6'))
            elif p.size and min(p.size) < p.drill + 0.4:
                issues.append(Issue('В-5', 'warning', fp.name,
                                    f'площадка {p.number}: поясок {(min(p.size)-p.drill)/2:.3f} мм < 0.2'))
    return issues


def v6_fields(sym: Symbol, required: list[str] = ()) -> list[Issue]:
    """В-6: кодировка, обязательность полей.
    У символов питания (#PWR/power) обязательные поля ЕСКД не требуются:
    в перечень элементов они не попадают (СВОДКА М1: ПИТАНИЕ 275->275)."""
    issues = []
    for k, v in sym.props.items():
        if ENC_ARTIFACT.search(v):
            issues.append(Issue('В-6', 'error', sym.name,
                                f'поле "{k}": артефакт кодировки в "{v.strip()}"', fixable=True))
    if not is_power_symbol(sym):
        for k in required:
            if not sym.props.get(k, '').strip():
                issues.append(Issue('В-6', 'error', sym.name,
                                    f'обязательное поле "{k}" не заполнено'))
    return issues


def v9_uniqueness(parts: dict) -> list[Issue]:
    """В-9: уникальность наименований (с учётом приёмки)."""
    issues, seen = [], {}
    for base, data in parts.items():
        for acc, props in data.get('acceptances', {}).items():
            nm = props.get('Наименование', '').strip()
            if nm and nm in seen:
                issues.append(Issue('В-9', 'error', base,
                                    f'наименование "{nm}" дублирует деталь {seen[nm]}'))
            seen[nm] = base
    return issues
