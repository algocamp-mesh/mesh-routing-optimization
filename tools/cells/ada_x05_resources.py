# EXP 11.5: как бюджет эфира разгружает горячие узлы
sub = df_amain[df_amain.method.isin(["hybrid", "hybrid_dc"])]
t = sub.groupby(["rate", "method"]).agg(
    max_node_duty=("max_node_duty", "mean"), deferrals=("duty_cycle_deferrals", "mean"),
    suppressed=("rreq_suppressed_dc", "mean"), lat=("latency_mean_s", "mean"), lat95=("latency_p95_s", "mean"),
    deadline=("fail_deadline", "mean"), generated=("generated", "mean"))
t["потерь по сроку 20 с, %"] = 100 * t.deadline / t.generated
t = t.drop(columns=["deadline", "generated"]).rename(columns={
    "max_node_duty": "макс. доля эфира узла", "deferrals": "откладываний из-за лимита (на прогон)",
    "suppressed": "непересланных RREQ (на прогон)", "lat": "задержка ср., с", "lat95": "задержка p95, с"})
t.round(3)
