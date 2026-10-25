# ⚙️ Гибрид и контрольные методы
HYBRID = replace(AODV_PRESETS["aodv_lora"],
                 piggyback=True,          # первый пакет едет внутри RREQ: доставка уже во время поиска
                 carry=True,              # пути нет — пакеты ждут у узла до срока и ищут путь при появлении соседа
                 rreq_retries=1)          # меньше слепых повторов поиска: их заменяет «храни и неси»
AODV_PRESETS["hybrid"] = HYBRID

# Контроль: «а не то же ли это, что затопить пакет несколько раз?»
# Источник повторяет затопление пакета k раз с интервалом gap, не зная, дошёл ли он
FLOOD_REPEAT = {"flooding_x2": (2, 3.0), "flooding_x3": (3, 3.0)}


class FloodRepeatSimulator(Simulator):
    """Затопление с k повторными рассылками каждого пакета от источника."""

    def __init__(self, sc, method, seed):
        super().__init__(sc, "flooding", seed)          # внутри — обычное затопление
        self.label = method
        self.repeats, self.gap = FLOOD_REPEAT[method]

    def summary(self):
        return {**super().summary(), "method": self.label}

    def generate(self, src, dst):
        n_before = len(self.packets)
        super().generate(src, dst)
        if len(self.packets) == n_before:                 # источник выключен — пакета нет
            return
        pid = next(reversed(self.packets))
        node = self.nodes[self.packets[pid]["src"]]
        for k in range(1, self.repeats):
            self.at(self.t + k * self.gap, self._repeat, node, pid, k, node.epoch)

    def _repeat(self, node, pid, k, epoch):
        if node.epoch != epoch or not node.alive:
            return
        rec = self.packets[pid]
        node.mark_seen((pid, k))
        self._enqueue_now(node, Frame("DATA", pid, rec["src"], rec["dst"], self.sc.hop_limit,
                                      size=self.cfg.header_bytes + self.sc.payload_bytes, ctrl={"rep": k}), epoch)

    def _on_data(self, r, frame):
        rep = (frame.ctrl or {}).get("rep", 0)
        if not r.mark_seen(frame.pid if rep == 0 else (frame.pid, rep)):
            self.stats["duplicates"] += 1
            return
        if frame.dst == r.id:
            self._deliver(frame, r)
            return
        if frame.hop_limit > 1:
            fwd = replace(frame, hop_limit=frame.hop_limit - 1, hops=frame.hops + 1)
            self.at(self.t + self.rng.uniform(*self.cfg.flood_jitter_s), self._enqueue_now, r, fwd, r.epoch)
        else:
            self._fail(frame.pid, "hoplimit_exhausted", definitive=False)


def simulate(sc: Scenario, method: str, seed: int = 1):
    if method in FLOOD_REPEAT:
        cls = FloodRepeatSimulator
    elif method in AODV_PRESETS:
        cls = AodvSimulator
    else:
        cls = Simulator
    sim = cls(sc, method, seed)
    return sim.run(), sim


METHOD_COLORS.update({"hybrid": "#2f9e44", "flooding_x2": "#4dabf7", "flooding_x3": "#a5d8ff"})
