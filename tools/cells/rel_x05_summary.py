# EXP 11.5: сводная таблица исследований 1–4
LABELS = {"flooding": "затопление", "flooding_x3": "затопление ×3 (контроль)", "aodv_rfc": "1. AODV по RFC",
          "aodv_lora": "1. aodv_lora", "hybrid": "2. hybrid", "hybrid_dc": "3. hybrid_dc", "hybrid_plus": "4. hybrid_plus",
          "dijkstra": "эталон Дейкстры (оракул)"}
cols = {"подвижные: случайные пары, 0.2 пак/с": "случайные пары", "подвижные: все → координатор": "все → координатор",
        "подвижные: узлы пропадают": "узлы пропадают", "подвижные: случайные пары, 0.5 пак/с": "нагрузка 0,5 пак/с"}
s = df_final.copy()
s["группа"] = s["сценарий"].map(lambda x: "неподвижные (6 топологий)" if x.startswith("неподвижные") else cols[x])
summary = s.pivot_table(index="method", columns="группа", values="pdr_20s", aggfunc="mean")
summary = summary[list(cols.values()) + ["неподвижные (6 топологий)"]]
base = s[s["сценарий"] == "подвижные: случайные пары, 0.2 пак/с"].groupby("method")
summary["эфир на пакет, с"] = base.airtime_per_delivered_s.mean()
summary["задержка ср., с"] = base.latency_mean_s.mean()
summary = summary.reindex(list(LABELS)).rename(index=LABELS)
summary.round(3)
