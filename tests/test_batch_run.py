"""component-batch: обнаружение, план, поточная обработка (веха М1)."""
import os, sys, shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from component_import import batch, cli_batch

HERE = os.path.dirname(__file__)

def _make_root(tmp_path):
    """Корень с двумя библиотеками: чистая копия golden и «сломанная»."""
    root = tmp_path / 'libs'
    for lib in ('K50-35', 'K50-BAD'):
        d = root / lib
        d.mkdir(parents=True)
        shutil.copy(os.path.join(HERE, 'golden_k50', 'C_K50-35.kicad_sym'),
                    d / f'{lib}.kicad_sym')
        pretty = d / f'{lib}.pretty'
        pretty.mkdir()
        for mod in os.listdir(os.path.join(HERE, 'golden_k50')):
            if mod.endswith('.kicad_mod'):
                shutil.copy(os.path.join(HERE, 'golden_k50', mod), pretty / mod)
    # «сломанная»: битый s-expression
    bad = root / 'K50-BAD' / 'K50-BAD.kicad_sym'
    bad.write_text(bad.read_text(encoding='utf-8')[:5000], encoding='utf-8')
    return str(root)

def test_discover_and_plan(tmp_path, capsys):
    root = _make_root(tmp_path)
    libs = batch.discover(root)
    assert [x[0] for x in libs] == ['K50-35', 'K50-BAD']
    assert cli_batch.main(['plan', root]) == 0
    out = capsys.readouterr().out
    assert 'СБОЙ РАЗБОРА' in out and 'K50-35' in out

def test_run_stream(tmp_path):
    root = _make_root(tmp_path)
    rc = cli_batch.main(['run', root, '-o', str(tmp_path / 'out'), '--dry-run'])
    assert rc == 1                                   # одна библиотека со сбоем
    md = (tmp_path / 'out' / 'СВОДКА.md').read_text(encoding='utf-8')
    assert 'готово начисто: 1' in md and 'сбоев: 1' in md
    assert (tmp_path / 'out' / 'ОТЧЁТ_K50-35.md').exists()
    assert (tmp_path / 'out' / 'K50-35' / 'K50-35.kicad_sym').exists()
    assert (tmp_path / 'out' / 'СВОДКА.csv').exists()
    # сбой одной библиотеки не убил поток и попал в сводку
    assert 'K50-BAD' in md
