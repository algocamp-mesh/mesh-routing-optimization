# EXP 11.1: гибрид на неподвижных графах
def path_from_tables(sim, src, dst, max_hops=15):
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
    sc = Scenario(name, name.split(",")[0], traffic=TrafficConfig(flows=[(s, d)]), churn=churn)
    ref_path, _ = dijkstra(Simulator(sc, "dijkstra", 1).snapshot_graph(), s, d)
    for m in ("dijkstra", "aodv_lora", "hybrid"):
        res, sim = simulate(sc, m, 1)
        rows.append({"сценарий": name, "метод": m,
                     "путь Дейкстры": "→".join(map(str, ref_path)) if ref_path else "—",
                     "путь по таблицам": "→".join(map(str, path_from_tables(sim, s, d))) if m != "dijkstra" else "",
                     "доставлено за 20 с": round(res["pdr_20s"], 3),
                     "из них внутри RREQ": int(res.get("delivered_in_rreq", 0) or 0),
                     "задержка, с": round(res["latency_mean_s"], 2),
                     "причины потерь": ", ".join(f"{k[5:]}: {int(v)}" for k, v in res.items() if k.startswith("fail_") and v)})
pd.DataFrame(rows)
