# ⚙️ Исследование 3: гибрид с бюджетом эфира
AODV_PRESETS["hybrid_dc"] = replace(AODV_PRESETS["hybrid"],
                                    dc_aware_rreq=0.6,      # израсходовал 60 % лимита эфира — не пересылает чужие RREQ
                                    dc_aware_min_dups=0)    # даже если копий не слышал
METHOD_COLORS.update({"hybrid_dc": "#0b7285"})
