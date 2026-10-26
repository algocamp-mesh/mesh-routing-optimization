# ⚙️ Исследование 5: идеи из DSR
AODV_PRESETS["hybrid_ovh"] = replace(AODV_PRESETS["hybrid_plus"],
                                     overhear_rrep=True,          # запоминать свежий маршрут из чужого RREP
                                     overhear_no_ireply=True)     # но не отвечать по нему на чужие RREQ
METHOD_COLORS.update({"hybrid_ovh": "#c2255c", "dsr": "#868e96"})
