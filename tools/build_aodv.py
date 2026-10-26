"""Собирает 1_simple_aodv.ipynb из исходного блокнота + новых ячеек."""
import json, sys, copy, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
HERE = pathlib.Path(__file__).parent
CELLS = HERE / "cells"
SRC = ROOT / "theory" / "mesh_routing_simulation.ipynb"
DST = ROOT / "1_simple_aodv.ipynb"

nb = json.loads(SRC.read_text(encoding="utf-8"))
cells = nb["cells"]


def src(i):
    return "".join(cells[i]["source"])


def set_src(i, text):
    cells[i]["source"] = text.splitlines(keepends=True)


def patch(i, old, new, count=1):
    s = src(i)
    assert s.count(old) == count, (i, old[:80], s.count(old))
    set_src(i, s.replace(old, new))


def md(text):
    return {"cell_type": "markdown", "metadata": {}, "source": text.strip("\n").splitlines(keepends=True)}


def code(text):
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
            "source": text.strip("\n").splitlines(keepends=True)}


def file_code(name):
    return code((CELLS / name).read_text(encoding="utf-8"))


def file_md(name):
    return md((CELLS / name).read_text(encoding="utf-8"))


# ---------- правки исходных ячеек ----------
# 7: Frame — служебные поля AODV
patch(7, '    hops: int = 0                     # сколько переходов уже пройдено\n',
         '    hops: int = 0                     # сколько переходов уже пройдено\n'
         '    ctrl: Optional[dict] = None       # служебные поля AODV (RREQ, RREP, RERR, HELLO)\n')

# 22: ядро симулятора
patch(22, 'assert method in METHODS, method', 'assert method in METHODS or method in AODV_PRESETS, method')
patch(22, '''                   reason=None, copy_reasons=Counter(), path_len=None)''',
          '''                   reason=None, copy_reasons=Counter(), path_len=None, reachable=self._reachable(src, dst))''')
patch(22, '''    # Трафик
    def _schedule_traffic(self):''',
          '''    def _reachable(self, s, d):
        """Есть ли сейчас путь s → d (оракул, только для диагностики: потери из-за распада сети)."""
        return dijkstra(self.snapshot_graph(), s, d)[0] is not None

    # Трафик
    def _schedule_traffic(self):''')
patch(22, '''        frame = node.queue[0]
        dur = lora_toa(frame.size, self.radio)''',
          '''        while node.queue and self._stale(node.queue[0]):  # срок доставки истёк: не тратим эфир
            self._fail(node.queue.popleft().pid, "deadline", definitive=True)
        if not node.queue:
            return
        frame = node.queue[0]
        dur = lora_toa(frame.size, self.radio)''')
patch(22, '''        if frame.kind == "DATA" and frame.link_dst is not None:   # ждём ACK''',
          '''        if frame.kind != "ACK" and frame.link_dst is not None:    # адресный кадр: ждём ACK''')
patch(22, '''        elif frame.kind == "DATA":
            node.busy = False
            self._kick(node)
        else:                                            # закончили ACK''',
          '''        elif frame.kind != "ACK":                        # широковещательный кадр
            node.busy = False
            self._kick(node)
        else:                                            # закончили ACK''')
patch(22, '''            node.retries, node.current, node.busy = 0, None, False
            self._fail(fr.pid, "link_broken", definitive=True)
            self._kick(node)''',
          '''            node.retries, node.current, node.busy = 0, None, False
            self._on_link_fail(node, fr)
            self._kick(node)''')
patch(22, '''    # Динамика
    def _node_off(self, n):''',
          '''    # Хуки для методов с собственным состоянием (AODV, раздел 4.1)
    def _stale(self, frame):
        """True — кадр устарел, отбросить из очереди не передавая."""
        return False

    def _on_link_fail(self, node, fr):
        """Адресный кадр не подтверждён после max_retries повторов."""
        self._fail(fr.pid, "link_broken", definitive=True)

    def _on_node_off(self, nd):
        pass

    # Динамика
    def _node_off(self, n):''')
patch(22, '''        nd.reset_volatile()
        nd.mcu_busy_until = self.t''',
          '''        self._on_node_off(nd)
        nd.reset_volatile()
        nd.mcu_busy_until = self.t''')
patch(22, '''                             hops=r["hops"], outcome=outcome))''',
          '''                             hops=r["hops"], outcome=outcome, reachable=r.get("reachable")))''')
patch(22, '''                   pdr=len(dl) / gen if gen else float("nan"),''',
          '''                   pdr=len(dl) / gen if gen else float("nan"),
                   pdr_20s=(dl.latency_s <= DEADLINE_S).sum() / gen if gen else float("nan"),
                   reachable_share=pk.reachable.mean() if gen else float("nan"),''')
patch(22, '''                   latency_p95_s=dl.latency_s.quantile(0.95) if len(dl) else float("nan"),''',
          '''                   latency_p95_s=dl.latency_s.quantile(0.95) if len(dl) else float("nan"),
                   latency_max_s=dl.latency_s.max() if len(dl) else float("nan"),''')
patch(22, '''tx_per_delivered=(self.stats["tx_DATA"] + self.stats["tx_ACK"]) / len(dl) if len(dl) else float("nan"),
                   overhead_share=self.air["ACK"] / air_total if air_total else 0.0,''',
          '''tx_per_delivered=sum(v for k, v in self.stats.items() if k.startswith("tx_")) / len(dl) if len(dl) else float("nan"),
                   overhead_share=(air_total - self.air["DATA"]) / air_total if air_total else 0.0,''')

patch(22, '''        for s, d in streams:
            t = tr.start_s + self.rng.expovariate(tr.rate_pps)
            while t < t_stop:
                self.at(t, self.generate, s, d)
                t += self.rng.expovariate(tr.rate_pps)''',
          '''        for s, d in streams:
            t = tr.start_s + self.rng.expovariate(tr.rate_pps)
            while t < t_stop:
                # случайная пара выбирается заранее: у всех методов одинаковый трафик при одном seed
                self.at(t, self.generate, *((s, d) if s is not None else self.rng.sample(self.topo.nodes, 2)))
                t += self.rng.expovariate(tr.rate_pps)''')

patch(22, '''        if node.retries < self.cfg.max_retries:
            node.retries += 1
            self.stats["retransmissions"] += 1
            node.queue.appendleft(fr)
            self.at(self.t + self.rng.uniform(*self.cfg.csma_backoff_s), self._unbusy_kick, node, epoch)''',
          '''        if node.retries < self._retry_limit(node, fr):
            node.retries += 1
            self.stats["retransmissions"] += 1
            node.queue.appendleft(fr)
            self.at(self.t + self._retry_delay(node), self._unbusy_kick, node, epoch)''')
patch(22, '''    def _on_link_fail(self, node, fr):''',
          '''    def _retry_limit(self, node, fr):
        return self.cfg.max_retries

    def _retry_delay(self, node):
        return self.rng.uniform(*self.cfg.csma_backoff_s)

    def _on_link_fail(self, node, fr):''')

# 24: цвета новых методов
patch(24, '''    colors = {"flooding": "#1c7ed6", "dijkstra": "#e8590c", "dp_hoplimit": "#2f9e44"}''',
          '''    colors = METHOD_COLORS''')

# ---------- новые и заменённые ячейки ----------
new = []
for i, c in enumerate(cells):
    if i == 0:
        new.append(file_md("md_intro.md"))
        new.append(file_md("md_task.md"))
        new.append(file_code("criteria.py"))
        continue
    if i >= 25:                          # старые эксперименты заменяются исследованием AODV
        continue
    new.append(c)
    if i == 4:
        pass
    if i == 13:                          # после проверки DP — описание и параметры AODV
        new.append(file_md("md_aodv.md"))
        new.append(file_code("aodv_config.py"))
    if i == 16:                          # после рисунков топологий — наш кейс
        new.append(file_md("md_topo20.md"))
        new.append(file_code("topo20.py"))
    if i == 22:                          # после ядра — реализация AODV
        new.append(file_md("md_aodv_impl.md"))
        new.append(file_code("aodv_sim.py"))
    if i == 23:
        new.append(file_md("md_metrics_add.md"))

for name in sorted(p.name for p in CELLS.glob("exp_*")):
    new.append(file_md(name) if name.endswith(".md") else file_code(name))

nb["cells"] = new
for c in nb["cells"]:
    if c["cell_type"] == "code":
        c["outputs"], c["execution_count"] = [], None
DST.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
print("written", DST, len(new), "cells")
