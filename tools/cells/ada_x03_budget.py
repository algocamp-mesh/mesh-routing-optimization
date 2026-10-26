# EXP 11.3: порог бюджета эфира
V_DC = {"hybrid": {}}
V_DC.update({f"В, порог {p:g}": dict(dc_aware_rreq=p, dc_aware_min_dups=0) for p in (0.4, 0.5, 0.6, 0.7, 0.8, 0.9)})
SPECS_DC = variants(V_DC, range(1, 13), base="hybrid", topo=list(MOBILITY), pattern=["random"], rate=LOAD_RATES)
df_dc = run_grid("11_3_budget", SPECS_DC)
df_dc["порог"] = df_dc.method.str.extract(r"порог ([\d.]+)")[0].astype(float).fillna(1.0)   # hybrid = без порога

fig, axes = plt.subplots(1, 2, figsize=(11, 3.6))
for rate in LOAD_RATES:
    s = df_dc[df_dc.rate == rate].groupby("порог")
    axes[0].plot(s.pdr_20s.mean().index, s.pdr_20s.mean().values, "o-", label=f"{rate} пак/с")
    axes[1].plot(s.airtime_per_delivered_s.mean().index, s.airtime_per_delivered_s.mean().values, "o-", label=f"{rate} пак/с")
for ax, yl in zip(axes, ["доставлено за 20 с", "эфир на доставленный пакет, с"]):
    ax.set_xlabel("порог: доля лимита эфира узла (1,0 — механизм выключен)"); ax.set_ylabel(yl); ax.grid(alpha=.3)
axes[0].axhline(1 - LOSS_MAX, color="#e03131", ls="--", lw=1); axes[0].legend(fontsize=8)
plt.tight_layout(); plt.show()
t = df_dc.pivot_table(index="method", columns="rate", values="pdr_20s", aggfunc="mean", sort=False)
t.columns = [f"{c} пак/с" for c in t.columns]
t.round(3)
