# EXP 11.4: hybrid_ovh — нагрузка и все сценарии
STATIC = ["line10", "ring12", "tree15", "grid4x4", "board6", "mesh30"]
ALL5 = ("flooding", "flooding_x3", "aodv_rfc", "aodv_lora", "hybrid", "hybrid_dc", "hybrid_plus", "hybrid_ovh", "dijkstra")
SPECS_F5 = grid(ALL5, range(1, 11), topo=STATIC, pattern=["default"], rate=[0.2], churn=[False])
SPECS_F5 += grid(ALL5, range(1, 11), topo=list(MOBILITY), pattern=["random", "sink"], rate=[0.2], churn=[False])
SPECS_F5 += grid(ALL5, range(1, 11), topo=list(MOBILITY), pattern=["random"], rate=[0.2], churn=[True])
SPECS_F5 += grid(ALL5, range(1, 11), topo=list(MOBILITY), pattern=["random"], rate=[0.5], churn=[False])
df_f5 = run_grid("11_4_final", SPECS_F5)

LOAD5 = ("flooding_x3", "dijkstra", "hybrid_plus", "hybrid_ovh")
SPECS_L5 = grid(LOAD5, range(1, 11), topo=list(MOBILITY), pattern=["random"], rate=[0.1, 0.2, 0.3, 0.4, 0.5, 0.7], churn=[False])
SPECS_L5 += grid(LOAD5, range(1, 11), topo=list(MOBILITY), pattern=["sink"], rate=[0.2, 0.5], churn=[False])
df_l5 = run_grid("11_4_load", SPECS_L5)
plot_lines(df_l5[df_l5.pattern == "random"], "rate", "pdr_20s", target=1 - LOSS_MAX, xlabel="суммарный трафик, пакетов/с",
           ylabel="доставлено за 20 с", title="Случайные пары: доставка против нагрузки")
plot_lines(df_l5[df_l5.pattern == "random"], "rate", "airtime_per_delivered_s", xlabel="суммарный трафик, пакетов/с",
           ylabel="эфир на доставленный пакет, с", title="Случайные пары: расход эфира")

k = ["topo", "pattern", "rate", "seed"]
a = df_l5[df_l5.method == "hybrid_ovh"].set_index(k)
b = df_l5[df_l5.method == "hybrid_plus"].set_index(k)
d = pd.DataFrame({"Δ": a.pdr_20s - b.pdr_20s, "air": a.airtime_per_delivered_s / b.airtime_per_delivered_s}).dropna()
g = d.groupby(level=["pattern", "rate"])
print("hybrid_ovh − hybrid_plus (среднее по трём видам движения, 95 % интервал):")
pd.DataFrame({"Δ доставлено за 20 с": g["Δ"].mean(), "± 95 %": 1.96 * g["Δ"].std() / g["Δ"].count() ** 0.5,
              "эфир, × к hybrid_plus": g.air.mean()}).round(3)
