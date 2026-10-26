# EXP 11.1: диагностика под нагрузкой
rows = []
for rate in (0.2, 0.5):
    for m in ("hybrid", "flooding_x3"):
        air, stats, res_l = Counter(), Counter(), []
        for seed in (1, 2, 3):
            res, sim = simulate(make_scenario("rwp20_vehicle", rate=rate), m, seed)
            air.update(sim.air); stats.update(sim.stats); res_l.append(res)
        T, gen = sum(air.values()), sum(r["generated"] for r in res_l)
        fails = Counter()
        for r in res_l:
            fails.update({k[5:]: v for k, v in r.items() if k.startswith("fail_") and v})
        rows.append({"нагрузка, пак/с": rate, "метод": m,
                     "доставлено за 20 с": sum(r["pdr_20s"] for r in res_l) / 3,
                     "эфир всей сети, доля времени": T / (3 * 600),
                     "из него RREQ, %": 100 * air["RREQ"] / T,
                     "макс. доля эфира узла": max(r["max_node_duty"] for r in res_l),
                     "откладываний из-за лимита эфира": stats["duty_cycle_deferrals"],
                     "передач RREQ на пакет": stats["tx_RREQ"] / gen,
                     "главная причина потерь": fails.most_common(1)[0][0] if fails else "—",
                     "потерь по сроку 20 с, %": 100 * fails["deadline"] / gen})
pd.DataFrame(rows).round(3)
