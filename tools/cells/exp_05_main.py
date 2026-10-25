# EXP 10.5: главный результат — 20 подвижных узлов, лёгкая нагрузка
SPECS_MAIN = grid(MAIN_METHODS, range(1, 21), topo=list(MOBILITY), pattern=["random", "sink"],
                  rate=[0.2], churn=[False, True])
df_main = run_grid("10_5_main", SPECS_MAIN)

CASES = [("random", False, "Случайные пары, узлы не пропадают"),
         ("sink", False, "Все шлют координатору (узел 0), узлы не пропадают"),
         ("random", True, "Случайные пары, каждый узел в среднем 300 с работает и 30 с отсутствует")]
for pat, churn, title in CASES:
    sub = df_main[(df_main.pattern == pat) & (df_main.churn == churn)]
    print(title)
    display(criteria_table(sub.assign(topo=sub.topo.map(MOBILITY))))

fig, axes = plt.subplots(1, 3, figsize=(15, 3.6), sharey=True)
for ax, (pat, churn, title) in zip(axes, CASES):
    sub = df_main[(df_main.pattern == pat) & (df_main.churn == churn)]
    xs = list(MOBILITY)
    w = 0.8 / len(MAIN_METHODS)
    for i, m in enumerate(MAIN_METHODS):
        s = sub[sub.method == m].groupby("topo").pdr_20s
        ax.bar([j + (i - 1.5) * w for j in range(len(xs))], s.mean().reindex(xs), w, yerr=s.std().reindex(xs),
               capsize=2, label=m, color=METHOD_COLORS[m])
    reach = sub.groupby("topo").reachable_share.mean().reindex(xs)
    ax.scatter(range(len(xs)), reach, marker="_", s=900, color="#333", zorder=5, label="путь существует")
    ax.axhline(1 - LOSS_MAX, color="#e03131", ls="--", lw=1)
    ax.set_xticks(range(len(xs))); ax.set_xticklabels([MOBILITY[x] for x in xs]); ax.set_ylim(0.5, 1.0)
    ax.set_title(title, fontsize=9); ax.grid(axis="y", alpha=.3)
axes[0].set_ylabel("доставлено за 20 с (среднее ± ст. откл.)")
h, l = axes[0].get_legend_handles_labels()
fig.legend(h, l, loc="lower center", ncol=5, fontsize=9)
plt.tight_layout(rect=(0, 0.08, 1, 1)); plt.show()
