# EXP 11.4: итоговая проверка и сводка всех исследований
ALL_METHODS = ("flooding", "flooding_x3", "aodv_rfc", "aodv_lora", "hybrid", "hybrid_dc", "hybrid_plus", "dijkstra")
SPECS_FINAL = grid(ALL_METHODS, range(1, 11), topo=STATIC, pattern=["default"], rate=[0.2], churn=[False])
SPECS_FINAL += grid(ALL_METHODS, range(1, 11), topo=list(MOBILITY), pattern=["random", "sink"], rate=[0.2], churn=[False])
SPECS_FINAL += grid(ALL_METHODS, range(1, 11), topo=list(MOBILITY), pattern=["random"], rate=[0.2], churn=[True])
SPECS_FINAL += grid(ALL_METHODS, range(1, 11), topo=list(MOBILITY), pattern=["random"], rate=[0.5], churn=[False])
df_final = run_grid("11_4_final", SPECS_FINAL)


def scenario(r):
    if r.topo not in MOBILITY:
        return "неподвижные: " + r.topo
    if r.churn:
        return "подвижные: узлы пропадают"
    if r.pattern == "sink":
        return "подвижные: все → координатор"
    return f"подвижные: случайные пары, {r.rate:g} пак/с"


df_final["сценарий"] = df_final.apply(scenario, axis=1)
_k = ["topo", "pattern", "rate", "churn", "seed"]
a = df_final[df_final.method == "hybrid_plus"].set_index(_k)
b = df_final[df_final.method == "hybrid_dc"].set_index(_k)
d = pd.DataFrame({"Δ": a.pdr_20s - b.pdr_20s, "air_plus": a.airtime_per_delivered_s, "air_dc": b.airtime_per_delivered_s,
                  "сценарий": a["сценарий"]}).dropna(subset=["Δ"])
g = d.groupby("сценарий", sort=False)
pair = pd.DataFrame({"Δ доставлено за 20 с": g["Δ"].mean(), "± 95 %": 1.96 * g["Δ"].std() / g["Δ"].count() ** 0.5,
                     "эфир hybrid_dc, с": g.air_dc.mean(), "эфир hybrid_plus, с": g.air_plus.mean()})
print("hybrid_plus − hybrid_dc на одинаковых сценариях:")
display(pair.round(3))

mob = df_final[df_final.topo.isin(MOBILITY) & (df_final.pattern == "random") & (df_final.rate == 0.2) & ~df_final.churn]
print("Подвижный кейс, случайные пары, 0,2 пакета/с — проверка требований:")
criteria_table(mob.assign(topo=mob.topo.map(MOBILITY)))
