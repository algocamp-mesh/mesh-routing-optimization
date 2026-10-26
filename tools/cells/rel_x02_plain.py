# EXP 11.2: пассивное подтверждение без ограничений
PA = dict(rreq_passive_ack=True)
V_PLAIN = {"hybrid_dc": {},
           "ожидание 0,5 с": {**PA, "rreq_pack_timeout_s": 0.5},
           "ожидание 0,8 с": {**PA, "rreq_pack_timeout_s": 0.8},
           "ожидание 1,2 с": {**PA, "rreq_pack_timeout_s": 1.2},
           "ожидание 0,8 с, 2 повтора": {**PA, "rreq_pack_timeout_s": 0.8, "rreq_pack_retries": 2}}
CASES_REL = [dict(topo=["line10", "grid4x4", "ring12"], pattern=["default"], rate=[0.2]),
             dict(topo=list(MOBILITY), pattern=["random"], rate=[0.2, 0.5])]
SPECS_PLAIN = [s for c in CASES_REL for s in variants(V_PLAIN, range(1, 11), base="hybrid_dc", **c)]
df_plain = run_grid("11_2_plain", SPECS_PLAIN)


def case_label(r):
    name = MOBILITY.get(r.topo, r.topo)
    return f"{name}, {r.rate:g} пак/с" if r.topo in MOBILITY else name


def rel_table(df, value="pdr_20s"):
    d = df.assign(case=df.apply(case_label, axis=1))
    cols = list(dict.fromkeys(d.case))
    return d.pivot_table(index="method", columns="case", values=value, aggfunc="mean", sort=False)[cols]


print("Доставлено за 20 с:")
display(rel_table(df_plain).round(3))
print("Эфир на доставленный пакет, с:")
rel_table(df_plain, "airtime_per_delivered_s").round(2)
