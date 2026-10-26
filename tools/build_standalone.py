"""Собирает hybrid_plus.py — один файл с симулятором и итоговым вариантом hybrid_plus.
Код берётся из ячеек 4_reliable_rreq.ipynb (до общих функций экспериментов включительно), без рисунков и проверок.
Запуск: python tools/build_standalone.py   (после python tools/build_studies.py 4_reliable_rreq)"""
import json, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "4_reliable_rreq.ipynb"
DST = ROOT / "hybrid_plus.py"
HELPERS = "# EXP: общие функции"

SKIP = ("_edges = [",)                                   # проверка DP на графе с доски
CUT = {                                                  # ячейка начинается с … → обрезать с маркера (демо-рисунок или таблица)
    "@dataclass\nclass RadioConfig": "# Справочная таблица ToA",
    "@dataclass\nclass ChannelConfig": "# Как качество зависит от расстояния",
    "def draw_topology": "_keys = [",
    "# ⚙️ Наш кейс": "fig, axes = plt.subplots",
}

HEADER = '''"""hybrid_plus — итоговый вариант маршрутизации для подвижной Mesh-сети LoRa (исследования 1–4).

    hybrid_plus = AODV (RFC 3561)
                + 4 доработки под LoRa             (исследование 1: aodv_lora)
                + первый пакет внутри RREQ
                  и «храни и неси»                  (исследование 2: hybrid)
                + бюджет эфира                      (исследование 3: hybrid_dc)
                + надёжный RREQ на цепочках         (исследование 4: hybrid_plus)

Один файл: модель LoRa, канал, узел, ядро дискретно-событийного симулятора, AODV со всеми механизмами,
контрольные методы (затопление, затопление ×3, эталон Дейкстры). Параметры итогового варианта —
AODV_PRESETS["hybrid_plus"]; их можно вывести: python hybrid_plus.py --config

Примеры:
    python hybrid_plus.py                                    # hybrid_plus, техника, случайные пары, 0,2 пак/с, 10 повторов
    python hybrid_plus.py --topo rwp20_walk --pattern sink   # пешеходы, все шлют узлу 0
    python hybrid_plus.py --methods hybrid_plus,dijkstra,flooding --rate 0.5 --seeds 1-20
    python hybrid_plus.py --topo line10 --pattern default    # неподвижная линия из исходного симулятора

Зависимости: Python 3.10+, pandas, matplotlib.
Файл сгенерирован из блокнота 4_reliable_rreq.ipynb скриптом tools/build_standalone.py — правки вносить в tools/cells/.
"""
'''

MAIN = '''

# ---------------------------------------------------------------------------------------------------------------------
def _parse_seeds(text):
    out = []
    for part in text.split(","):
        a, _, b = part.partition("-")
        out += list(range(int(a), int(b) + 1)) if b else [int(a)]
    return out


def _show_config(name):
    cfg, base = AODV_PRESETS[name], AodvConfig()
    print(f"{name}: отличия от AODV по RFC 3561 (AodvConfig по умолчанию)")
    for f in fields(AodvConfig):
        v, d = getattr(cfg, f.name), getattr(base, f.name)
        if v != d:
            print(f"  {f.name:24s} = {v!r:12}  (RFC: {d!r})")


def main():
    import argparse, sys
    if not sys.stdout.isatty():                  # вывод в канал или файл — всегда UTF-8
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="hybrid_plus и контрольные методы на сценариях исследования")
    p.add_argument("--methods", default="hybrid_plus",
                   help="через запятую: hybrid_plus, hybrid_dc, hybrid, aodv_lora, aodv_rfc, flooding, flooding_x3, dijkstra")
    p.add_argument("--topo", default="rwp20_vehicle", help="rwp20_walk | rwp20_vehicle | rwp20_drone | line10 | grid4x4 | …")
    p.add_argument("--pattern", default="random", help="random (случайные пары) | sink (все → узел 0) | default (поток топологии)")
    p.add_argument("--rate", type=float, default=0.2, help="суммарный трафик, пакетов/с на всю сеть")
    p.add_argument("--churn", action="store_true", help="узлы пропадают: в среднем 300 с работают, 30 с отсутствуют")
    p.add_argument("--seeds", default="1-10", help="например 1-10 или 1,2,5")
    p.add_argument("--n", type=int, default=None, help="число узлов (для rwp20_*)")
    p.add_argument("--area", type=float, default=None, help="сторона квадрата, м (для rwp20_*)")
    p.add_argument("--config", action="store_true", help="показать параметры hybrid_plus и выйти")
    a = p.parse_args()
    if a.config:
        _show_config("hybrid_plus")
        return
    rows = []
    for m in a.methods.split(","):
        for s in _parse_seeds(a.seeds):
            sc = make_scenario(a.topo, pattern=a.pattern, rate=a.rate, churn=a.churn, n=a.n, area=a.area)
            res, _ = simulate(sc, m.strip(), s)
            rows.append(res)
    df = pd.DataFrame(rows)
    g = df.groupby("method", sort=False)
    t = pd.DataFrame({"PDR за 20 с": g.pdr_20s.mean(), "± 95 %": 1.96 * g.pdr_20s.std() / g.pdr_20s.count() ** 0.5,
                      "путь существовал": g.reachable_share.mean(), "задержка ср., с": g.latency_mean_s.mean(),
                      "задержка p95, с": g.latency_p95_s.mean(), "эфир на пакет, с": g.airtime_per_delivered_s.mean()})
    print(f"{a.topo}, {a.pattern}, {a.rate} пак/с{', узлы пропадают' if a.churn else ''}, повторов: {len(_parse_seeds(a.seeds))}")
    print(t.round(3).to_string())


if __name__ == "__main__":
    main()
'''


def clean(src):
    lines = [l for l in src.splitlines() if not l.startswith("%")]
    return "\n".join(lines).rstrip()


nb = json.loads(SRC.read_text(encoding="utf-8"))
parts = []
for c in nb["cells"]:
    if c["cell_type"] != "code":
        continue
    s = "".join(c["source"])
    if s.startswith(SKIP) or s.startswith("RESULTS_DIR"):
        continue
    for start, marker in CUT.items():
        if s.startswith(start):
            assert marker in s, (start, marker)
            s = s[:s.index(marker)]
    parts.append(clean(s))
    if s.startswith(HELPERS):
        break
assert any(p.startswith("# ⚙️ Исследование 4") for p in parts), "нет ячейки hybrid_plus"

body = "\n\n\n".join(parts)
body = body.replace("from dataclasses import dataclass, field, replace", "from dataclasses import dataclass, field, fields, replace")
code = HEADER + "\nimport matplotlib\nmatplotlib.use(\"Agg\")                          # без окон: рисунки здесь не нужны\n\n" + body + "\n" + MAIN
compile(code, str(DST), "exec")
DST.write_text(code, encoding="utf-8")
print("written", DST, len(code.splitlines()), "lines")
