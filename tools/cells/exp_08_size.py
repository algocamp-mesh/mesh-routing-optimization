# EXP 10.8: размер и плотность сети (техника, 8–15 м/с)
SPECS_SIZE = []
for n in (10, 15, 20):                       # плотность постоянная: площадь растёт вместе с числом узлов
    SPECS_SIZE += grid(MAIN_METHODS, range(1, 6), topo=["rwp20_vehicle"], n=[n], area=[round(2000 * (n / 20) ** 0.5)],
                       pattern=["random"], rate=[0.2])
for area in (1500, 2500):                    # 20 узлов: гуще и реже
    SPECS_SIZE += grid(MAIN_METHODS, range(1, 6), topo=["rwp20_vehicle"], n=[20], area=[area], pattern=["random"], rate=[0.2])
df_size = run_grid("10_8_size", SPECS_SIZE)
df_size["конфигурация"] = df_size.apply(lambda r: f"{int(r.n)} узлов, {int(r.area)} × {int(r.area)} м", axis=1)
criteria_table(df_size, by=("конфигурация", "method"))
