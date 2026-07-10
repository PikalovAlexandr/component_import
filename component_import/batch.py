"""Массовый импорт (веха М1): поточная обработка каталога с десятками
PCAD-библиотек «от чистых к грязным».

Обнаружение: каждая пара <Имя>.kicad_sym + <Имя>.pretty/ (или .kicad_mod рядом)
— одна библиотека; правило категорий: одна библиотека = одна категория Part-DB
(дерево классификатора библиотекарь строит потом в UI).

Режимы:
- plan: быстрый анализ всех библиотек, ранжирование по «грязности»
  (доля error-находок на деталь) — порядок работ библиотекаря;
- run:  обработка в этом порядке: валидация -> исправление -> верификация ->
  (опц.) выгрузка; отчёт на библиотеку + сводный отчёт/CSV.
"""
from __future__ import annotations
import os, csv, glob, tempfile
from dataclasses import dataclass, asdict
from .importer import ImportSession
from .cli import upload_session


@dataclass
class LibResult:
    name: str
    symbols: int = 0
    parts: int = 0
    footprints: int = 0
    errors: int = 0
    manual: int = 0
    fixable: int = 0
    residual_errors: int = -1      # после автоисправлений (-1 = не запускалось)
    created: int = 0
    skipped: int = 0
    status: str = ''
    error_text: str = ''

    @property
    def dirt(self) -> float:
        """«Грязность»: неисправимые ошибки на деталь (для ранжирования)."""
        return (self.errors - self.fixable) / max(self.parts, 1)


def discover(root: str) -> list[tuple[str, str, list[str]]]:
    """-> [(имя, путь_к_.kicad_sym, [каталоги/файлы футпринтов])]."""
    out = []
    for sym in sorted(glob.glob(os.path.join(root, '**', '*.kicad_sym'),
                                recursive=True)):
        stem = os.path.splitext(os.path.basename(sym))[0]
        d = os.path.dirname(sym)
        fps = []
        pretty = os.path.join(d, stem + '.pretty')
        if os.path.isdir(pretty):
            fps = [pretty]
        else:
            mods = glob.glob(os.path.join(d, '*.kicad_mod'))
            if mods:
                fps = [d]
        out.append((stem, sym, fps))
    return out


def _stage_dir(sym: str, fps: list[str], tmp: str) -> str:
    """Собрать каталог библиотеки для ImportSession (символ + футпринты)."""
    os.makedirs(tmp, exist_ok=True)
    os.symlink(os.path.abspath(sym), os.path.join(tmp, os.path.basename(sym)))
    for src in fps:
        if os.path.isdir(src) and src.endswith('.pretty'):
            os.symlink(os.path.abspath(src),
                       os.path.join(tmp, os.path.basename(src)))
        else:
            for mod in glob.glob(os.path.join(src, '*.kicad_mod')):
                os.symlink(os.path.abspath(mod),
                           os.path.join(tmp, os.path.basename(mod)))
    return tmp


def analyze(name: str, sym: str, fps: list[str], field_map: dict,
            tu_docs: list | None = None) -> tuple[LibResult, ImportSession | None]:
    r = LibResult(name=name)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            sess = ImportSession(_stage_dir(sym, fps, os.path.join(tmp, 'lib')),
                                 field_map=field_map, config={'lib_name': name})
            sess.validate()
            sess.group()
            for doc in (tu_docs or []):
                from .tudoc import v7_check
                sess.issues += v7_check(sess.parts,
                                        {x.name: x for x in sess.symbols}, doc)
            r.symbols = len(sess.symbols)
            r.parts = len(sess.parts)
            r.footprints = len(sess.footprints)
            r.errors = sum(1 for i in sess.issues if i.severity == 'error')
            r.manual = sum(1 for i in sess.issues if i.severity == 'manual')
            r.fixable = sum(1 for i in sess.issues
                            if i.severity == 'error' and i.fixable)
            r.status = 'проанализирована'
            return r, sess
        except Exception as e:                       # noqa: BLE001 — поток не падает
            r.status, r.error_text = 'СБОЙ РАЗБОРА', f'{type(e).__name__}: {e}'
            return r, None


def process(name: str, sym: str, fps: list[str], out_root: str, field_map: dict,
            tu_docs=None, upload_url: str = '', token: str = '',
            dry_run: bool = True) -> LibResult:
    r, _ = analyze(name, sym, fps, field_map, tu_docs)
    if r.status == 'СБОЙ РАЗБОРА':
        return r
    with tempfile.TemporaryDirectory() as tmp:
        sess = ImportSession(_stage_dir(sym, fps, os.path.join(tmp, 'lib')),
                             field_map=field_map, config={'lib_name': name})
        sess.validate()
        sess.group()
        out_dir = os.path.join(out_root, name)
        try:
            fixed = sess.write_fixed(out_dir)
            check = ImportSession(fixed, config={'lib_name': name})
            check.validate()
            r.residual_errors = sum(1 for i in check.issues
                                    if i.severity == 'error'
                                    and i.rule in ('В-3', 'В-4', 'В-5', 'В-6'))
            from .cli import make_report
            make_report(sess, os.path.join(out_root, f'ОТЧЁТ_{name}.md'), name)
            if upload_url or dry_run:
                cli, created = upload_session(sess, upload_url, token, name,
                                              dry_run=dry_run or not upload_url)
                r.created, r.skipped = created, cli.skipped
            r.status = ('ГОТОВА' if r.residual_errors == 0 else
                        f'ОСТАТОК {r.residual_errors} ошибок')
        except Exception as e:                       # noqa: BLE001
            r.status, r.error_text = 'СБОЙ ОБРАБОТКИ', f'{type(e).__name__}: {e}'
    return r


def summary(results: list[LibResult], out_root: str):
    """Сводный отчёт MD + CSV по всем библиотекам."""
    os.makedirs(out_root, exist_ok=True)
    cpath = os.path.join(out_root, 'СВОДКА.csv')
    cols = ['name', 'status', 'symbols', 'parts', 'footprints', 'errors',
            'fixable', 'manual', 'residual_errors', 'created', 'skipped',
            'error_text']
    with open(cpath, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=cols, delimiter=';',
                           extrasaction='ignore')
        w.writeheader()
        for r in results:
            w.writerow(asdict(r))
    tot = lambda a: sum(getattr(r, a) for r in results)
    ready = sum(1 for r in results if r.status == 'ГОТОВА')
    fails = [r for r in results if r.status.startswith('СБОЙ')]
    lines = ['# Сводный отчёт массового импорта', '',
             f'Библиотек: {len(results)} | готово начисто: {ready} | '
             f'сбоев: {len(fails)}',
             f'Символов: {tot("symbols")} | деталей: {tot("parts")} | '
             f'выгружено: {tot("created")} (пропущено {tot("skipped")})',
             f'Ошибок до исправлений: {tot("errors")} (исправимо '
             f'{tot("fixable")}) | на ручную проверку: {tot("manual")}', '',
             '| Библиотека | Статус | Деталей | error→остаток | manual | '
             'выгружено |', '|---|---|---|---|---|---|']
    for r in results:
        res = '' if r.residual_errors < 0 else str(r.residual_errors)
        lines.append(f'| {r.name} | {r.status} | {r.parts} | '
                     f'{r.errors}→{res} | {r.manual} | {r.created} |')
    if fails:
        lines += ['', '## Сбои', '']
        lines += [f'- **{r.name}**: {r.error_text}' for r in fails]
    mpath = os.path.join(out_root, 'СВОДКА.md')
    open(mpath, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    return mpath, cpath
