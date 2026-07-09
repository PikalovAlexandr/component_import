"""Разбор форматов KiCad: s-expression, библиотеки символов, посадочные места."""
from __future__ import annotations
import re, os
from dataclasses import dataclass, field

_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|\(|\)|[^\s()]+')

def parse_sexpr(text: str):
    stack = [[]]
    for m in _TOKEN.finditer(text):
        t = m.group(0)
        if t == '(':
            stack.append([])
        elif t == ')':
            node = stack.pop()
            stack[-1].append(node)
        else:
            if t.startswith('"') and t.endswith('"') and len(t) >= 2:
                t = t[1:-1].replace('\\"', '"')
            stack[-1].append(t)
    if len(stack) != 1:
        raise ValueError("несбалансированные скобки s-expression")
    return stack[0]

def children(node, key):
    return [x for x in node if isinstance(x, list) and x and x[0] == key]

def child_val(node, key, idx=1):
    c = children(node, key)
    return c[0][idx] if c else None


@dataclass
class Pin:
    number: str
    name: str
    etype: str
    hidden: bool = False

@dataclass
class Symbol:
    name: str
    props: dict = field(default_factory=dict)
    pins: list = field(default_factory=list)
    raw: str = ""            # исходный текст блока (для текстовых трансформаций)

@dataclass
class Pad:
    number: str
    ptype: str                # thru_hole / smd / np_thru_hole
    at: tuple = (0.0, 0.0)
    size: tuple = None
    drill: float = None

@dataclass
class Footprint:
    name: str
    file: str
    pads: list = field(default_factory=list)
    raw: str = ""


def load_symbol_lib(path: str) -> tuple[str, list[Symbol]]:
    """Возвращает (шапка_файла, [Symbol]); raw каждого символа — точный текст блока."""
    text = open(path, encoding='utf-8').read()
    blocks = re.split(r'(?=^\t\(symbol ")', text, flags=re.M)
    header, blocks = blocks[0], blocks[1:]
    if blocks:
        blocks[-1] = blocks[-1].rstrip()
        assert blocks[-1].endswith(')')
        blocks[-1] = blocks[-1][:-1].rstrip() + '\n'   # снять закрывающую скобку файла
    symbols = []
    for b in blocks:
        node = parse_sexpr(b)[0]
        name = node[1]
        props = {}
        for p in children(node, 'property'):
            props[p[1]] = p[2] if len(p) > 2 and isinstance(p[2], str) else ""
        pins = []
        for unit in children(node, 'symbol'):
            for pin in children(unit, 'pin'):
                etype = pin[1] if len(pin) > 1 and isinstance(pin[1], str) else "?"
                pins.append(Pin(
                    number=child_val(pin, 'number') or "",
                    name=child_val(pin, 'name') or "",
                    etype=etype,
                    hidden=bool(children(pin, 'hide')),
                ))
        symbols.append(Symbol(name=name, props=props, pins=pins, raw=b))
    return header, symbols


def load_footprint(path: str) -> Footprint:
    text = open(path, encoding='utf-8').read()
    node = parse_sexpr(text)[0]
    pads = []
    for pad in children(node, 'pad'):
        size = children(pad, 'size')
        drill = children(pad, 'drill')
        at = children(pad, 'at')
        dval = None
        if drill:
            try:
                dval = float(drill[0][1])
            except (ValueError, IndexError):
                dval = None
        pads.append(Pad(
            number=pad[1],
            ptype=pad[2] if len(pad) > 2 else '?',
            at=(float(at[0][1]), float(at[0][2])) if at else (0.0, 0.0),
            size=tuple(float(v) for v in size[0][1:3]) if size else None,
            drill=dval,
        ))
    return Footprint(name=node[1], file=os.path.basename(path), pads=pads, raw=text)


def load_dir(path: str):
    """Каталог с *.kicad_sym и *.kicad_mod -> (header, [Symbol], {имя: Footprint})."""
    header, symbols, footprints = "", [], {}
    for fn in sorted(os.listdir(path)):
        full = os.path.join(path, fn)
        if fn.endswith('.kicad_sym'):
            header, symbols = load_symbol_lib(full)   # одна библиотека за прогон
        elif fn.endswith('.kicad_mod'):
            fp = load_footprint(full)
            footprints[fp.name] = fp
        elif fn.endswith('.pretty') and os.path.isdir(full):
            for sub in sorted(os.listdir(full)):
                if sub.endswith('.kicad_mod'):
                    fp = load_footprint(os.path.join(full, sub))
                    footprints[fp.name] = fp
    return header, symbols, footprints


def _norm_fp(s: str) -> str:
    """Нормализация имени футпринта: PCAD-конвертация меняет пробел/точку на '_',
    накапливает экранирование кавычек."""
    return s.replace('\\', '').replace(' ', '_').replace('.', '_')

def resolve_footprint(field_value: str, footprints: dict) -> str | None:
    """'8X2.5' или 'LIB:8X2.5' -> имя футпринта в наборе."""
    name = field_value.split(':', 1)[-1]
    if name in footprints:
        return name
    alt = _norm_fp(name)
    for k in footprints:
        if _norm_fp(k) == alt:
            return k
    return None
