# EXP 10.6: нагрузка — до какого трафика методы держат требования
RATES = [0.05, 0.1, 0.2, 0.3, 0.5]
SPECS_LOAD = grid(MAIN_METHODS, range(1, 6), topo=list(MOBILITY), pattern=["random"], rate=RATES)
df_load = run_grid("10_6_load", SPECS_LOAD)
plot_lines(df_load, "rate", "pdr_20s", target=1 - LOSS_MAX, xlabel="суммарный трафик, пакетов/с",
           ylabel="доставлено за 20 с", title="Доставка против нагрузки (20 узлов, случайные пары)")
plot_lines(df_load, "rate", "airtime_per_delivered_s", xlabel="суммарный трафик, пакетов/с",
           ylabel="эфир на доставленный пакет, с", title="Расход эфира")

_m = df_load.groupby(["method", "topo", "rate"]).pdr_20s.mean().reset_index()
cap = (_m[_m.pdr_20s >= 1 - LOSS_MAX].groupby(["method", "topo"]).rate.max().unstack()
       .reindex(index=list(MAIN_METHODS), columns=list(MOBILITY)).rename(columns=MOBILITY))
print("Наибольшая нагрузка из проверенных (пакетов/с на всю сеть), при которой потери за 20 с ≤ 10 % (NaN — ни при какой):")
cap
