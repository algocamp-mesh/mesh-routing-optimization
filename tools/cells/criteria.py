# ⚙️ Требования к подвижному случаю (theory/fix, 21.10.2026)
N_NODES_MAX = 20            # до 20 подвижных узлов
LOSS_MAX = 0.10             # потери не больше 10 %
DEADLINE_S = 20.0           # доставка не дольше 20 с
RAM_MAX_B = 200 * 1024      # ОЗУ 200 кБ
ROM_MAX_B = 500 * 1024      # ПЗУ 500 кБ
FLASH_WRITES_MAX = 100_000  # перезаписей ПЗУ за 5 лет непрерывной работы

METHOD_COLORS = {"flooding": "#1c7ed6", "dijkstra": "#e8590c", "dp_hoplimit": "#2f9e44",
                 "aodv_rfc": "#ae3ec9", "aodv_rfc_hello": "#f783ac", "aodv_lora": "#f59f00"}
