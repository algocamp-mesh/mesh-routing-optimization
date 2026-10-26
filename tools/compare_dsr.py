"""DSR из ветки DSR (симулятор коллеги как есть) на сценариях исследования 4 (results/4_reliable_rreq/11_4_final.csv).
Единственная правка — случайные пары выбираются заранее, как у нас, чтобы трафик совпадал при одном seed.
Проверка: затопление и Дейкстра в обоих симуляторах дают одинаковые результаты на всех прогонах.
Запуск: git fetch origin && python tools/compare_dsr.py   -> results/compare_dsr/dsr_on_our_scenarios.csv"""
import sys, os, json, time, subprocess
import pandas as pd
from concurrent.futures import ProcessPoolExecutor
sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DSR_REF = "bfca624"                       # коммит ветки DSR, на котором сделано сравнение
G = None


def _init():
    global G
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.show = lambda *a, **k: plt.close("all")
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
    nb = json.loads(subprocess.run(["git", "show", f"{DSR_REF}:mesh_routing_simulation.ipynb"], cwd=ROOT,
                                   capture_output=True, check=True).stdout.decode("utf-8"))
    G = {"display": lambda *a, **k: None, "__name__": "__dsr__"}
    for i, c in enumerate(nb["cells"][:26]):
        if c["cell_type"] == "code":
            src = "\n".join(l for l in "".join(c["source"]).splitlines() if not l.startswith("%"))
            exec(compile(src, f"<dsr cell {i}>", "exec"), G)
    exec('''
_RWP20 = {"walk": ((0.5, 1.5), (0, 60)), "vehicle": ((8, 15), (0, 10)), "drone": ((15, 25), (0, 5))}
for _k, (_v, _p) in _RWP20.items():
    TOPOLOGIES[f"rwp20_{_k}"] = (
        lambda rng, sim_time=600.0, n=20, area=2000.0, _v=_v, _p=_p, _name=f"rwp20_{_k}":
            topo_rwp(rng, n=n, area=area, v_range=_v, pause_range=_p, sim_time=sim_time, name=_name), None)

def _schedule_traffic(self):
    tr = self.sc.traffic
    flows = TOPOLOGIES[self.sc.topology][1] if tr.flows == "default" else tr.flows
    t_stop = self.sc.sim_time_s - tr.stop_margin_s
    streams = [(s, d) for s, d in flows] if flows else [(None, None)]
    for s, d in streams:
        t = tr.start_s + self.rng.expovariate(tr.rate_pps)
        while t < t_stop:
            self.at(t, self.generate, *((s, d) if s is not None else self.rng.sample(self.topo.nodes, 2)))
            t += self.rng.expovariate(tr.rate_pps)
Simulator._schedule_traffic = _schedule_traffic
''', G)


def run(spec):
    g = G
    nodes = 20
    if spec["pattern"] == "random":
        tr = g["TrafficConfig"](flows=None, rate_pps=spec["rate"])
    elif spec["pattern"] == "sink":
        tr = g["TrafficConfig"](flows=[(i, 0) for i in range(1, nodes)], rate_pps=spec["rate"] / (nodes - 1))
    else:
        tr = g["TrafficConfig"](flows="default", rate_pps=spec["rate"])
    ch = g["ChurnConfig"](random_nodes="all", mtbf_s=300, mttr_s=30) if spec["churn"] else g["ChurnConfig"]()
    sc = g["Scenario"](spec["topo"], spec["topo"], traffic=tr, churn=ch)
    sim = g["Simulator"](sc, spec["method"], spec["seed"])
    res = sim.run()
    pk = sim.packets_df()
    ok = (pk.outcome == "delivered") & (pk.latency_s <= 20.0)
    out = dict(spec, generated=len(pk), pdr=res["pdr"], pdr_20s=ok.sum() / len(pk) if len(pk) else float("nan"),
               latency_mean_s=res["latency_mean_s"], latency_p95_s=res.get("latency_p95_s"),
               airtime_per_delivered_s=res["airtime_per_delivered_s"])
    return out


if __name__ == "__main__":
    STATIC = ["line10", "ring12", "tree15", "grid4x4", "board6", "mesh30"]
    MOB = ["rwp20_walk", "rwp20_vehicle", "rwp20_drone"]
    cases = [dict(topo=t, pattern="default", rate=0.2, churn=False) for t in STATIC]
    cases += [dict(topo=t, pattern=p, rate=0.2, churn=False) for t in MOB for p in ("random", "sink")]
    cases += [dict(topo=t, pattern="random", rate=0.2, churn=True) for t in MOB]
    cases += [dict(topo=t, pattern="random", rate=0.5, churn=False) for t in MOB]
    specs = [dict(c, method=m, seed=s) for c in cases for m in ("dsr", "flooding", "dijkstra") for s in range(1, 11)]
    t0 = time.time()
    with ProcessPoolExecutor(os.cpu_count(), initializer=_init) as ex:
        df = pd.DataFrame(list(ex.map(run, specs, chunksize=1)))
    print("wall", round(time.time() - t0), "runs", len(df))
    out = os.path.join(ROOT, "results", "compare_dsr")
    os.makedirs(out, exist_ok=True)
    df.to_csv(os.path.join(out, "dsr_on_our_scenarios.csv"), index=False)
