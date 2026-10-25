# EXP 10.2: AODV по RFC «как есть» на нашем кейсе
SPECS_RFC = grid(("flooding", "dijkstra", "aodv_rfc", "aodv_rfc_hello"), range(1, 6),
                 topo=list(MOBILITY), pattern=["random"], rate=[0.2])
df_rfc = run_grid("10_2_rfc", SPECS_RFC)
display(criteria_table(df_rfc.assign(topo=df_rfc.topo.map(MOBILITY))))

# Куда уходит эфир: доли по типам кадров
_ctrl = ["air_share_RREQ", "air_share_RREP", "air_share_RERR", "air_share_HELLO"]
air = df_rfc.groupby("method", sort=False)[_ctrl + ["overhead_share"]].mean().fillna(0)
air["ACK"] = air.overhead_share - air[_ctrl].sum(axis=1)
air["DATA"] = 1 - air.overhead_share
air = air.rename(columns=lambda c: c.replace("air_share_", ""))[["DATA", "ACK", "RREQ", "RREP", "RERR", "HELLO"]]
fig, ax = plt.subplots(figsize=(7, 2.8))
left = pd.Series(0.0, index=air.index)
for c, color in zip(air.columns, ["#1c7ed6", "#74c0fc", "#f59f00", "#ae3ec9", "#e03131", "#f783ac"]):
    ax.barh(air.index, air[c], left=left, color=color, label=c)
    left += air[c]
ax.set_xlabel("доля эфирного времени")
ax.legend(ncol=6, fontsize=8, loc="lower center", bbox_to_anchor=(0.5, 1.0))
ax.invert_yaxis(); plt.tight_layout(); plt.show()
