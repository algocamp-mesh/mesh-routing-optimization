# EXP 10.4: вклад каждой доработки (парное сравнение на одинаковых сценариях)
FEATURES = {                                   # входят в aodv_lora
    "локальная починка": dict(local_repair=True),
    "повторы с паузой": dict(retry_backoff_s=0.2, extra_retries_if_heard=3),
    "маршрут 10 с": dict(active_route_timeout_s=10.0),
    "срок 20 с": dict(deadline_s=20.0),
}
TRIED = {                                      # проверены и не вошли
    "метрика ETX": dict(metric="etx", etx_delay_s=0.3),
    "разброс RREQ 0–0,5 с": dict(rreq_jitter_s=(0.0, 0.5)),
    "подавление RREQ (2 копии)": dict(rreq_suppress_dups=2),
    "задержка RREP 0,6 с": dict(rrep_delay_s=0.6),
    "разнесение пачки 0,5 с": dict(flush_gap_s=0.5),
    "без расширяющегося кольца": dict(expanding_ring=False, rreq_backoff=False, node_traversal_s=0.3),
    "HELLO раз в 1 с": dict(hello_interval_s=1.0),
}
_rfc_defaults = AodvConfig()
V_ABL = {"aodv_rfc": ({}, "aodv_rfc"), "aodv_lora": ({}, "aodv_lora")}
V_ABL.update({f"RFC + {k}": (d, "aodv_rfc") for k, d in FEATURES.items()})
V_ABL.update({f"LoRa − {k}": ({p: getattr(_rfc_defaults, p) for p in d}, "aodv_lora") for k, d in FEATURES.items()})
V_ABL.update({f"LoRa + {k}": (d, "aodv_lora") for k, d in TRIED.items()})
SPECS_ABL = []
for name, (d, base) in V_ABL.items():
    SPECS_ABL += variants({name: d}, range(1, 11), base=base, topo=list(MOBILITY), pattern=["random", "sink"], rate=[0.2])
df_abl = run_grid("10_4_ablation", SPECS_ABL)

t = df_abl.pivot_table(index="method", columns="topo", values="pdr_20s", aggfunc="mean", sort=False)
t = t[list(MOBILITY)].rename(columns=MOBILITY)
t["среднее"] = t.mean(axis=1)
t["эфир на пакет, с"] = df_abl.groupby("method", sort=False).airtime_per_delivered_s.mean()
display(t.round(3))

# Разница с эталонным вариантом на тех же (топология, трафик, seed): среднее ± 95 % доверительный интервал
_key = ["topo", "pattern", "seed"]
def paired_delta(variant, ref):
    a = df_abl[df_abl.method == variant].set_index(_key).pdr_20s
    b = df_abl[df_abl.method == ref].set_index(_key).pdr_20s
    d = (a - b).dropna()
    return d.mean(), 1.96 * d.std() / len(d) ** 0.5

fig, axes = plt.subplots(1, 3, figsize=(15, 3.6))
for ax, prefix, ref, title in [(axes[0], "RFC + ", "aodv_rfc", "Добавить к RFC одну доработку"),
                               (axes[1], "LoRa − ", "aodv_lora", "Убрать из aodv_lora одну доработку"),
                               (axes[2], "LoRa + ", "aodv_lora", "Проверенные и отвергнутые идеи")]:
    names = [i for i in t.index if i.startswith(prefix)]
    dd = sorted(((paired_delta(n, ref), n[len(prefix):]) for n in names))
    means, cis, labels = [x[0][0] for x in dd], [x[0][1] for x in dd], [x[1] for x in dd]
    colors = ["#adb5bd" if abs(m) <= c else ("#2f9e44" if m > 0 else "#e03131") for m, c in zip(means, cis)]
    ax.barh(labels, means, xerr=cis, capsize=3, color=colors)
    ax.axvline(0, color="#333", lw=.8)
    ax.set_title(title, fontsize=10); ax.set_xlabel("Δ доли доставленных за 20 с (серое — незначимо)")
    ax.grid(axis="x", alpha=.3)
plt.tight_layout(); plt.show()
