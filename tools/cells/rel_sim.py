# ⚙️ Исследование 4: надёжный RREQ
AODV_PRESETS["hybrid_plus"] = replace(AODV_PRESETS["hybrid_dc"],
                                      rreq_passive_ack=True,       # никто не переслал наш RREQ дальше — повторить
                                      rreq_pack_timeout_s=0.8,
                                      rreq_pack_retries=1,
                                      rreq_pack_max_degree=2)      # только у звеньев цепочек и мостов
METHOD_COLORS.update({"hybrid_plus": "#5f3dc4"})
