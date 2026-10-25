@dataclass
class Route:
    """Запись таблицы маршрутов AODV."""
    nxt: int                       # следующий переход
    hops: int                      # число переходов до получателя
    cost: float                    # сумма ETX каналов (для metric = "etx")
    seq: int                       # номер последовательности получателя: чем больше, тем свежее
    expire: float                  # момент, когда маршрут устареет
    valid: bool = True
    precursors: set = field(default_factory=set)   # соседи, которые шлют через нас данные к этому получателю


class AodvState:
    """Энергозависимая память узла AODV: стирается при выключении."""

    def __init__(self, seq):
        self.seq = seq                     # собственный номер последовательности
        self.rreq_id = 0
        self.routes = {}                   # получатель -> Route
        self.rreq_seen = OrderedDict()     # (источник, rreq_id) -> время
        self.pending = {}                  # получатель -> deque пакетов, ждущих маршрут
        self.n_pending = 0
        self.discovery = {}                # получатель -> {"ttl", "retries", "ring", "token"}
        self.rebroadcast = {}              # (источник, rreq_id) -> {"dups"}: отложенные ретрансляции RREQ
        self.collect = {}                  # (источник, rreq_id) -> лучшая копия RREQ у получателя
        self.last_heard = {}               # сосед -> время последнего услышанного кадра
        self.parked = {}                   # получатель -> True: путь не найден, пакеты ждут (carry)
        self.last_try = {}                 # получатель -> время последнего поиска
        self.riding = {}                   # получатель -> пакет, который едет внутри RREQ (piggyback)


FIVE_YEARS_S = 5 * 365 * 24 * 3600


class AodvSimulator(Simulator):
    """AODV (RFC 3561) поверх модели LoRa. Параметры — AODV_PRESETS[method]."""

    def __init__(self, sc, method, seed):
        super().__init__(sc, method, seed)
        self.ac = AODV_PRESETS[method]
        self._ctrl_seq = itertools.count(1)          # ID служебных кадров отрицательные, чтобы не путать с пакетами
        self.ntt = self.ac.node_traversal_s
        self.net_diam = sc.hop_limit                 # NET_DIAMETER
        self.net_traversal = 2 * self.ntt * self.net_diam
        # ПЗУ: верхняя граница зарезервированных номеров переживает выключение
        self.flash_res = {n: 0 for n in self.nodes}
        self.flash_block_writes, self.flash_boot_writes, self.seq_changes = Counter(), Counter(), Counter()
        self.aodv = {n: AodvState(0) for n in self.nodes}
        for n in self.nodes:
            self._seq_bump(n, 0)
        self.flash_block_writes.clear()              # начальная запись при прошивке не считается
        self.peak = Counter()
        self.discovery_times = []

    def run(self):
        if self.ac.hello_interval_s:
            rng = random.Random(self.seed * 31 + 5)    # отдельный генератор: трафик не сдвигается
            for n in self.nodes:
                self.at(rng.uniform(0, self.ac.hello_interval_s), self._hello, n)
        return super().run()

    # Вспомогательное
    def _cid(self):
        return -next(self._ctrl_seq)

    def _m(self, hops, cost):
        return cost if self.ac.metric == "etx" else hops

    def _link_etx(self, a, b):
        """Качество канала по уровню сигнала, который узел измеряет при приёме."""
        P = self.topo.positions(self.t)
        return etx(min(math.dist(P[a], P[b]), self.topo.R), self.topo.R, self.ch)

    def _route(self, n, dst):
        rt = self.aodv[n].routes.get(dst)
        return rt if rt is not None and rt.valid and rt.expire > self.t else None

    def _seq_bump(self, n, new):
        """Номер последовательности не убывает. В ПЗУ пишется только граница блока."""
        st = self.aodv[n]
        if new > st.seq:
            self.seq_changes[n] += 1
            st.seq = new
        while st.seq >= self.flash_res[n]:
            self.flash_res[n] += self.ac.seq_flash_block
            self.flash_block_writes[n] += 1

    def _too_old(self, fr):
        if self.ac.deadline_s is None or fr.kind != "DATA":
            return False
        return self.t - self.packets[fr.pid]["t_gen"] > self.ac.deadline_s

    _stale = _too_old                                # хук очереди передачи в базовом симуляторе

    def _enqueue_now(self, node, frame, epoch):
        super()._enqueue_now(node, frame, epoch)
        self.peak["queue"] = max(self.peak["queue"], len(node.queue))

    # Таблица маршрутов
    def _update_route(self, n, dst, nxt, hops, cost, seq, life):
        """Правило RFC 3561, 6.2: свежее (больший seq) или при равном seq — короче/дешевле."""
        if dst == n:
            return
        st = self.aodv[n]
        rt = st.routes.get(dst)
        now = self.t
        active = rt is not None and rt.valid and rt.expire > now
        if (rt is None or seq > rt.seq
                or (seq == rt.seq and (not active or self._m(hops, cost) < self._m(rt.hops, rt.cost)))):
            pre = rt.precursors if rt is not None and active and rt.nxt == nxt else set()
            st.routes[dst] = Route(nxt, hops, cost, seq, now + life, True, pre)
            if len(st.routes) > self.ac.route_table_capacity:   # вытесняем устаревшую запись
                victim = min(st.routes, key=lambda d: (st.routes[d].valid and st.routes[d].expire > now,
                                                        st.routes[d].expire))
                del st.routes[victim]
                self.stats["route_evictions"] += 1
            self.peak["routes"] = max(self.peak["routes"], len(st.routes))
            if dst in st.pending:
                self._flush(n, dst)
        elif active and rt.nxt == nxt:
            rt.expire = max(rt.expire, now + life)

    # Источник
    def generate(self, src, dst):
        if src is None:
            src, dst = self.rng.sample(self.topo.nodes, 2)
        node = self.nodes[src]
        if not node.alive:
            self.stats["gen_skipped_src_off"] += 1
            return
        pid = next(self._pid_seq)
        self.packets[pid] = dict(pid=pid, src=src, dst=dst, t_gen=self.t, t_del=None, hops=None, reason=None,
                                 copy_reasons=Counter(), path_len=None, reachable=self._reachable(src, dst))
        fr = Frame("DATA", pid, src, dst, self.sc.hop_limit, size=self.cfg.header_bytes + self.sc.payload_bytes)
        node.mark_seen(pid)
        self._route_or_buffer(node, fr)

    def _route_or_buffer(self, node, fr, ttl=None):
        rt = self._route(node.id, fr.dst)
        if rt:
            self._send_data(node, fr, rt)
        else:
            self._buffer(node, fr, ttl)

    def _send_data(self, node, fr, rt):
        rt.expire = max(rt.expire, self.t + self.ac.active_route_timeout_s)
        self._enqueue_now(node, replace(fr, link_dst=rt.nxt), node.epoch)

    def _buffer(self, node, fr, ttl=None):
        st = self.aodv[node.id]
        if st.n_pending >= self.ac.pending_capacity:
            self.stats["drop_buffer_overflow"] += 1
            self._fail(fr.pid, "buffer_overflow", definitive=True)
            return
        st.pending.setdefault(fr.dst, deque()).append(fr)
        st.n_pending += 1
        self.peak["pending"] = max(self.peak["pending"], st.n_pending)
        if fr.dst not in st.discovery:
            self._start_discovery(node.id, fr.dst, ttl)

    def _flush(self, n, dst):
        """Маршрут появился: отправить всё, что ждало."""
        st = self.aodv[n]
        d = st.discovery.pop(dst, None)
        if d is not None:
            self.discovery_times.append(self.t - d["t0"])
        st.parked.pop(dst, None)
        q = list(st.pending.pop(dst, None) or ())
        rid = st.riding.pop(dst, None)
        if rid is not None:                              # не знаем, дошёл ли пакет из RREQ, — шлём и его
            q.insert(0, rid)
            st.n_pending += 1
        for k, fr in enumerate(q):
            st.n_pending -= 1
            if k == 0 or self.ac.flush_gap_s <= 0:
                self._resend(n, fr, self.nodes[n].epoch)
            else:                                     # пачку разносим во времени: меньше коллизий со скрытыми узлами
                self.at(self.t + k * self.ac.flush_gap_s, self._resend, n, fr, self.nodes[n].epoch)

    def _resend(self, n, fr, epoch):
        if self.nodes[n].epoch != epoch:
            self._fail(fr.pid, "node_off", definitive=True)
        elif self._too_old(fr):
            self._fail(fr.pid, "deadline", definitive=True)
        else:
            self._route_or_buffer(self.nodes[n], fr, ttl=fr.hop_limit)

    # Поиск маршрута
    def _start_discovery(self, n, dst, ttl0=None):
        ring = self.ac.expanding_ring and ttl0 is None
        ttl = self.ac.ttl_start if ring else min(ttl0 or self.net_diam, self.net_diam)
        st = self.aodv[n]
        st.discovery[dst] = dict(ttl=ttl, retries=0, ring=ring, token=0, t0=self.t)
        st.last_try[dst] = self.t
        st.parked.pop(dst, None)
        self.stats["discoveries"] += 1
        self._send_rreq(n, dst)

    def _rreq_mark(self, st, key):
        st.rreq_seen[key] = self.t
        if len(st.rreq_seen) > self.ac.rreq_cache_capacity:
            st.rreq_seen.popitem(last=False)
        self.peak["rreq_cache"] = max(self.peak["rreq_cache"], len(st.rreq_seen))

    def _send_rreq(self, n, dst):
        st, nd = self.aodv[n], self.nodes[n]
        d = st.discovery[dst]
        self._seq_bump(n, st.seq + 1)                 # RFC: перед RREQ свой номер увеличивается
        st.rreq_id += 1
        self._rreq_mark(st, (n, st.rreq_id))
        old = st.routes.get(dst)
        ctrl = dict(rreq_id=st.rreq_id, orig_seq=st.seq, dst_seq=old.seq if old else None, cost=0.0)
        size = self.cfg.header_bytes + self.ac.rreq_bytes
        if self.ac.piggyback:
            rid = self._take_rider(n, dst)
            if rid is not None:
                ctrl["data"] = rid
                size += self.sc.payload_bytes + 4               # полезная нагрузка + ID пакета и источник
                self.stats["piggybacked"] += 1
        fr = Frame("RREQ", self._cid(), n, dst, d["ttl"], size=size, ctrl=ctrl)
        self._enqueue_now(nd, fr, nd.epoch)
        if d["ring"] and d["ttl"] < self.net_diam:
            wait = 2 * self.ntt * (d["ttl"] + self.ac.timeout_buffer)       # RING_TRAVERSAL_TIME
        else:
            wait = self.net_traversal * (2 ** d["retries"] if self.ac.rreq_backoff else 1)
        d["token"] += 1
        self.at(self.t + wait, self._disc_timeout, n, dst, d["token"], nd.epoch)

    def _disc_timeout(self, n, dst, token, epoch):
        if self.nodes[n].epoch != epoch:
            return
        st = self.aodv[n]
        d = st.discovery.get(dst)
        if d is None or d["token"] != token:
            return
        if self._route(n, dst):
            self._flush(n, dst)
            return
        if d["ring"] and d["ttl"] < self.net_diam:
            d["ttl"] += self.ac.ttl_increment
            if d["ttl"] > self.ac.ttl_threshold:
                d["ttl"] = self.net_diam
            d["ttl"] = min(d["ttl"], self.net_diam)
        elif d["retries"] < self.ac.rreq_retries:
            d["retries"] += 1
            self.stats["rreq_retries"] += 1
        else:
            del st.discovery[dst]
            self.stats["discovery_failed"] += 1
            rid = st.riding.pop(dst, None)
            if rid is not None:                          # пакет из RREQ снова ждёт в буфере
                st.pending.setdefault(dst, deque()).appendleft(rid)
                st.n_pending += 1
            if self.ac.carry:
                self._park(n, dst)
                return
            reason = "no_route" if self._reachable(n, dst) else "unreachable"
            for fr in st.pending.pop(dst, ()):
                st.n_pending -= 1
                self._fail(fr.pid, reason, definitive=True)
            return
        self._send_rreq(n, dst)

    # Гибрид: пакет едет в RREQ, «храни и неси»
    def _take_rider(self, n, dst):
        """Пакет, который поедет внутри RREQ: прежний пассажир или первый из буфера."""
        st = self.aodv[n]
        rid = st.riding.get(dst)
        if rid is not None and self._too_old(rid):
            self._fail(st.riding.pop(dst).pid, "deadline", definitive=True)
            rid = None
        if rid is None and st.pending.get(dst):
            rid = st.pending[dst].popleft()
            st.n_pending -= 1
            st.riding[dst] = rid
        return rid

    def _park(self, n, dst):
        """Пути нет: пакеты ждут у узла до своего срока, пока не появится новый сосед."""
        st = self.aodv[n]
        keep = deque()
        for fr in st.pending.get(dst) or ():
            if self._too_old(fr):
                st.n_pending -= 1
                self._fail(fr.pid, "deadline", definitive=True)
            else:
                keep.append(fr)
        if not keep:
            st.pending.pop(dst, None)
            st.parked.pop(dst, None)
            return
        st.pending[dst] = keep
        st.parked[dst] = True
        self.stats["parked"] += 1
        expire = min(self.packets[fr.pid]["t_gen"] for fr in keep) + (self.ac.deadline_s or DEADLINE_S) + 1e-3
        nxt = expire if self.ac.carry_poll_s is None else min(expire, self.t + self.ac.carry_poll_s)
        self.at(max(nxt, self.t + 1e-3), self._carry_check, n, dst, self.nodes[n].epoch)

    def _carry_check(self, n, dst, epoch):
        st = self.aodv[n]
        if self.nodes[n].epoch != epoch or dst not in st.parked or dst in st.discovery:
            return
        if self._route(n, dst):
            self._flush(n, dst)
        elif (self.ac.carry_poll_s is not None
              and self.t - st.last_try.get(dst, -INF) >= self.ac.carry_poll_s):
            self.stats["carry_retries"] += 1
            self._start_discovery(n, dst, self.net_diam)
        else:
            self._park(n, dst)

    def _carry_wake(self, n):
        """Услышали нового соседа: сеть, возможно, снова связна — ищем путь для ждущих пакетов."""
        st = self.aodv[n]
        for dst in list(st.parked):
            if dst not in st.discovery and self.t - st.last_try.get(dst, -INF) >= self.ac.carry_min_gap_s:
                self.stats["carry_wakeups"] += 1
                self._start_discovery(n, dst, self.net_diam)

    # Приём
    def _on_data(self, r, frame):
        st, u = self.aodv[r.id], frame.link_src
        prev = st.last_heard.get(u)
        st.last_heard[u] = self.t
        if st.parked and (prev is None or self.t - prev > self.ac.carry_new_neighbor_s):
            self._carry_wake(r.id)
        k = frame.kind
        if k == "RREQ":
            return self._on_rreq(r, frame, u)
        if k == "RERR":
            return self._on_rerr(r, frame, u)
        if k == "HELLO":
            return self._on_hello(r, frame, u)
        if frame.link_dst != r.id:                    # адресный кадр не нам
            return
        self._send_ack(r, frame)
        # Повтор того же кадра (потерялся наш ACK) отбрасываем. Ключ — пакет и номер перехода: после починки
        # пакет может законно пройти через узел второй раз по новому пути, и это уже не повтор
        if not r.mark_seen((frame.pid, frame.hops)):
            self.stats["duplicates"] += 1
            return
        if k == "RREP":
            self._on_rrep(r, frame, u)
        else:
            self._on_unicast_data(r, frame, u)

    def _rev_life(self, hops):
        return max(self.ac.active_route_timeout_s, 2 * self.net_traversal - 2 * hops * self.ntt)

    def _on_rreq(self, r, frame, u):
        c, orig = frame.ctrl, frame.src
        if orig == r.id:
            return
        st = self.aodv[r.id]
        key = (orig, c["rreq_id"])
        le = self._link_etx(r.id, u)
        cost, hops = c["cost"] + le, frame.hops + 1
        if key in st.rreq_seen:                       # копия уже виденного запроса
            self.stats["rreq_duplicates"] += 1
            col = st.collect.get(key)
            if col is not None and self._m(hops, cost) < self._m(col["hops"], col["cost"]):
                col.update(u=u, hops=hops, cost=cost)
            elif key in st.rebroadcast:
                st.rebroadcast[key]["dups"] += 1
            return
        self._rreq_mark(st, key)
        if r.id == frame.dst and c.get("data") is not None:     # пакет приехал вместе с поиском
            self._deliver(replace(c["data"], hops=frame.hops), r)
        if r.id == frame.dst and self.ac.rrep_delay_s > 0:  # получатель ждёт другие копии
            st.collect[key] = dict(u=u, hops=hops, cost=cost, seq=c["orig_seq"], dst_seq=c["dst_seq"])
            self.at(self.t + self.ac.rrep_delay_s, self._dst_reply, r, key, orig, r.epoch)
            return
        self._update_route(r.id, orig, u, hops, cost, c["orig_seq"], self._rev_life(hops))   # обратный маршрут
        if r.id == frame.dst:
            self._reply_as_dst(r, orig, c["dst_seq"])
            return
        rt = self._route(r.id, frame.dst)
        if (self.ac.intermediate_reply and rt is not None and rt.nxt != u
                and (c["dst_seq"] is None or rt.seq >= c["dst_seq"])):
            rt.precursors.add(u)
            self.stats["rrep_intermediate"] += 1
            if c.get("data") is not None:              # поиск тут кончается — пакет дальше едет по маршруту
                left = max(c["data"].hop_limit - hops, 1)
                self._route_or_buffer(r, replace(c["data"], hops=hops, hop_limit=left, link_dst=None), ttl=left)
            self.at(self.t + self.ac.rrep_delay_s, self._intermediate_reply, r, frame.dst, orig, r.epoch)
            return
        if frame.hop_limit > 1:
            fwd = replace(frame, hop_limit=frame.hop_limit - 1, hops=hops, ctrl={**c, "cost": cost})
            delay = self.rng.uniform(*(self.ac.rreq_jitter_s or self.cfg.flood_jitter_s)) + self.ac.etx_delay_s * (le - 1)
            st.rebroadcast[key] = {"dups": 0}
            self.at(self.t + delay, self._rreq_fire, r, key, fwd, r.epoch)

    def _rreq_fire(self, r, key, fwd, epoch):
        if r.epoch != epoch:
            return
        rb = self.aodv[r.id].rebroadcast.pop(key, None)
        if rb is None:
            return
        if self.ac.rreq_suppress_dups is not None and rb["dups"] >= self.ac.rreq_suppress_dups:
            self.stats["rreq_suppressed"] += 1
            return
        self._enqueue_now(r, fwd, epoch)

    def _intermediate_reply(self, r, dst, orig, epoch):
        rt = self._route(r.id, dst) if r.epoch == epoch else None
        if rt is not None:
            self._send_rrep(r, dst, orig, rt.hops, rt.cost, rt.seq, rt.expire - self.t)

    def _dst_reply(self, r, key, orig, epoch):
        if r.epoch != epoch:
            return
        col = self.aodv[r.id].collect.pop(key, None)
        if col is None:
            return
        self._update_route(r.id, orig, col["u"], col["hops"], col["cost"], col["seq"], self._rev_life(col["hops"]))
        self._reply_as_dst(r, orig, col["dst_seq"])

    def _reply_as_dst(self, r, orig, req_dst_seq):
        if req_dst_seq is not None:
            self._seq_bump(r.id, req_dst_seq)         # RFC 6.6.1: не меньше запрошенного
        self.stats["rrep_dst"] += 1
        self._send_rrep(r, r.id, orig, 0, 0.0, self.aodv[r.id].seq, 2 * self.ac.active_route_timeout_s)

    def _send_rrep(self, r, dst, orig, hops, cost, dst_seq, life):
        rev = self._route(r.id, orig)
        if rev is None:
            self.stats["rrep_no_reverse"] += 1
            return
        fr = Frame("RREP", self._cid(), dst, orig, self.net_diam, link_dst=rev.nxt, hops=hops,
                   size=self.cfg.header_bytes + self.ac.rrep_bytes, ctrl=dict(dst_seq=dst_seq, cost=cost, life=life))
        self._enqueue_now(r, fr, r.epoch)

    def _on_rrep(self, r, frame, u):
        c = frame.ctrl
        hops, cost = frame.hops + 1, c["cost"] + self._link_etx(r.id, u)
        if frame.dst == r.id:                          # ответ на наш поиск: пакет из RREQ уже доставлен
            self.aodv[r.id].riding.pop(frame.src, None)
        self._update_route(r.id, frame.src, u, hops, cost, c["dst_seq"], c["life"])    # прямой маршрут
        if frame.dst == r.id:
            self.stats["rrep_received"] += 1
            return
        rev = self._route(r.id, frame.dst)
        if rev is None:
            self.stats["rrep_no_reverse"] += 1
            return
        fwd_rt = self._route(r.id, frame.src)
        if fwd_rt is not None:
            fwd_rt.precursors.add(rev.nxt)
        rev.precursors.add(u)
        rev.expire = max(rev.expire, self.t + self.ac.active_route_timeout_s)
        self._enqueue_now(r, replace(frame, link_dst=rev.nxt, hops=hops, ctrl={**c, "cost": cost}), r.epoch)

    def _on_unicast_data(self, r, frame, u):
        if frame.dst == r.id:
            self._deliver(frame, r)
            return
        rs = self._route(r.id, frame.src)              # RFC: использование продлевает и обратный маршрут
        if rs is not None:
            rs.expire = max(rs.expire, self.t + self.ac.active_route_timeout_s)
        if frame.hop_limit <= 1:
            self._fail(frame.pid, "hoplimit_exceeded", definitive=True)
            return
        fwd = replace(frame, hop_limit=frame.hop_limit - 1, hops=frame.hops + 1, link_dst=None)
        rt = self._route(r.id, frame.dst)
        if rt is not None:
            rt.precursors.add(u)
            self._send_data(r, fwd, rt)
            return
        self.stats["data_no_route"] += 1
        if self.ac.local_repair and not self._too_old(fwd):
            self.stats["local_repairs"] += 1
            self._buffer(r, fwd, ttl=fwd.hop_limit)
            return
        old = self.aodv[r.id].routes.get(frame.dst)
        self._send_rerr(r.id, [(frame.dst, old.seq if old else 0)])
        self._fail(frame.pid, "no_route", definitive=True)

    # Обрыв канала
    def _retry_limit(self, node, fr):
        heard = self.aodv[node.id].last_heard.get(fr.link_dst)
        recent = heard is not None and self.t - heard <= self.ac.heard_window_s
        return self.cfg.max_retries + (self.ac.extra_retries_if_heard if recent else 0)

    def _retry_delay(self, node):
        b = self.ac.retry_backoff_s
        if b is None:
            return super()._retry_delay(node)
        return b * 2 ** min(node.retries - 1, 4) * self.rng.uniform(0.5, 1.0)

    def _on_link_fail(self, node, fr):
        """После max_retries повторов без ACK."""
        v = fr.link_dst
        self.stats["link_breaks"] += 1
        self._break_link(node.id, v)
        stuck = [f for f in node.queue if f.link_dst == v and f.kind in ("DATA", "RREP")]
        for f in stuck:                               # кадры в очереди к тому же соседу
            node.queue.remove(f)
        for f in [fr] + stuck:
            if f.kind != "DATA":
                self.stats["rrep_lost_link"] += f.kind == "RREP"
                continue
            if self.ac.local_repair and not self._too_old(f):
                self.stats["local_repairs"] += 1
                self._route_or_buffer(node, replace(f, link_dst=None), ttl=f.hop_limit)
            else:
                self._fail(f.pid, "link_broken", definitive=True)

    def _break_link(self, n, v):
        st = self.aodv[n]
        unreach = []
        for dst, rt in st.routes.items():
            if rt.valid and rt.nxt == v:
                rt.valid, rt.seq, rt.expire = False, rt.seq + 1, self.t
                if rt.precursors:
                    unreach.append((dst, rt.seq))
        st.last_heard.pop(v, None)
        if unreach:
            self._send_rerr(n, unreach)

    def _send_rerr(self, n, unreach):
        nd = self.nodes[n]
        size = self.cfg.header_bytes + self.ac.rerr_bytes_base + self.ac.rerr_bytes_per_dst * len(unreach)
        self.stats["rerr_sent"] += 1
        self._enqueue_now(nd, Frame("RERR", self._cid(), n, -1, 1, size=size, ctrl=dict(unreach=unreach)), nd.epoch)

    def _on_rerr(self, r, frame, u):
        st = self.aodv[r.id]
        prop = []
        for dst, seq in frame.ctrl["unreach"]:
            rt = st.routes.get(dst)
            if rt is not None and rt.valid and rt.nxt == u:
                rt.valid, rt.seq, rt.expire = False, max(rt.seq, seq), self.t
                if rt.precursors:
                    prop.append((dst, rt.seq))
        if prop:
            self._send_rerr(r.id, prop)

    # HELLO
    def _hello(self, n):
        nd, st, a = self.nodes[n], self.aodv[n], self.ac
        if nd.alive:
            lim = self.t - a.allowed_hello_loss * a.hello_interval_s
            for v in [v for v, tl in st.last_heard.items() if tl < lim]:
                if any(rt.valid and rt.nxt == v for rt in st.routes.values()):
                    self.stats["hello_link_breaks"] += 1
                    self._break_link(n, v)
                st.last_heard.pop(v, None)
            if any(rt.valid and rt.expire > self.t for rt in st.routes.values()):   # RFC: только на активном маршруте
                self._enqueue_now(nd, Frame("HELLO", self._cid(), n, -1, 1, size=self.cfg.header_bytes + a.hello_bytes,
                                            ctrl=dict(seq=st.seq)), nd.epoch)
        self.at(self.t + a.hello_interval_s * self.rng.uniform(0.95, 1.05), self._hello, n)

    def _on_hello(self, r, frame, u):
        life = self.ac.allowed_hello_loss * self.ac.hello_interval_s
        self._update_route(r.id, u, u, 1, self._link_etx(r.id, u), frame.ctrl["seq"], life)

    # Выключение: таблицы и буфер стираются, граница номеров в ПЗУ остаётся
    def _on_node_off(self, nd):
        st = self.aodv[nd.id]
        for fr in [f for q in st.pending.values() for f in q] + list(st.riding.values()):
            self._fail(fr.pid, "node_off", definitive=True)
        self.aodv[nd.id] = AodvState(self.flash_res[nd.id])
        before = self.flash_block_writes[nd.id]
        self._seq_bump(nd.id, self.flash_res[nd.id])  # после включения — с новой границы блока
        self.flash_boot_writes[nd.id] += self.flash_block_writes[nd.id] - before
        self.flash_block_writes[nd.id] = before

    # Ресурсы и итоги
    def ram_bytes(self):
        """ОЗУ под структуры маршрутизации при статическом выделении по ёмкостям."""
        a, c = self.ac, self.cfg
        frame_b = c.header_bytes + self.sc.payload_bytes + 8          # кадр + служебные поля в памяти
        return (a.route_table_capacity * 24 + a.rreq_cache_capacity * 8 + a.pending_capacity * frame_b
                + c.queue_capacity * frame_b + c.mcu.queue_capacity * frame_b + c.seen_cache_capacity * 4
                + 2 * len(self.nodes) * 8)                            # отложенные RREQ и последние услышанные соседи

    def summary(self):
        out = super().summary()
        T, air_total = self.sc.sim_time_s, sum(self.air.values())
        for k in ("RREQ", "RREP", "RERR", "HELLO"):
            out["air_share_" + k] = self.air[k] / air_total if air_total else 0.0
        for k in ("discoveries", "discovery_failed", "rrep_intermediate", "rreq_suppressed",
                  "link_breaks", "local_repairs", "rerr_sent", "hello_link_breaks",
                  "piggybacked", "parked", "carry_wakeups", "carry_retries"):
            out[k] = self.stats[k]
        out["discovery_time_mean_s"] = (sum(self.discovery_times) / len(self.discovery_times)
                                        if self.discovery_times else float("nan"))
        out["flash_naive_5y"] = max(self.seq_changes[n] for n in self.nodes) / T * FIVE_YEARS_S
        out["flash_writes_5y"] = out["flash_naive_5y"] / self.ac.seq_flash_block   # ожидаемое при записи блоками
        out["flash_boot_writes"] = sum(self.flash_boot_writes.values())
        out["ram_bytes"] = self.ram_bytes()
        for k in ("routes", "pending", "queue", "rreq_cache"):
            out["peak_" + k] = self.peak[k]
        return out


def simulate(sc: Scenario, method: str, seed: int = 1):
    sim = (AodvSimulator if method in AODV_PRESETS else Simulator)(sc, method, seed)
    res = sim.run()
    return res, sim
