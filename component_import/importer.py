# -*- coding: utf-8 -*-
"""Конвейер мастера импорта (Л-7): группировка в детали, слияние приёмки,
маппинг полей, автоисправления с протоколом, запись исправленной библиотеки."""
from __future__ import annotations
import os, re, csv, shutil
from collections import defaultdict
from .kicad import load_dir, resolve_footprint
from . import rules as R

DEFAULT_CONFIG = {
    'acceptance_suffixes': {'-А': '5', '-A': '5'},   # суффикс -> код приёмки
    'acceptance_fields': ['Наименование', 'Код ОКП'],  # поля, зависящие от приёмки
    'status_map': [  # regex по полю -> статус ЖЦ (позднее правило перекрывает раннее)
        (r'в новых разработках не применять', 'Не для новых разработок', 'Примечание'),
        (r'сданы в архив', 'Архив', 'Вид'),
    ],
    'required_fields': ['Наименование'],
    'lib_name': None,      # имя выходной библиотеки (по умолчанию — из имени файла)
    'threed_var': 'COMPONENT_3D',
}


class ImportSession:
    def __init__(self, src_dir: str, field_map: dict | None = None, config: dict | None = None):
        self.cfg = {**DEFAULT_CONFIG, **(config or {})}
        self.field_map = field_map or {}
        self.header, self.symbols, self.footprints = load_dir(src_dir)
        self.issues: list[R.Issue] = []
        self.fix_log: list[str] = []
        self.parts: dict = {}

    # ---------- 1. валидация ----------
    def validate(self):
        self.issues = []
        for s in self.symbols:
            self.issues += R.v3_pin_numbering(s)
            self.issues += R.v4_pin_types(s)
            self.issues += R.v6_fields(s, self.cfg['required_fields'])
            self.issues += R.v2_symbol_footprint(s, self.footprints)
        for fp in self.footprints.values():
            self.issues += R.v5_footprint_geometry(fp)
        return self.issues

    # ---------- 2. группировка: детали и приёмка ----------
    def group(self):
        base_of = {}
        for s in self.symbols:
            for suf, code in self.cfg['acceptance_suffixes'].items():
                if s.name.endswith(suf):
                    base_of[s.name] = (s.name[:-len(suf)], code)
                    break
            else:
                base_of[s.name] = (s.name, '')
        self.parts = {}
        for s in self.symbols:
            base, code = base_of[s.name]
            part = self.parts.setdefault(base, {'symbols': {}, 'acceptances': {}})
            part['symbols'][code] = s
            part['acceptances'][code] = {f: s.props.get(f, '') for f in self.cfg['acceptance_fields']}
        # деталь без базового варианта (только -А) — предупреждение
        for base, part in self.parts.items():
            if '' not in part['symbols']:
                self.issues.append(R.Issue('Л-7', 'manual', base,
                                           'есть только вариант с приёмкой, базового нет'))
        self.issues += R.v9_uniqueness(self.parts)
        return self.parts

    def apply_field_map_props(self):
        """Применить маппинг полей к props символов (для выгрузки в Part-DB —
        та же логика, что write_fixed применяет к тексту)."""
        enc = lambda v: R.ENC_ARTIFACT.sub(lambda m: m.group(0)[0] + 'я', v)
        for s in self.symbols:
            for old, new in self.field_map.items():
                if '+' in old:
                    val = ' '.join(x for x in
                                   (s.props.get(p.strip(), '').strip() for p in old.split('+')) if x)
                    if val:
                        s.props[new] = enc(val)
                elif old in s.props and old != new:
                    s.props[new] = s.props.pop(old)

    # ---------- 3. автоисправления (текстовые, с протоколом) ----------
    def _fix_symbol_text(self, text: str, sym) -> str:
        name = sym.name
        text, n = R.ENC_ARTIFACT.subn(lambda m: m.group(0)[0] + 'я', text)
        if n: self.fix_log.append(f'{name}: кодировка — {n} замен')
        # тип выводов правим ТОЛЬКО если правило класса требует passive (В-4)
        want = R.DEFAULT_CLASS_RULES.get((sym.props.get('Reference') or ' ')[0].upper(), {}).get('etype')
        if want == 'passive':
            text, n = re.subn(r'\(pin (?:input|output|unspecified) line', '(pin passive line', text)
            if n: self.fix_log.append(f'{name}: тип выводов -> passive — {n}')
        def fix_name(m):
            return f'(name "{m.group(2)}"{m.group(1)}(number "{m.group(2)}"'
        text, n = re.subn(r'\(name "\d+"((?:(?!\(number)[\s\S])*?)\(number "(\d+)"', fix_name, text)
        # считаем только реальные замены (regex матчит и совпадающие пары)
        return text

    def write_fixed(self, out_dir: str):
        lib = self.cfg['lib_name'] or 'library'
        shutil.rmtree(out_dir, ignore_errors=True)
        os.makedirs(f'{out_dir}/{lib}.pretty')
        os.makedirs(f'{out_dir}/{lib}.3dshapes')
        # --- символы: одна деталь = один символ базового варианта ---
        blocks = []
        for base, part in sorted(self.parts.items()):
            s = part['symbols'].get('') or next(iter(part['symbols'].values()))
            text = self._fix_symbol_text(s.raw, s)
            # маппинг имён полей: 1:1 переименование и составной "A+B" -> новое поле
            for old, new in self.field_map.items():
                if '+' in old:
                    parts_v = [s.props.get(p.strip(), '').strip() for p in old.split('+')]
                    val = R.ENC_ARTIFACT.sub(lambda m: m.group(0)[0] + 'я',
                                             ' '.join(v for v in parts_v if v))
                    if val:
                        text = text.replace('\t\t(property "Reference"',
                                            _prop(new, val) + '\t\t(property "Reference"', 1)
                        self.fix_log.append(f'{s.name}: поле "{new}" собрано из "{old}"')
                elif old != new:
                    text, n = re.subn(rf'\(property "{re.escape(old)}"', f'(property "{new}"', text)
                    if n: self.fix_log.append(f'{s.name}: поле "{old}" -> "{new}"')
            # ссылка на футпринт: разрешить, санировать, добавить имя библиотеки
            orig_ref = s.props.get('Footprint', '')
            resolved = resolve_footprint(orig_ref, self.footprints)
            safe = sanitize_name(resolved or orig_ref.split(':', 1)[-1])
            if safe != (resolved or orig_ref):
                self.fix_log.append(f'{s.name}: футпринт "{orig_ref}" -> "{lib}:{safe}"')
            # значение занимает всю строку открытия свойства — заменяем строку целиком
            text = re.sub(r'^(\s*)\(property "Footprint" .*$',
                          rf'\1(property "Footprint" "{lib}:{safe}"',
                          text, count=1, flags=re.M)
            # статус ЖЦ из текста примечания
            status = ''
            for rx, st, fld in self.cfg['status_map']:
                if re.search(rx, s.props.get(fld, ''), re.I):
                    status = st
            add = ''
            for code, fields in sorted(part['acceptances'].items()):
                if code == '':
                    continue
                for f, v in fields.items():
                    add += _prop(f'Приёмка {code}. {f}', v.strip())
                self.fix_log.append(f'{base}: слит вариант приёмки "{code}"')
            if status:
                add += _prop('Статус', status)
            text = text.replace('\t\t(property "Reference"', add + '\t\t(property "Reference"', 1)
            blocks.append(text)
        with open(f'{out_dir}/{lib}.kicad_sym', 'w', encoding='utf-8') as f:
            f.write(self.header + ''.join(blocks) + ')\n')
        # --- футпринты: масштаб дюймы->мм, ссылка на 3D ---
        used = {resolve_footprint(p['symbols'][next(iter(p['symbols']))].props.get('Footprint', ''),
                                  self.footprints) for p in self.parts.values()}
        heights = self._heights_by_fp()
        for fpname in sorted(x for x in used if x):
            fp = self.footprints[fpname]
            safe = sanitize_name(fpname)
            text, n = re.subn(r'\((size|drill) ([\d. ]+)\)', _scale_line, fp.raw)
            if any(max(p.size or (1,)) < 0.13 for p in fp.pads):
                self.fix_log.append(f'{safe}: пересчёт дюймы->мм')
            if safe != fpname:
                # имя занимает всю первую строку файла — заменяем строку целиком
                text = re.sub(r'^\(footprint .*$', f'(footprint "{safe}"',
                              text, count=1, flags=re.M)
                self.fix_log.append(f'футпринт "{fpname}" переименован в "{safe}"')
            model = (f'\t(model "${{{self.cfg["threed_var"]}}}/{safe}.wrl"\n'
                     '\t\t(offset (xyz 0 0 0))\n\t\t(scale (xyz 1 1 1))\n\t\t(rotate (xyz 0 0 0))\n\t)\n')
            text = text.rstrip()[:-1].rstrip() + '\n' + model + ')\n'
            open(f'{out_dir}/{lib}.pretty/{safe}.kicad_mod', 'w', encoding='utf-8').write(text)
            wrl = _wrl_stub(safe, fp, heights.get(fpname))
            if wrl:
                open(f'{out_dir}/{lib}.3dshapes/{safe}.wrl', 'w', encoding='utf-8').write(wrl)
                self.fix_log.append(f'{safe}: 3D-заглушка')
        if self.symbols:
            orphans = set(self.footprints) - used
            for o in sorted(orphans):
                self.issues.append(R.Issue('Л-8', 'manual', o,
                                           'футпринт не используется ни одной деталью («сирота»)'))
        else:
            # библиотека «только посадочные места» (узлы/платы): сироты не считаем,
            # футпринты выписываем все
            for fpname in sorted(set(self.footprints) - {x for x in used if x}):
                fp = self.footprints[fpname]
                safe = sanitize_name(fpname)
                text, _ = re.subn(r'\((size|drill) ([\d. ]+)\)', _scale_line, fp.raw)
                open(f'{out_dir}/{lib}.pretty/{safe}.kicad_mod', 'w', encoding='utf-8').write(text)
        return out_dir

    def _heights_by_fp(self):
        h = {}
        for part in self.parts.values():
            s = next(iter(part['symbols'].values()))
            fp = resolve_footprint(s.props.get('Footprint', ''), self.footprints)
            try:
                v = float(s.props.get('Высота', ''))
            except ValueError:
                continue
            if fp:
                h[fp] = max(h.get(fp, 0), v)
        return h


def sanitize_name(name: str) -> str:
    """Санация имени футпринта/файла: кавычки, бэкслэши, запрещённые символы -> '_'."""
    out = re.sub(r'[\\\\"\'<>:|?*]+', '', name)
    out = re.sub(r'\s+', '_', out).strip('_')
    return out or 'unnamed'


def _prop(name, value, indent='\t\t'):
    return (f'{indent}(property "{name}" "{value}"\n'
            f'{indent}\t(at 0 0 0)\n{indent}\t(show_name no)\n{indent}\t(do_not_autoplace no)\n'
            f'{indent}\t(hide yes)\n{indent}\t(effects\n{indent}\t\t(font\n{indent}\t\t\t(size 1.27 1.27)\n'
            f'{indent}\t\t)\n{indent}\t)\n{indent})\n')

def _scale_line(m):
    vals = [float(v) for v in m.group(2).split()]
    for _ in range(2):   # встречается и двойная ошибка единиц (0.0019 = мм/25.4/25.4)
        if max(vals) < 0.13:
            vals = [round(v * 25.4, 4) for v in vals]
    return f"({m.group(1)} " + ' '.join(str(v) for v in vals) + ")"

def _wrl_stub(fpname, fp, height):
    m = re.match(r'^([\d.]+)X([\d.]+)(?:X([\d.]+))?$', fpname)
    if not m:
        return None
    D = float(m.group(1))
    H = float(m.group(3)) if m.group(3) else (height or D * 1.8)
    terms = [p for p in fp.pads if p.number in ('1', '2')] or \
            [p for p in fp.pads if p.number in ('1', '3')]
    cx = sum(p.at[0] for p in terms) / len(terms)
    cy = sum(p.at[1] for p in terms) / len(terms)
    u = 2.54
    return f"""#VRML V2.0 utf8
# Заглушка мастера импорта: корпус D{D} x H{H} мм, футпринт {fpname}
Transform {{
  translation {cx/u:.4f} {-cy/u:.4f} {H/2/u:.4f}
  rotation 1 0 0 1.5708
  children [ Shape {{
    appearance Appearance {{ material Material {{
      diffuseColor 0.55 0.62 0.68 specularColor 0.7 0.7 0.7 shininess 0.6 }} }}
    geometry Cylinder {{ radius {D/2/u:.4f} height {H/u:.4f} }} }} ]
}}
"""

def load_field_map(path: str) -> dict:
    """CSV 'старое;новое' -> dict."""
    out = {}
    with open(path, encoding='utf-8-sig') as f:
        for row in csv.reader(f, delimiter=';'):
            if len(row) >= 2 and row[0].strip() and not row[0].startswith('#'):
                out[row[0].strip()] = row[1].strip()
    return out
