# ⚙️ Наш кейс: до 20 подвижных узлов. Площадь 2000 × 2000 м даёт ту же плотность, что 30 узлов на 2500 × 2500 м
_RWP20 = {"walk": ((0.5, 1.5), (0, 60)), "vehicle": ((8, 15), (0, 10)), "drone": ((15, 25), (0, 5))}
for _k, (_v, _p) in _RWP20.items():
    TOPOLOGIES[f"rwp20_{_k}"] = (
        lambda rng, sim_time=600.0, n=20, area=2000.0, _v=_v, _p=_p, _name=f"rwp20_{_k}":
            topo_rwp(rng, n=n, area=area, v_range=_v, pause_range=_p, sim_time=sim_time, name=_name),
        None)

fig, axes = plt.subplots(1, 3, figsize=(10, 3.4))
for ax, t in zip(axes, (0, 300, 600)):
    draw_topology(build_topology("rwp20_vehicle", random.Random(1), 600.0), t=t, ax=ax,
                  title=f"rwp20_vehicle, t = {t} с")
plt.tight_layout(); plt.show()
