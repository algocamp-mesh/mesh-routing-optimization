"""Выполняет все код-ячейки блокнота, а run_grid подменяет на параллельный (16 процессов).
Результаты кладутся в папку RESULTS_DIR блокнота (results/…) — те же, что получил бы блокнот при RERUN = True."""
import json, sys, os, time
from concurrent.futures import ProcessPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NB = os.path.join(ROOT, sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "1_simple_aodv.ipynb")
FORCE = "--force" in sys.argv
HELPERS = "# EXP: общие функции"


def setup_mpl():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.show = lambda *a, **k: plt.close("all")


def load_cells():
    nb = json.load(open(NB, encoding="utf-8"))
    return ["\n".join(l for l in "".join(c["source"]).splitlines() if not l.startswith("%"))
            for c in nb["cells"] if c["cell_type"] == "code"]


W = None


def _init():
    global W
    os.chdir(ROOT)
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
    setup_mpl()
    W = {"display": lambda *a, **k: None, "__name__": "__nb__"}
    for s in load_cells():
        exec(compile(s, "<cell>", "exec"), W)
        if s.startswith(HELPERS):
            break


def _run(spec):
    return W["run_spec"](spec)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    os.chdir(ROOT)
    setup_mpl()
    G = {"display": print, "__name__": "__nb__"}
    ex = ProcessPoolExecutor(os.cpu_count(), initializer=_init)
    for s in load_cells():
        t0 = time.time()
        exec(compile(s, "<cell>", "exec"), G)
        print(f"--- ячейка «{s.splitlines()[0][:60]}» {time.time() - t0:.1f} с", flush=True)
        if s.startswith(HELPERS):
            pd = G["pd"]

            def run_grid(name, specs):
                path = os.path.join(G.get("RESULTS_DIR", "results"), name + ".csv")
                if os.path.exists(path) and not FORCE:
                    return pd.read_csv(path)
                t1 = time.time()
                df = pd.DataFrame(list(ex.map(_run, specs, chunksize=1)))
                df = df.fillna({c: 0 for c in df.columns if c.startswith("fail_")})
                os.makedirs(os.path.dirname(path), exist_ok=True)
                df.to_csv(path, index=False)
                df = pd.read_csv(path)                 # как в блокноте: дальше работаем с прочитанным CSV
                print(f"[{name}] {len(specs)} прогонов за {time.time() - t1:.0f} с", flush=True)
                return df

            G["run_grid"] = run_grid
    ex.shutdown()
