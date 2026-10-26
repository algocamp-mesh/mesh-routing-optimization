# EXP 11.2: механизмы А и Б
V_AB = {
    "hybrid": {},
    "А, порог 0,2": dict(load_adaptive=True, busy_threshold=0.2),
    "А, порог 0,3": dict(load_adaptive=True, busy_threshold=0.3),
    "А, порог 0,4": dict(load_adaptive=True, busy_threshold=0.4),
    "А + Б (2 копии), порог 0,3": dict(load_adaptive=True, busy_threshold=0.3, load_supp_dups=2),
    "Б (2 копии), порог 0,3": dict(load_adaptive=True, busy_threshold=0.3, load_no_piggyback=False, load_supp_dups=2),
    "Б (1 копия), порог 0,2": dict(load_adaptive=True, busy_threshold=0.2, load_no_piggyback=False, load_supp_dups=1),
}
LOAD_RATES = [0.2, 0.3, 0.5, 0.7]
SPECS_AB = variants(V_AB, range(1, 9), base="hybrid", topo=list(MOBILITY), pattern=["random"], rate=LOAD_RATES)
df_ab = run_grid("11_2_options", SPECS_AB)
t = df_ab.pivot_table(index="method", columns="rate", values="pdr_20s", aggfunc="mean", sort=False)
t.columns = [f"{c} пак/с" for c in t.columns]
t["эфир на пакет при 0,5, с"] = df_ab[df_ab.rate == 0.5].groupby("method", sort=False).airtime_per_delivered_s.mean()
print("Доставлено за 20 с (среднее по трём видам движения):")
t.round(3)
