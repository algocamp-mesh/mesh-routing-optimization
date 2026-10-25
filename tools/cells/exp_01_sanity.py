# EXP 10.1: AODV на неподвижных графах — маршруты совпадают с эталоном?
def path_from_tables(sim, src, dst, max_hops=15):
    """Путь, который получится, если идти по таблицам next-hop узлов AODV."""
    path, n = [src], src
    for _ in range(max_hops):
        rt = sim.aodv[n].routes.get(dst)
        if rt is None:
            break
        n = rt.nxt
        path.append(n)
        if n == dst:
            break
    return path

rows = []
checks = [("board6", 1, 6, ChurnConfig()), ("board6, узел 2 пропал 100–300 с", 1, 6, ChurnConfig(scheduled=[(2, 100, 300)])),
          ("line10", 0, 6, ChurnConfig()), ("line10, поток 0 → 9 (нужно 9 переходов)", 0, 9, ChurnConfig())]
for name, s, d, churn in checks:
    topo = name.split(",")[0]
    sc = Scenario(name, topo, traffic=TrafficConfig(flows=[(s, d)]), churn=churn)
    ref = Simulator(sc, "dijkstra", 1)
    ref_path, _ = dijkstra(ref.snapshot_graph(), s, d)
    for m in ("dijkstra", "aodv_rfc", "aodv_lora"):
        res, sim = simulate(sc, m, 1)
        rows.append({"сценарий": name, "метод": m,
                     "путь Дейкстры": "→".join(map(str, ref_path)) if ref_path else "—",
                     "путь по таблицам AODV (в конце прогона)": "→".join(map(str, path_from_tables(sim, s, d))) if m != "dijkstra" else "",
                     "доставлено": round(res["pdr"], 3), "за 20 с": round(res["pdr_20s"], 3),
                     "задержка, с": round(res["latency_mean_s"], 2),
                     "причины потерь": ", ".join(f"{k[5:]}: {int(v)}" for k, v in res.items() if k.startswith("fail_") and v)})
pd.DataFrame(rows)
