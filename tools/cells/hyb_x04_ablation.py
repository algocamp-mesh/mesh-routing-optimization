# EXP 11.4: вклад механизмов гибрида (парное сравнение)
V_HABL = {
    "hybrid": {},
    "− пакет в RREQ": dict(piggyback=False),
    "− храни и неси": dict(carry=False),
    "− оба (= aodv_lora, 1 повтор)": dict(piggyback=False, carry=False),
    "2 повтора поиска": dict(rreq_retries=2),
    "быстрый режим": dict(ring_from_known_hops=True),
}
SPECS_HABL = variants(V_HABL, range(1, 11), base="hybrid", topo=list(MOBILITY), pattern=["random", "sink"], rate=[0.2])
df_habl = run_grid("11_4_ablation", SPECS_HABL)

_key = ["topo", "pattern", "seed"]
ref = df_habl[df_habl.method == "hybrid"].set_index(_key)
rows = []
for v in V_HABL:
    if v == "hybrid":
        continue
    x = df_habl[df_habl.method == v].set_index(_key)
    d = (x.pdr_20s - ref.pdr_20s).dropna()
    rows.append({"вариант": v, "Δ доставлено за 20 с": d.mean(), "± 95 %": 1.96 * d.std() / len(d) ** 0.5,
                 "эфир на пакет, с": x.airtime_per_delivered_s.mean(), "задержка ср., с": x.latency_mean_s.mean()})
t_habl = pd.DataFrame(rows).set_index("вариант")
print(f"hybrid: доставлено за 20 с {ref.pdr_20s.mean():.3f}, эфир {ref.airtime_per_delivered_s.mean():.2f} с, "
      f"задержка {ref.latency_mean_s.mean():.2f} с")
display(t_habl.round(3))

fig, ax = plt.subplots(figsize=(7, 3))
tt = t_habl.sort_values("Δ доставлено за 20 с")
ax.barh(tt.index, tt["Δ доставлено за 20 с"], xerr=tt["± 95 %"], capsize=3,
        color=["#adb5bd" if abs(m) <= c else ("#2f9e44" if m > 0 else "#e03131")
               for m, c in zip(tt["Δ доставлено за 20 с"], tt["± 95 %"])])
ax.axvline(0, color="#333", lw=.8); ax.grid(axis="x", alpha=.3)
ax.set_xlabel("Δ доли доставленных за 20 с относительно hybrid (серое — незначимо)")
plt.tight_layout(); plt.show()
