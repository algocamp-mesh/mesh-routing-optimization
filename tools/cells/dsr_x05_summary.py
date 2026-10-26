# EXP 11.5: сводка всех исследований и сравнение с DSR коллеги
DSR_CSV = os.path.join("results", "compare_dsr", "dsr_on_our_scenarios.csv")   # tools/compare_dsr.py, те же сценарии и seed
dsr = pd.read_csv(DSR_CSV)
dsr = dsr[dsr.method == "dsr"]
s = pd.concat([df_f5, dsr], ignore_index=True)


def group(r):
    if r.topo not in MOBILITY:
        return "неподвижные (6 топологий)"
    if r.churn:
        return "узлы пропадают"
    if r.pattern == "sink":
        return "все → координатор"
    return f"случайные пары, {r.rate:g} пак/с"


s["группа"] = s.apply(group, axis=1)
order = ["случайные пары, 0.2 пак/с", "все → координатор", "узлы пропадают", "случайные пары, 0.5 пак/с",
         "неподвижные (6 топологий)"]
LABELS5 = {"flooding": "затопление", "flooding_x3": "затопление ×3 (контроль)", "aodv_rfc": "1. AODV по RFC",
           "aodv_lora": "1. aodv_lora", "dsr": "DSR (ветка DSR, коллега)", "hybrid": "2. hybrid",
           "hybrid_dc": "3. hybrid_dc", "hybrid_plus": "4. hybrid_plus", "hybrid_ovh": "5. hybrid_ovh",
           "dijkstra": "эталон Дейкстры (оракул)"}
summary5 = s.pivot_table(index="method", columns="группа", values="pdr_20s", aggfunc="mean")[order]
base = s[s["группа"] == order[0]].groupby("method")
summary5["эфир на пакет, с"] = base.airtime_per_delivered_s.mean()
summary5["задержка ср., с"] = base.latency_mean_s.mean()
summary5 = summary5.reindex(list(LABELS5)).rename(index=LABELS5)
print("PDR за 20 с. Эфир и задержка — для случайных пар, 0,2 пакета/с:")
display(summary5.round(3))

mob = df_f5[df_f5.topo.isin(MOBILITY) & (df_f5.pattern == "random") & (df_f5.rate == 0.2) & ~df_f5.churn
            & df_f5.method.isin(["hybrid_plus", "hybrid_ovh", "dijkstra"])]
print("Подвижный кейс, случайные пары, 0,2 пакета/с — проверка требований:")
criteria_table(mob.assign(topo=mob.topo.map(MOBILITY)))
