# EXP 11.2: главный результат
HYB_METHODS = ("flooding", "flooding_x3", "dijkstra", "aodv_lora", "hybrid")
CASES = [("random", False, "Случайные пары"), ("sink", False, "Все шлют координатору (узел 0)"),
         ("random", True, "Случайные пары + узлы пропадают (300 с есть, 30 с нет)")]
SPECS_HMAIN = grid(HYB_METHODS, range(1, 21), topo=list(MOBILITY), pattern=["random", "sink"],
                   rate=[0.2], churn=[False, True])
SPECS_HMAIN = [s for s in SPECS_HMAIN if not (s["pattern"] == "sink" and s["churn"])]
df_hmain = run_grid("11_2_main", SPECS_HMAIN)

for pat, churn, title in CASES:
    sub = df_hmain[(df_hmain.pattern == pat) & (df_hmain.churn == churn)]
    print(title)
    display(criteria_table(sub.assign(topo=sub.topo.map(MOBILITY))))

fig, axes = plt.subplots(1, 3, figsize=(16, 3.8), sharey=True)
for ax, (pat, churn, title) in zip(axes, CASES):
    sub = df_hmain[(df_hmain.pattern == pat) & (df_hmain.churn == churn)]
    xs = list(MOBILITY)
    w = 0.85 / len(HYB_METHODS)
    for i, m in enumerate(HYB_METHODS):
        s = sub[sub.method == m].groupby("topo").pdr_20s
        ax.bar([j + (i - (len(HYB_METHODS) - 1) / 2) * w for j in range(len(xs))], s.mean().reindex(xs), w,
               yerr=s.std().reindex(xs), capsize=2, label=m, color=METHOD_COLORS[m])
    reach = sub.groupby("topo").reachable_share.mean().reindex(xs)
    ax.scatter(range(len(xs)), reach, marker="_", s=1100, color="#333", zorder=5, label="путь существует")
    ax.axhline(1 - LOSS_MAX, color="#e03131", ls="--", lw=1)
    ax.set_xticks(range(len(xs))); ax.set_xticklabels([MOBILITY[x] for x in xs]); ax.set_ylim(0.6, 1.0)
    ax.set_title(title, fontsize=9); ax.grid(axis="y", alpha=.3)
axes[0].set_ylabel("доставлено за 20 с (среднее ± ст. откл.)")
h, l = axes[0].get_legend_handles_labels()
fig.legend(h, l, loc="lower center", ncol=6, fontsize=9)
plt.tight_layout(rect=(0, 0.08, 1, 1)); plt.show()
