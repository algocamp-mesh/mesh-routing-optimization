# EXP 10.9: ресурсы узла — ОЗУ, ПЗУ, эфир, микроконтроллер
aodv_main = df_main[df_main.method.str.startswith("aodv")]
res_t = aodv_main.groupby("method").agg(
    ram_bytes=("ram_bytes", "max"), peak_routes=("peak_routes", "max"), peak_pending=("peak_pending", "max"),
    peak_queue=("peak_queue", "max"), peak_rreq_cache=("peak_rreq_cache", "max"),
    flash_writes_5y=("flash_writes_5y", "max"), flash_naive_5y=("flash_naive_5y", "max"),
    max_node_duty=("max_node_duty", "max"), mcu_util_max=("mcu_util_max", "max"))
res_t["ОЗУ, % от 200 кБ"] = 100 * res_t.ram_bytes / RAM_MAX_B
res_t = res_t.rename(columns={
    "ram_bytes": "ОЗУ под маршрутизацию, байт", "peak_routes": "макс. записей в таблице маршрутов",
    "peak_pending": "макс. пакетов в буфере ожидания", "peak_queue": "макс. длина очереди передачи",
    "peak_rreq_cache": "макс. записей в кэше RREQ",
    "flash_writes_5y": "перезаписей ПЗУ за 5 лет (номер блоками по 1024)",
    "flash_naive_5y": "… если писать номер при каждом изменении",
    "max_node_duty": "макс. доля эфира узла", "mcu_util_max": "макс. загрузка MCU"})
display(res_t.round(3).T)

# Задержка: распределение по пакетам (техника, случайные пары)
fig, ax = plt.subplots(figsize=(7, 3.4))
for m in MAIN_METHODS:
    lat = []
    for seed in range(1, 4):
        _, sim = simulate(make_scenario("rwp20_vehicle"), m, seed)
        lat += sim.packets_df().latency_s.dropna().tolist()
    lat = sorted(lat)
    ax.plot(lat, [i / len(lat) for i in range(1, len(lat) + 1)], label=m, color=METHOD_COLORS[m])
ax.axvline(DEADLINE_S, color="#e03131", ls="--", lw=1)
ax.set_xscale("log"); ax.set_xlabel("задержка доставки, с"); ax.set_ylabel("доля доставленных пакетов")
ax.set_title("Распределение задержки доставленных пакетов (техника, 3 прогона)", fontsize=10)
ax.grid(alpha=.3); ax.legend(fontsize=8)
plt.tight_layout(); plt.show()
