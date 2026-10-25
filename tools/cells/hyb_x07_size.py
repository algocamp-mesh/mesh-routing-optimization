# EXP 11.7: размер и плотность сети (техника)
SPECS_HSIZE = []
for n in (10, 15, 20):
    SPECS_HSIZE += grid(HYB_METHODS, range(1, 6), topo=["rwp20_vehicle"], n=[n], area=[round(2000 * (n / 20) ** 0.5)],
                        pattern=["random"], rate=[0.2])
for area in (1500, 2500):
    SPECS_HSIZE += grid(HYB_METHODS, range(1, 6), topo=["rwp20_vehicle"], n=[20], area=[area], pattern=["random"], rate=[0.2])
df_hsize = run_grid("11_7_size", SPECS_HSIZE)
df_hsize["конфигурация"] = df_hsize.apply(lambda r: f"{int(r.n)} узлов, {int(r.area)} × {int(r.area)} м", axis=1)
criteria_table(df_hsize, by=("конфигурация", "method"))
