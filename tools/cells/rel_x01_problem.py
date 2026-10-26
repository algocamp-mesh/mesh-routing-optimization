# EXP 11.1: неподвижные топологии
STATIC = ["line10", "ring12", "tree15", "grid4x4", "board6", "mesh30"]
SPECS_STATIC = grid(("flooding", "dijkstra", "aodv_lora", "hybrid_dc"), range(1, 11), topo=STATIC, pattern=["default"], rate=[0.2])
df_static = run_grid("11_1_static", SPECS_STATIC)
t = df_static.pivot_table(index="topo", columns="method", values="pdr_20s", aggfunc="mean").reindex(STATIC)
print("Доставлено за 20 с:")
t[["flooding", "dijkstra", "aodv_lora", "hybrid_dc"]].round(3)
