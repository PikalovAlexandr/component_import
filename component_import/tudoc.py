"""В-7 (ТЗ п.4.3): сверка полей деталей с эталонной таблицей параметров,
привязанной к документу ТУ (FR-4a, ОП п.5).

Эталон описывается парой файлов, которые готовит библиотекарь:
1) YAML-конфиг документа: как из имени детали получить ключ таблицы и что сверять;
2) CSV-таблица параметров (черновик можно получать из PDF, подтверждение — ручное).

Пример YAML:
    doc: "ОЖ0.464.214 ТУ"
    table: tu_OZh0464214.csv
    key_regex: '^K50-35(?P<Серия>А|Б)?-(?P<U>[\\d,]+)В-(?P<C>[\\d,]+)$'
    checks:
      - {column: Масса,  field: Масса,  tolerance: "1%"}
      - {column: Высота, field: Высота, tolerance: "-0.5..+2.5"}   # зиг/выступы
    footprint_checks:
      name_regex: '^(?P<D>[\\d.]+)X(?P<A>[\\d.]+)'
      d_column: D
      d_tolerance: "-0.1..+1.1"        # изолированные корпуса на +1 мм толще
      pitch_by_d: [[8, 2.5], [14, 5], [21, 7.5]]   # D<=8 -> 2.5 и т.д.
CSV: колонки-ключи (имена групп key_regex) + колонки параметров; десятичная ','
или '.'; пустая ячейка = не сверять."""
from __future__ import annotations
import re, csv, os
import yaml
from .rules import Issue

_num = lambda s: float(str(s).replace(',', '.'))


class TuDoc:
    def __init__(self, cfg_path: str):
        self.cfg = yaml.safe_load(open(cfg_path, encoding='utf-8'))
        self.name = self.cfg['doc']
        self.key_re = re.compile(self.cfg['key_regex'])
        self.keys = list(self.key_re.groupindex)
        table = os.path.join(os.path.dirname(cfg_path), self.cfg['table'])
        self.rows = {}
        with open(table, encoding='utf-8-sig') as f:
            for row in csv.DictReader(f, delimiter=';'):
                key = tuple((row.get(k) or '').strip() for k in self.keys)
                self.rows[self._norm_key(key)] = row

    def _norm_key(self, key):
        out = []
        for v in key:
            try:
                out.append(f'{_num(v):g}')
            except ValueError:
                out.append(v)
        return tuple(out)

    def lookup(self, part_name: str):
        m = self.key_re.match(part_name)
        if not m:
            return None, None
        key = tuple((m.group(k) or '').strip() for k in self.keys)
        return key, self.rows.get(self._norm_key(key))


def _tol_ok(actual: float, ref: float, tol: str) -> bool:
    tol = str(tol).strip()
    if tol.endswith('%'):
        return abs(actual - ref) <= float(tol[:-1]) / 100 * max(abs(ref), 1e-9)
    if '..' in tol:
        lo, hi = tol.split('..')
        return ref + float(lo) <= actual <= ref + float(hi)
    return abs(actual - ref) <= float(tol or 0)


def v7_check(parts: dict, symbols_by_name: dict, doc: TuDoc) -> list[Issue]:
    issues = []
    fpc = doc.cfg.get('footprint_checks') or {}
    fp_re = re.compile(fpc['name_regex']) if fpc else None
    for base, part in sorted(parts.items()):
        sym = part['symbols'].get('') or next(iter(part['symbols'].values()))
        key, row = doc.lookup(base)
        if key is None:
            continue                      # деталь не этого документа
        if row is None:
            issues.append(Issue('В-7', 'error', base,
                                f'{doc.name}: строка {dict(zip(doc.keys, key))} в таблице не найдена'))
            continue
        # --- поля ---
        for chk in doc.cfg.get('checks', []):
            ref_s = (row.get(chk['column']) or '').strip()
            act_s = (sym.props.get(chk['field']) or '').strip()
            if not ref_s or not act_s:
                continue
            try:
                ref, act = _num(ref_s), _num(act_s)
            except ValueError:
                if ref_s != act_s:
                    issues.append(Issue('В-7', 'error', base,
                                        f'{doc.name}: {chk["field"]} = "{act_s}", по ТУ "{ref_s}"'))
                continue
            if not _tol_ok(act, ref, chk.get('tolerance', '0')):
                issues.append(Issue('В-7', 'error', base,
                                    f'{doc.name}: {chk["field"]} = {act:g}, по ТУ {ref:g} '
                                    f'(допуск {chk.get("tolerance", "0")})'))
        # --- посадочное место ---
        if fp_re:
            fp_name = (sym.props.get('Footprint') or '').split(':', 1)[-1]
            m = fp_re.match(fp_name)
            ref_d_s = (row.get(fpc['d_column']) or '').strip()
            if m and ref_d_s:
                fd, fa = _num(m.group('D')), _num(m.group('A'))
                ref_d = _num(ref_d_s)
                if not _tol_ok(fd, ref_d, fpc.get('d_tolerance', '0')):
                    issues.append(Issue('В-7', 'error', base,
                                        f'{doc.name}: корпус футпринта D{fd:g}, по ТУ D{ref_d:g}'))
                exp = _pitch_by_d(ref_d, fpc.get('pitch_by_d', []))
                if exp is not None and abs(fa - exp) > 0.01:
                    issues.append(Issue('В-7', 'error', base,
                                        f'{doc.name}: шаг выводов {fa:g}, для D{ref_d:g} по ТУ {exp:g}'))
    return issues


def _pitch_by_d(d: float, table) -> float | None:
    for dmax, pitch in table:
        if d <= float(dmax):
            return float(pitch)
    return None
