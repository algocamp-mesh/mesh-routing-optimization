# EXP 11.3: кому повторять
PA8 = dict(rreq_passive_ack=True, rreq_pack_timeout_s=0.8)
V_TARGET = {"hybrid_dc": {},
            "все узлы": PA8,
            "соседей ≤ 2": {**PA8, "rreq_pack_max_degree": 2},
            "соседей ≤ 3": {**PA8, "rreq_pack_max_degree": 3},
            "избирательно": {**PA8, "rreq_pack_selective": True},
            "соседей ≤ 2 + избирательно": {**PA8, "rreq_pack_max_degree": 2, "rreq_pack_selective": True}}
SPECS_TARGET = [s for c in CASES_REL for s in variants(V_TARGET, range(1, 13), base="hybrid_dc", **c)]
df_target = run_grid("11_3_target", SPECS_TARGET)
print("Доставлено за 20 с:")
display(rel_table(df_target).round(3))
print("Эфир на доставленный пакет, с:")
rel_table(df_target, "airtime_per_delivered_s").round(2)
