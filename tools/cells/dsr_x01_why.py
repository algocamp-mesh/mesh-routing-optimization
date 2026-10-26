# EXP 11.1: сколько поисков маршрута приходится на пакет
SPECS_WHY = grid(("hybrid_plus",), range(1, 11), topo=list(MOBILITY), pattern=["random", "sink"], rate=[0.2, 0.5])
df_why = run_grid("11_1_why", SPECS_WHY)
t = df_why.groupby(["pattern", "rate"]).agg(gen=("generated", "mean"), disc=("discoveries", "mean"),
                                            rreq=("air_share_RREQ", "mean"), pdr=("pdr_20s", "mean"),
                                            air=("airtime_per_delivered_s", "mean"))
t["поисков на пакет"] = t.disc / t.gen
t = t.rename(columns={"rreq": "доля эфира на RREQ", "pdr": "доставлено за 20 с", "air": "эфир на пакет, с"})
t[["поисков на пакет", "доля эфира на RREQ", "доставлено за 20 с", "эфир на пакет, с"]].round(3)
