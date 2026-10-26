"""Собирает блокноты исследований 2–4. Общая часть (разделы 0–9 и AODV) берётся из 1_simple_aodv.ipynb,
своё — из tools/cells. Сначала нужно собрать исследование 1: python tools/build_aodv.py
Запуск: python tools/build_studies.py [имя ...]   (без имён — все)"""
import json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
CELLS = pathlib.Path(__file__).resolve().parent / "cells"
SRC = ROOT / "1_simple_aodv.ipynb"
HELPERS = "# EXP: общие функции"

STUDIES = {
    "2_hybrid_aodv": dict(intro="hyb_intro.md", insert=["hyb_idea.md", "hyb_sim.py", "hyb_exp_intro.md"], exps="hyb_x*"),
    "3_adaptive_hybrid": dict(intro="ada_intro.md", insert=["base_hybrid.md", "hyb_sim.py", "ada_idea.md", "ada_sim.py",
                                                            "ada_exp_intro.md"], exps="ada_x*"),
    "4_reliable_rreq": dict(intro="rel_intro.md", insert=["base_hybrid.md", "hyb_sim.py", "ada_sim.py", "rel_idea.md",
                                                          "rel_sim.py", "rel_exp_intro.md"], exps="rel_x*"),
    "5_dsr_ideas": dict(intro="dsr_intro.md", insert=["base_plus.md", "hyb_sim.py", "ada_sim.py", "rel_sim.py",
                                                      "dsr_idea.md", "dsr_sim.py", "dsr_exp_intro.md"], exps="dsr_x*"),
}


def md(text):
    return {"cell_type": "markdown", "metadata": {}, "source": text.strip("\n").splitlines(keepends=True)}


def code(text):
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
            "source": text.strip("\n").splitlines(keepends=True)}


def cell(name):
    text = (CELLS / name).read_text(encoding="utf-8")
    return md(text) if name.endswith(".md") else code(text)


def build(name, spec):
    nb = json.loads(SRC.read_text(encoding="utf-8"))
    out = [cell(spec["intro"])]
    for i, c in enumerate(nb["cells"]):
        s = "".join(c["source"])
        if i < 2 and c["cell_type"] == "markdown":       # введение и постановка исследования 1 заменяются своими
            continue
        if c["cell_type"] == "markdown" and s.startswith("## 10. Эксперименты"):
            out += [cell(x) for x in spec["insert"]]
            continue
        out.append(c)
        if c["cell_type"] == "code" and s.startswith(HELPERS):
            out.append(code(f'RESULTS_DIR = os.path.join("results", "{name}")   # результаты этого исследования'))
            break
    out += [cell(p.name) for p in sorted(CELLS.glob(spec["exps"]))]
    for c in out:
        if c["cell_type"] == "code":
            c["outputs"], c["execution_count"] = [], None
    nb["cells"] = out
    dst = ROOT / f"{name}.ipynb"
    dst.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
    print("written", dst, len(out), "cells")


for name in (sys.argv[1:] or STUDIES):
    build(name, STUDIES[name])
