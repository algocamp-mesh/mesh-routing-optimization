# EXP 11.4: итоговое сравнение по нагрузке
ADA_METHODS = ("flooding_x3", "dijkstra", "aodv_lora", "hybrid", "hybrid_dc")
RATES_MAIN = [0.1, 0.2, 0.3, 0.4, 0.5, 0.7]
SPECS_AMAIN = grid(ADA_METHODS, range(1, 11), topo=list(MOBILITY), pattern=["random"], rate=RATES_MAIN)
df_amain = run_grid("11_4_main", SPECS_AMAIN)
plot_lines(df_amain, "rate", "pdr_20s", target=1 - LOSS_MAX, xlabel="суммарный трафик, пакетов/с",
           ylabel="доставлено за 20 с", title="Доставка против нагрузки")
plot_lines(df_amain, "rate", "airtime_per_delivered_s", xlabel="суммарный трафик, пакетов/с",
           ylabel="эфир на доставленный пакет, с", title="Расход эфира")
for rate in (0.2, 0.5):
    sub = df_amain[df_amain.rate == rate]
    print(f"Нагрузка {rate} пакета/с")
    display(criteria_table(sub.assign(topo=sub.topo.map(MOBILITY))))

# hybrid_dc против hybrid на одинаковых сценариях
_k = ["topo", "rate", "seed"]
a = df_amain[df_amain.method == "hybrid_dc"].set_index(_k).pdr_20s
b = df_amain[df_amain.method == "hybrid"].set_index(_k).pdr_20s
d = (a - b).dropna().groupby(level="rate")
print("Разница hybrid_dc − hybrid по нагрузкам (среднее ± 95 %):")
pd.DataFrame({"Δ доставлено за 20 с": d.mean(), "± 95 %": 1.96 * d.std() / d.count() ** 0.5}).round(3)
