# EXP 11.2: запасные маршруты (AOMDV)
DSR_CASES = [dict(pattern=["random"], rate=[0.2, 0.3, 0.5, 0.7], churn=[False]),
             dict(pattern=["sink"], rate=[0.2], churn=[False]),
             dict(pattern=["random"], rate=[0.2], churn=[True])]


def case_name(r):
    if r.churn:
        return "узлы пропадают"
    return "все → координатор" if r.pattern == "sink" else f"случайные пары {r.rate:g}"


def paired_vs(df, ref="hybrid_plus"):
    """Δ доставки к ref на одинаковых сценариях + эфир и число поисков по каждому случаю."""
    k = ["topo", "pattern", "rate", "churn", "seed"]
    d = df.assign(case=df.apply(case_name, axis=1))
    base = d[d.method == ref].set_index(k)
    rows = []
    for m in dict.fromkeys(d.method):
        if m == ref:
            continue
        x = d[d.method == m].set_index(k)
        delta = (x.pdr_20s - base.pdr_20s).dropna()
        tmp = pd.DataFrame({"Δ": delta, "air": x.airtime_per_delivered_s / base.airtime_per_delivered_s,
                            "disc": x.discoveries / base.discoveries, "case": x["case"]}).dropna(subset=["Δ"])
        for case, g in tmp.groupby("case", sort=False):
            rows.append({"вариант": m, "сценарий": case, "Δ доставлено за 20 с": g["Δ"].mean(),
                         "± 95 %": 1.96 * g["Δ"].std() / len(g) ** 0.5,
                         "эфир, × к hybrid_plus": g.air.mean(), "поисков, × к hybrid_plus": g.disc.mean()})
    return pd.DataFrame(rows).set_index(["вариант", "сценарий"])


V_MP = {"hybrid_plus": {}, "запасные пути, k = 2": dict(multipath_k=2), "запасные пути, k = 3": dict(multipath_k=3)}
SPECS_MP = [s for c in DSR_CASES for s in variants(V_MP, range(1, 11), base="hybrid_plus", topo=list(MOBILITY), **c)]
df_mp = run_grid("11_2_multipath", SPECS_MP)
paired_vs(df_mp).round(3)
