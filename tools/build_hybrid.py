"""Собирает 2_hybrid_aodv.ipynb: общая часть (разделы 0–9 и AODV) из 1_simple_aodv.ipynb
+ гибрид и его эксперименты из tools/cells/hyb_*. Сначала нужно собрать AODV: python tools/build_aodv.py"""
import json, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
CELLS = pathlib.Path(__file__).resolve().parent / "cells"
SRC = ROOT / "1_simple_aodv.ipynb"
DST = ROOT / "2_hybrid_aodv.ipynb"
HELPERS = "# EXP: общие функции"


def md(text):
    return {"cell_type": "markdown", "metadata": {}, "source": text.strip("\n").splitlines(keepends=True)}


def code(text):
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
            "source": text.strip("\n").splitlines(keepends=True)}


def cell(name):
    text = (CELLS / name).read_text(encoding="utf-8")
    return md(text) if name.endswith(".md") else code(text)


nb = json.loads(SRC.read_text(encoding="utf-8"))
src = nb["cells"]
out = [cell("hyb_intro.md")]
for i, c in enumerate(src):
    s = "".join(c["source"])
    if i < 2 and c["cell_type"] == "markdown":           # введение и постановка AODV заменяются своими
        continue
    if c["cell_type"] == "markdown" and s.startswith("## 10. Эксперименты"):
        out += [cell("hyb_idea.md"), cell("hyb_sim.py"), cell("hyb_exp_intro.md")]
        continue
    out.append(c)
    if c["cell_type"] == "code" and s.startswith(HELPERS):
        out.append(code('RESULTS_DIR = os.path.join("results", "2_hybrid_aodv")   # результаты исследования 2 отдельно от исследования 1'))
        break
out += [cell(p.name) for p in sorted(CELLS.glob("hyb_x*"))]

for c in out:
    if c["cell_type"] == "code":
        c["outputs"], c["execution_count"] = [], None
nb["cells"] = out
DST.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
print("written", DST, len(out), "cells")
