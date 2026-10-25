# EXP 11.3: где гибрид выигрывает — пакеты с путём и без пути в момент отправки
rows = []
for topo in MOBILITY:
    for churn in (False, True):
        for m in ("flooding_x3", "dijkstra", "aodv_lora", "hybrid"):
            pk_all, in_rreq, gen = [], 0, 0
            for seed in range(1, 6):
                res, sim = simulate(make_scenario(topo, churn=churn), m, seed)
                pk = sim.packets_df()
                pk_all.append(pk)
                in_rreq += res.get("delivered_in_rreq", 0) or 0
            pk = pd.concat(pk_all)
            ok = (pk.outcome == "delivered") & (pk.latency_s <= DEADLINE_S)
            reach = pk.reachable.astype(bool)
            rows.append({"движение": MOBILITY[topo], "узлы пропадают": "да" if churn else "нет", "метод": m,
                         "путь был: доставлено": ok[reach].mean(),
                         "пути не было: доставлено": ok[~reach].mean(),
                         "пакетов без пути, %": 100 * (~reach).mean(),
                         "доставлено внутри RREQ, % от доставленных": 100 * in_rreq / max(ok.sum(), 1) if m == "hybrid" else float("nan")})
t_why = pd.DataFrame(rows).round(3)
t_why
