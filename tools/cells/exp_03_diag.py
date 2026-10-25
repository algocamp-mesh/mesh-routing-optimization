# EXP 10.3: диагностика — обрывы канала настоящие или ложные?
class BreakProbe(AodvSimulator):
    """AODV, который в момент «обрыва» спрашивает оракула: сосед правда ушёл?"""

    def __init__(self, *a):
        super().__init__(*a)
        self.breaks = Counter()

    def _on_link_fail(self, node, fr):
        in_range = any(m == fr.link_dst for m, _ in self.neighbors(node.id))
        self.breaks[(in_range, fr.kind)] += 1
        super()._on_link_fail(node, fr)


rows = []
for topo in MOBILITY:
    for m in ("aodv_rfc", "aodv_lora"):
        tot, gen = Counter(), 0
        for seed in range(1, 4):
            sim = BreakProbe(make_scenario(topo), m, seed)
            res = sim.run()
            tot.update(sim.breaks)
            gen += res["generated"]
        n = sum(tot.values())
        false = sum(v for (in_range, _), v in tot.items() if in_range)
        rows.append({"сценарий": MOBILITY[topo], "метод": m, "пакетов": gen, "«обрывов»": n,
                     "ложных (сосед рядом), %": round(100 * false / n, 1) if n else 0.0,
                     "из них при отправке RREP": sum(v for (_, kind), v in tot.items() if kind == "RREP"),
                     "из них при отправке DATA": sum(v for (_, kind), v in tot.items() if kind == "DATA")})
pd.DataFrame(rows)
