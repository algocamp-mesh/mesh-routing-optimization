# EXP 11.3: подслушивание чужих RREP
V_OVH = {"hybrid_plus": {},
         "подслушивание RREP": dict(overhear_rrep=True),
         "+ подслушивание DATA": dict(overhear_rrep=True, overhear_data=True),
         "только хороший канал (ETX ≤ 1,1)": dict(overhear_rrep=True, overhear_max_etx=1.1),
         "без ответов за других": dict(overhear_rrep=True, overhear_no_ireply=True),
         "ETX ≤ 1,1 + без ответов за других": dict(overhear_rrep=True, overhear_max_etx=1.1, overhear_no_ireply=True),
         "без ответов за других + запасные пути k = 2": dict(overhear_rrep=True, overhear_no_ireply=True, multipath_k=2)}
SPECS_OVH = [s for c in DSR_CASES for s in variants(V_OVH, range(1, 11), base="hybrid_plus", topo=list(MOBILITY), **c)]
df_ovh = run_grid("11_3_overhear", SPECS_OVH)
paired_vs(df_ovh).round(3)
