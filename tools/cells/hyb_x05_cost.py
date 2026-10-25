# EXP 11.5: доставка против расхода эфира
agg = df_hmain.groupby(["method", "pattern", "churn", "topo"]).agg(
    pdr=("pdr_20s", "mean"), air=("airtime_per_delivered_s", "mean"), lat=("latency_mean_s", "mean")).reset_index()
fig, axes = plt.subplots(1, 3, figsize=(16, 4), sharey=True)
for ax, (pat, churn, title) in zip(axes, CASES):
    sub = agg[(agg.pattern == pat) & (agg.churn == churn)]
    for m in HYB_METHODS:
        s = sub[sub.method == m]
        ax.plot(s.air, s.pdr, "o--", color=METHOD_COLORS[m], label=m, ms=7, lw=0.8)
    ax.axhline(1 - LOSS_MAX, color="#e03131", ls="--", lw=1)
    ax.set_xscale("log"); ax.set_xlabel("эфир на доставленный пакет, с (лог. шкала)")
    ax.set_title(title, fontsize=9); ax.grid(alpha=.3)
axes[0].set_ylabel("доставлено за 20 с"); axes[0].legend(fontsize=8)
plt.tight_layout(); plt.show()

summary = agg.groupby("method").agg(pdr=("pdr", "mean"), air=("air", "mean"), lat=("lat", "mean")).reindex(HYB_METHODS)
summary.columns = ["доставлено за 20 с (ср. по сценариям)", "эфир на пакет, с", "задержка ср., с"]
summary.round(3)
