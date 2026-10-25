# EXP 10.7: сколько должен жить маршрут при разной скорости узлов
ARTS = [3, 5, 10, 20, 40]
V_ART = {f"ART {a} с": dict(active_route_timeout_s=float(a)) for a in ARTS}
SPECS_ART = variants(V_ART, range(1, 6), base="aodv_lora", topo=list(MOBILITY), pattern=["random", "sink"], rate=[0.2, 0.5])
df_art = run_grid("10_7_art", SPECS_ART)
df_art["ART"] = df_art.method.str.extract(r"(\d+)")[0].astype(float)
for pat in ("random", "sink"):
    sub = df_art[df_art.pattern == pat].assign(method=lambda d: d.rate.map(lambda r: f"{r} пакета/с"))
    plot_lines(sub, "ART", "pdr_20s", target=1 - LOSS_MAX, xlabel="ACTIVE_ROUTE_TIMEOUT, с", ylabel="доставлено за 20 с",
               title=f"Время жизни маршрута: {'случайные пары' if pat == 'random' else 'все → координатор'}", logx=True)
best = df_art.groupby(["pattern", "rate", "topo", "ART"]).pdr_20s.mean().reset_index()
best = best.loc[best.groupby(["pattern", "rate", "topo"]).pdr_20s.idxmax()]
print("Лучшее время жизни маршрута, с:")
best.assign(topo=best.topo.map(MOBILITY)).pivot_table(index=["pattern", "rate"], columns="topo", values="ART")[list(MOBILITY.values())]
