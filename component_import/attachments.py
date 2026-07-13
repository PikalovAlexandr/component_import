"""Д-5 (FR-4a, FR-4b): вложения ТУ и SPICE-моделей.

Файлы живут в git (Gitea) — источник истины и версии (FR-4a); в Part-DB
создаётся вложение-ссылка (url на raw-файл Gitea с ревизией) у категории
(ТУ — один документ на серию) или у детали (SPICE-модель).

SPICE: помимо вложения, детали проставляются параметры группы «SPICE»
(Sim.Device, Sim.Type, Sim.Pins, Sim.Library, Sim.Name) с EDA-видимостью —
они доезжают до полей символа в KiCad (подтверждено стендом М0), и деталь
из базы сразу пригодна к симуляции. Валидация В-8: Sim.Pins сверяется
с выводами детали ДО выгрузки."""
from __future__ import annotations

SIM_FIELDS = ('Device', 'Type', 'Pins', 'Library', 'Name')


def sim_params(sim: dict) -> list[dict]:
    """{'Device':'C','Pins':'1 2',...} -> параметры группы SPICE для Part-DB."""
    out = []
    for key in SIM_FIELDS:
        if key in sim and str(sim[key]).strip():
            out.append({'name': f'Sim.{key}',
                        'value_text': str(sim[key]).strip(),
                        'group': 'SPICE'})
    return out


def check_sim_pins(sim: dict, part_pins: list[str]) -> list[str]:
    """В-8: каждый вывод из Sim.Pins существует у детали. -> список проблем."""
    problems = []
    pins_decl = str(sim.get('Pins', '')).split()
    if not pins_decl:
        return ['Sim.Pins не задан — порядок выводов модели неизвестен']
    have = set(part_pins)
    for p in pins_decl:
        # формат KiCad: "1=Plus 2=Minus" или просто "1 2"
        num = p.split('=', 1)[0]
        if num not in have:
            problems.append(f'Sim.Pins: вывод "{num}" отсутствует у детали '
                            f'(есть: {sorted(have)})')
    if len(pins_decl) != len(have):
        problems.append(f'Sim.Pins: заявлено {len(pins_decl)} выводов, '
                        f'у детали {len(have)}')
    return problems


def attachment_payload(name: str, url: str, element_iri: str,
                       attachment_type_iri: str) -> dict:
    """Вложение-ссылка Part-DB (файл — в git, версия — в url через ревизию)."""
    return {
        'name': name,
        'element': element_iri,
        'attachment_type': attachment_type_iri,
        'url': url,
    }


def gitea_raw_url(base: str, org: str, repo: str, path: str,
                  rev: str = 'main') -> str:
    """Стабильная raw-ссылка Gitea; с rev=коммит — иммутабельная (версия FR-4a)."""
    return f'{base.rstrip("/")}/{org}/{repo}/raw/{rev}/{path.lstrip("/")}'
