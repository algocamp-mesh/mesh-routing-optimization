"""hybrid_plus — итоговый вариант маршрутизации для подвижной Mesh-сети LoRa (исследования 1–4).

    hybrid_plus = AODV (RFC 3561)
                + 4 доработки под LoRa             (исследование 1: aodv_lora)
                + первый пакет внутри RREQ
                  и «храни и неси»                  (исследование 2: hybrid)
                + бюджет эфира                      (исследование 3: hybrid_dc)
                + надёжный RREQ на цепочках         (исследование 4: hybrid_plus)

hybrid_ovh  = hybrid_plus + подслушивание чужих RREP (исследование 5) — лучший вариант по итогам всех исследований,
              запускается через --methods hybrid_ovh

Один файл: модель LoRa, канал, узел, ядро дискретно-событийного симулятора, AODV со всеми механизмами,
контрольные методы (затопление, затопление ×3, эталон Дейкстры). Параметры итогового варианта —
AODV_PRESETS["hybrid_plus"]; их можно вывести: python hybrid_plus.py --config

Примеры:
    python hybrid_plus.py                                    # hybrid_plus, техника, случайные пары, 0,2 пак/с, 10 повторов
    python hybrid_plus.py --topo rwp20_walk --pattern sink   # пешеходы, все шлют узлу 0
    python hybrid_plus.py --methods hybrid_ovh,hybrid_plus,dijkstra --rate 0.5 --seeds 1-20
    python hybrid_plus.py --topo line10 --pattern default    # неподвижная линия из исходного симулятора

Зависимости: Python 3.10+, pandas, matplotlib.
Файл сгенерирован из блокнота 5_dsr_ideas.ipynb скриптом tools/build_standalone.py — правки вносить в tools/cells/.
"""

import matplotlib
matplotlib.use("Agg")                          # без окон: рисунки здесь не нужны

# ⚙️ Требования к подвижному случаю (theory/fix, 21.10.2026)
N_NODES_MAX = 20            # до 20 подвижных узлов
LOSS_MAX = 0.10             # потери не больше 10 %
DEADLINE_S = 20.0           # доставка не дольше 20 с
RAM_MAX_B = 200 * 1024      # ОЗУ 200 кБ
ROM_MAX_B = 500 * 1024      # ПЗУ 500 кБ
FLASH_WRITES_MAX = 100_000  # перезаписей ПЗУ за 5 лет непрерывной работы

METHOD_COLORS = {"flooding": "#1c7ed6", "dijkstra": "#e8590c", "dp_hoplimit": "#2f9e44",
                 "aodv_rfc": "#ae3ec9", "aodv_rfc_hello": "#f783ac", "aodv_lora": "#f59f00"}


import math, heapq, random, bisect, itertools
from collections import deque, OrderedDict, Counter
from dataclasses import dataclass, field, fields, replace
from typing import Optional

import pandas as pd
import matplotlib.pyplot as plt

pd.set_option("display.width", 180)
pd.set_option("display.max_columns", 40)


@dataclass
class RadioConfig:
    """⚙️ Параметры радио: Semtech SX1262."""
    chip: str = "SX1262"
    sf: int = 7                      # spreading factor, 5..12
    bw_hz: float = 125_000           # полоса, Гц
    cr: int = 1                      # 1..4 -> 4/5..4/8
    preamble_symbols: int = 8
    explicit_header: bool = True
    crc_on: bool = True
    low_dr_optimize: Optional[bool] = None   # None = авто (T_sym >= 16,38 мс)
    voltage_v: float = 3.3
    tx_power_dbm: int = 22
    i_tx_ma: float = 118.0           # передача +22 dBm, DC-DC
    i_rx_ma: float = 4.6             # дежурный приём LoRa, BW 125 кГц, DC-DC
    i_sleep_ma: float = 0.0006       # сон с сохранением конфигурации, ~0,6 мкА (ориентировочно)


def lora_toa(payload_bytes: int, r: RadioConfig) -> float:
    """Время в эфире кадра LoRa для SX126x, с (даташит SX1261/2, раздел 6.1.4)."""
    assert 5 <= r.sf <= 12, "SX1262 поддерживает SF5..SF12"
    t_sym = (2 ** r.sf) / r.bw_hz
    ldro = r.low_dr_optimize if r.low_dr_optimize is not None else (t_sym >= 0.01638)
    h = 1 if r.explicit_header else 0
    crc = 1 if r.crc_on else 0
    if r.sf in (5, 6):
        n_pre = r.preamble_symbols + 6.25
        num = 8 * payload_bytes + 16 * crc - 4 * r.sf + 20 * h
        den = 4 * r.sf
    else:
        n_pre = r.preamble_symbols + 4.25
        num = 8 * payload_bytes + 16 * crc - 4 * r.sf + 8 + 20 * h
        den = 4 * (r.sf - 2 * int(ldro))
    n_payload = 8 + math.ceil(max(num, 0) / den) * (r.cr + 4)
    return (n_pre + n_payload) * t_sym


assert abs(lora_toa(20, RadioConfig(sf=7)) - 0.05658) < 1e-4   # контрольное значение 56,6 мс


@dataclass
class McuConfig:
    """⚙️ Микроконтроллер: время обработки и потребление (допущение 4)."""
    name: str = "nRF52840"
    t_rx_proc_s: float = 0.004         # обработка принятого кадра, с
    t_tx_prep_s: float = 0.002         # подготовка кадра к передаче (DATA и ACK), с
    queue_capacity: int = 8            # очередь задач MCU (ограничение памяти)
    i_active_ma: float = 3.3           # ток во время обработки
    i_idle_ma: float = 0.003           # ток в простое, узел включён


# Ориентировочные профили; замените измерениями своей платы
MCU_PRESETS = {
    "nRF52840":  McuConfig("nRF52840 (RAK4631)", 0.004, 0.002, 8, 3.3, 0.003),       # 64 МГц, System ON idle
    "ESP32-S3":  McuConfig("ESP32-S3 (Heltec V3)", 0.002, 0.001, 16, 45.0, 0.8),     # 240 МГц, light sleep
    "slow_mcu":  McuConfig("медленный MCU", 0.020, 0.010, 4, 5.0, 0.01),             # для стресс-проверки
}


@dataclass
class NodeConfig:
    """⚙️ Логика и ограничения узла."""
    # Микроконтроллер (допущение 4)
    mcu: McuConfig = field(default_factory=McuConfig)

    # Ограничение 1: энергия
    battery_j: float = float("inf")    # запас энергии, Дж (inf = без ограничения)

    # Ограничение 2: память
    queue_capacity: int = 16           # очередь на передачу, пакетов
    seen_cache_capacity: int = 64      # кэш ID виденных пакетов (LRU)

    # Ограничение 3: эфирное время
    duty_cycle_limit: float = 0.10     # доля времени в передаче за окно
    duty_cycle_window_s: float = 60.0

    # Доступ к каналу
    csma: bool = True
    csma_backoff_s: tuple = (0.01, 0.10)
    csma_max_attempts: int = 8
    flood_jitter_s: tuple = (0.0, 0.20)   # задержка перед ретрансляцией при затоплении

    # Надёжная адресная передача
    max_retries: int = 3
    ack_guard_s: float = 0.03

    # 3*. Режим сна (по умолчанию выключен)
    sleep_enabled: bool = False
    sleep_period_s: float = 10.0
    awake_fraction: float = 0.5

    # Размеры кадров, байт
    header_bytes: int = 12             # адреса, ID пакета, HopLimit, тип
    route_bytes_per_hop: int = 1       # маршрут в заголовке (для адресной передачи)
    ack_bytes: int = 6


class S:
    """Состояния узла."""
    RX, TX, SLEEP, OFF, DEAD = "RX", "TX", "SLEEP", "OFF", "DEAD"


@dataclass
class Frame:
    kind: str                         # "DATA" или "ACK"
    pid: int                          # ID пакета (сквозной)
    src: int                          # источник
    dst: int                          # получатель
    hop_limit: int
    link_src: Optional[int] = None    # кто передаёт этот кадр
    link_dst: Optional[int] = None    # кому адресован (None = широковещательно)
    route: Optional[list] = None      # маршрут для адресной передачи
    idx: int = 0                      # позиция передающего узла в маршруте
    size: int = 0                     # длина кадра, байт
    hops: int = 0                     # сколько переходов уже пройдено
    ctrl: Optional[dict] = None       # служебные поля AODV (RREQ, RREP, RERR, HELLO)


class Node:
    """Узел сети: состояние, учёт энергии и проверка ограничений.
    Решения о маршрутизации принимает симулятор (раздел 8), узел хранит данные."""

    def __init__(self, nid, cfg: NodeConfig, radio: RadioConfig):
        self.id, self.cfg, self.radio = nid, cfg, radio
        self.state, self.state_since = S.RX, 0.0
        self.energy_j = 0.0
        self.time_in = Counter()
        self.queue = deque()             # ограничение 2: очередь
        self.seen = OrderedDict()        # ограничение 2: кэш ID
        self.tx_log = deque()            # ограничение 3: (начало, длительность)
        self.incoming = {}               # tx_id -> "ok" | "collision" | "halfduplex" | "not_listening"
        self.busy = False                # передаёт, ждёт ACK или выжидает паузу
        self.current = None              # кадр, ожидающий ACK
        self.ack_wait_id = None
        self.retries = 0
        self.csma_attempts = 0
        self.awake = True
        self.epoch = 0                   # растёт при выключении: старые события игнорируются
        self.airtime_s = 0.0
        self.tx_count = 0
        self.t_death = None
        self.mcu_busy_until = 0.0        # MCU свободен с этого момента
        self.mcu_pending = 0             # задач в очереди MCU
        self.mcu_active_s = 0.0          # суммарное время работы MCU

    @property
    def alive(self):
        return self.state not in (S.OFF, S.DEAD)

    @property
    def can_receive(self):
        return self.state == S.RX

    # Энергия (ограничение 1)
    def _current_ma(self, st):
        return {S.RX: self.radio.i_rx_ma, S.TX: self.radio.i_tx_ma,
                S.SLEEP: self.radio.i_sleep_ma}.get(st, 0.0)

    def set_state(self, new, t):
        dt = t - self.state_since
        self.time_in[self.state] += dt
        self.energy_j += self.radio.voltage_v * self._current_ma(self.state) / 1000 * dt
        self.state, self.state_since = new, t

    def alive_time(self, t):
        base = sum(v for k, v in self.time_in.items() if k in (S.RX, S.TX, S.SLEEP))
        return base + (t - self.state_since if self.alive else 0.0)

    def mcu_energy_j(self, t):
        m = self.cfg.mcu
        idle = max(self.alive_time(t) - self.mcu_active_s, 0.0)
        return self.radio.voltage_v * (m.i_active_ma * self.mcu_active_s + m.i_idle_ma * idle) / 1000

    def total_energy_j(self, t):
        return self.energy_j + self.mcu_energy_j(t)

    def battery_empty(self, t):
        return self.total_energy_j(t) >= self.cfg.battery_j

    # Память (ограничение 2)
    def mark_seen(self, pid) -> bool:
        """True, если пакет новый."""
        if pid in self.seen:
            self.seen.move_to_end(pid)
            return False
        self.seen[pid] = True
        if len(self.seen) > self.cfg.seen_cache_capacity:
            self.seen.popitem(last=False)
        return True

    def enqueue(self, frame) -> bool:
        if len(self.queue) >= self.cfg.queue_capacity:
            return False
        self.queue.append(frame)
        return True

    # Эфирное время (ограничение 3)
    def dc_wait(self, t, dur) -> float:
        """Сколько ждать, чтобы передача длительностью dur уложилась в лимит."""
        W = self.cfg.duty_cycle_window_s
        budget = self.cfg.duty_cycle_limit * W
        while self.tx_log and self.tx_log[0][0] + self.tx_log[0][1] <= t - W:
            self.tx_log.popleft()
        used = sum(min(d, s + d - (t - W)) for s, d in self.tx_log)
        if used + dur <= budget or not self.tx_log:
            return 0.0
        s, d = self.tx_log[0]
        return max(s + d + W - t, 1e-3)

    def reset_volatile(self):
        """Выключение: энергозависимая память стирается."""
        self.queue.clear(); self.seen.clear(); self.incoming.clear()
        self.busy = False; self.current = None; self.ack_wait_id = None
        self.retries = 0; self.csma_attempts = 0
        self.mcu_pending = 0


@dataclass
class ChannelConfig:
    """⚙️ Канал."""
    p_max: float = 0.99      # вероятность приёма вблизи
    p_min: float = 0.70      # вероятность приёма на границе R
    d0_frac: float = 0.5     # до какой доли R качество максимально


def link_pdr(d, R, ch: ChannelConfig) -> float:
    x = d / R
    if x <= ch.d0_frac:
        return ch.p_max
    if x >= 1:
        return ch.p_min
    f = (x - ch.d0_frac) / (1 - ch.d0_frac)
    return ch.p_max - (ch.p_max - ch.p_min) * f * f


def etx(d, R, ch: ChannelConfig) -> float:
    p = link_pdr(d, R, ch)
    return 1.0 / (p * p)


INF = float("inf")


def dijkstra(g, s, t):
    """g: {u: [(v, cost), ...]}. Возвращает (путь, стоимость) или (None, inf)."""
    dist, prev, done = {s: 0.0}, {}, set()
    pq = [(0.0, s)]
    while pq:
        du, u = heapq.heappop(pq)
        if u in done:
            continue
        done.add(u)
        if u == t:
            break
        for v, c in g.get(u, []):
            nd = du + c
            if nd < dist.get(v, INF):
                dist[v], prev[v] = nd, u
                heapq.heappush(pq, (nd, v))
    if t not in done:
        return None, INF
    path = [t]
    while path[-1] != s:
        path.append(prev[path[-1]])
    return path[::-1], dist[t]


def dp_hoplimit(g, s, t, H):
    """Кратчайший путь не длиннее H переходов.
    Возвращает (путь, стоимость, причина отказа или None)."""
    STAY = "stay"
    D, P = [{s: 0.0}], [{}]
    for _ in range(H):
        prev_layer = D[-1]
        cur = dict(prev_layer)
        par = {v: STAY for v in cur}
        for u, du in prev_layer.items():
            for v, c in g.get(u, []):
                if du + c < cur.get(v, INF):
                    cur[v], par[v] = du + c, u
        D.append(cur); P.append(par)
    if t not in D[H]:
        reachable, _ = dijkstra(g, s, t)
        return None, INF, ("hoplimit_insufficient" if reachable else "unreachable")
    path, h, v = [t], H, t
    while v != s:
        pv = P[h][v]
        h -= 1
        if pv == STAY:
            continue
        path.append(pv)
        v = pv
    return path[::-1], D[H][t], None


@dataclass
class AodvConfig:
    """⚙️ Параметры AODV (RFC 3561). Времена пересчитаны под LoRa."""
    # Поиск маршрута (RREQ / RREP)
    node_traversal_s: float = 0.4          # NODE_TRAVERSAL_TIME: оценка времени на переход (RFC: 40 мс для Wi-Fi)
    expanding_ring: bool = True            # поиск расширяющимся кольцом: TTL_START, +TTL_INCREMENT … TTL_THRESHOLD
    ttl_start: int = 1
    ttl_increment: int = 2
    ttl_threshold: int = 7
    timeout_buffer: int = 2
    ring_from_known_hops: bool = False     # RFC 6.4: кольцо начинается с известного числа переходов + TTL_INCREMENT
    rreq_retries: int = 2                  # RREQ_RETRIES: повторов поиска с полным TTL
    rreq_backoff: bool = True              # двоичная экспоненциальная задержка между повторами
    intermediate_reply: bool = True        # узел со свежим маршрутом отвечает на RREQ сам
    # Маршруты
    active_route_timeout_s: float = 3.0    # ACTIVE_ROUTE_TIMEOUT: сколько живёт неиспользуемый маршрут
    metric: str = "hops"                   # "hops" (RFC) | "etx" — стоимость с учётом качества каналов
    etx_delay_s: float = 0.0               # доп. задержка ретрансляции RREQ на единицу (ETX − 1) входящего канала
    rreq_suppress_dups: Optional[int] = None   # не ретранслировать RREQ, если за время ожидания услышано столько копий
    rreq_jitter_s: Optional[tuple] = None  # случайная задержка ретрансляции RREQ (None — как flood_jitter_s узла)
    rrep_delay_s: float = 0.0              # RREP отправляется с задержкой: волна RREQ успевает утихнуть,
                                           # а получатель за это время выбирает лучшую из копий RREQ
    flush_gap_s: float = 0.0               # интервал между пакетами, дождавшимися маршрута (0 — пачкой, как в RFC)
    # Обрыв канала
    local_repair: bool = False             # узел с оборванным каналом сам ищет новый путь, а не теряет пакет
    retry_backoff_s: Optional[float] = None    # пауза перед повтором растёт: b, 2b, 4b… (None — как у всех методов)
    extra_retries_if_heard: int = 0        # доп. повторы, если соседа недавно слышали: скорее коллизия, чем уход
    heard_window_s: float = 3.0
    # Гибрид (см. 2_hybrid_aodv.ipynb): «храни и неси» и первый пакет внутри RREQ
    carry: bool = False                    # поиск не нашёл путь — пакеты не теряются, а ждут у узла до срока
    carry_new_neighbor_s: float = 10.0     # услышали соседа, которого не было столько секунд, — ищем путь заново
    carry_min_gap_s: float = 2.0           # не чаще одного поиска к одному получателю за это время
    carry_poll_s: Optional[float] = None   # дополнительно повторять поиск раз в столько секунд (None — нет)
    piggyback: bool = False                # первый ждущий пакет едет внутри RREQ вместе с поиском
    # Исследование 3: адаптация к загрузке канала
    load_adaptive: bool = False            # узел измеряет занятость канала и при перегрузке экономит эфир
    busy_window_s: float = 10.0            # окно измерения занятости канала, с
    busy_threshold: float = 0.3            # «перегрузка» — канал занят дольше этой доли окна
    load_no_piggyback: bool = True         # при перегрузке не класть данные в RREQ
    load_supp_dups: Optional[int] = None   # при перегрузке не пересылать RREQ, если уже услышано столько копий
    dc_aware_rreq: Optional[float] = None  # узел израсходовал эту долю своего лимита эфира — не пересылает RREQ,
    dc_aware_min_dups: int = 1             #   если уже услышал столько копий (запрос и так идёт дальше)
    # Исследование 4: надёжный RREQ
    rreq_passive_ack: bool = False         # не услышал пересылку своего RREQ дальше и RREP — повторить RREQ
    rreq_pack_timeout_s: float = 0.8       # сколько ждать пересылку после конца своей передачи, с
    rreq_pack_retries: int = 1             # сколько раз повторять
    rreq_pack_selective: bool = False      # повторять, только если промолчал кто-то из недавно слышанных соседей
    rreq_pack_neighbor_s: float = 30.0     # «недавно слышанный» сосед — за последние столько секунд
    rreq_pack_max_degree: Optional[int] = None  # повторять, только если у узла не больше стольких соседей (цепочка, мост)
    # Исследование 5: идеи из DSR
    multipath_k: int = 1                   # хранить до k путей к получателю (как AOMDV): обрыв — переход на запасной
    multipath_extra_hops: int = 1          # запасной путь не длиннее основного больше чем на столько переходов
    overhear_rrep: bool = False            # запоминать маршрут из чужого RREP, услышанного в эфире
    overhear_data: bool = False            # чужой DATA через соседа продлевает наш маршрут к тому же получателю
    overhear_max_etx: Optional[float] = None   # подслушивать только у соседа с хорошим каналом (ETX не больше)
    overhear_no_ireply: bool = False       # по подслушанному маршруту не отвечать на чужие RREQ
    # HELLO
    hello_interval_s: Optional[float] = None   # None — без HELLO, обрыв определяется по отсутствию ACK
    allowed_hello_loss: int = 2
    # Память и сроки
    pending_capacity: int = 8              # буфер пакетов, ждущих маршрут
    rreq_cache_capacity: int = 64          # кэш (источник, ID) виденных RREQ
    route_table_capacity: int = 32         # таблица маршрутов, записей
    deadline_s: Optional[float] = None     # пакеты старше этого выбрасываются из очередей (None — нет)
    seq_flash_block: int = 1024            # номер последовательности резервируется в ПЗУ блоками
    # Размеры служебных кадров, байт (сверх общего заголовка header_bytes)
    rreq_bytes: int = 16                   # rreq_id 2, orig 2, orig_seq 4, dst 2, dst_seq 4, hops+flags 1, cost 1
    rrep_bytes: int = 12                   # dst 2, dst_seq 4, orig 2, hops 1, cost 1, lifetime 2
    rerr_bytes_base: int = 1
    rerr_bytes_per_dst: int = 6
    hello_bytes: int = 12


# ⚙️ Готовые варианты. Ключ используется как имя метода в run_matrix
AODV_PRESETS = {
    # RFC 3561 как есть; меняется только NODE_TRAVERSAL_TIME — под медленный эфир LoRa
    "aodv_rfc": AodvConfig(),
    # RFC + HELLO раз в секунду: так AODV определяет соседей без подтверждений канального уровня
    "aodv_rfc_hello": AodvConfig(hello_interval_s=1.0),
    # Адаптация под LoRa и подвижную сеть: 4 доработки, каждая значимо помогает (раздел 10.4)
    "aodv_lora": AodvConfig(local_repair=True,                            # пакет ждёт новый путь у узла обрыва
                            retry_backoff_s=0.2, extra_retries_if_heard=3,   # не путать коллизию с уходом соседа
                            active_route_timeout_s=10.0,                  # маршрут живёт дольше, чем в RFC
                            deadline_s=20.0),                             # не тратить эфир на опоздавшие пакеты
}


R_DEFAULT = 600.0


class Topology:
    kind = "static"

    def __init__(self, name, nodes, R):
        self.name, self.nodes, self.R = name, list(nodes), R

    def positions(self, t):
        raise NotImplementedError

    def links(self, t, alive):
        """{узел: [(сосед, расстояние), ...]} среди живых узлов в момент t."""
        raise NotImplementedError


class GeometricTopology(Topology):
    """Канал есть, если расстояние ≤ R."""

    def __init__(self, name, pos, R):
        super().__init__(name, pos.keys(), R)
        self.pos = dict(pos)

    def positions(self, t):
        return self.pos

    def links(self, t, alive):
        P = self.positions(t)
        ids = [n for n in self.nodes if n in alive]
        out = {n: [] for n in ids}
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                d = math.dist(P[a], P[b])
                if d <= self.R:
                    out[a].append((b, d)); out[b].append((a, d))
        return out


class ExplicitTopology(Topology):
    """Явный список рёбер; координаты нужны для расстояний и рисунка."""

    def __init__(self, name, pos, edges, R):
        super().__init__(name, pos.keys(), R)
        self.pos, self.edges = dict(pos), list(edges)

    def positions(self, t):
        return self.pos

    def links(self, t, alive):
        out = {n: [] for n in self.nodes if n in alive}
        for a, b in self.edges:
            if a in alive and b in alive:
                d = math.dist(self.pos[a], self.pos[b])
                out[a].append((b, d)); out[b].append((a, d))
        return out


class RandomWaypointTopology(GeometricTopology):
    """Подвижная сеть: Random Waypoint в квадрате area × area."""
    kind = "mobile"

    def __init__(self, name, n, area, R, v_range, pause_range, sim_time, rng):
        self.area, self.v_range, self.pause_range = area, v_range, pause_range
        start = {i: (rng.uniform(0, area), rng.uniform(0, area)) for i in range(n)}
        super().__init__(name, start, R)
        self.legs = {}
        for i in range(n):
            t, p, legs = 0.0, start[i], []
            while t < sim_time:
                q = (rng.uniform(0, area), rng.uniform(0, area))
                v = rng.uniform(*v_range)
                dt = math.dist(p, q) / v
                legs.append((t, t + dt, p, q)); t += dt
                pause = rng.uniform(*pause_range)
                legs.append((t, t + pause, q, q)); t += pause
                p = q
            self.legs[i] = (legs, [lg[0] for lg in legs])
        self._cache_t, self._cache = None, None

    def positions(self, t):
        if t == self._cache_t:
            return self._cache
        out = {}
        for i, (legs, starts) in self.legs.items():
            k = max(bisect.bisect_right(starts, t) - 1, 0)
            t0, t1, p, q = legs[k]
            f = 0.0 if t1 <= t0 else min(max((t - t0) / (t1 - t0), 0.0), 1.0)
            out[i] = (p[0] + (q[0] - p[0]) * f, p[1] + (q[1] - p[1]) * f)
        self._cache_t, self._cache = t, out
        return out


def _connected(topo):
    L = topo.links(0.0, set(topo.nodes))
    seen, stack = {topo.nodes[0]}, [topo.nodes[0]]
    while stack:
        for v, _ in L[stack.pop()]:
            if v not in seen:
                seen.add(v); stack.append(v)
    return len(seen) == len(topo.nodes)


# Конструкторы
def topo_board6(rng=None, R=750.0):
    pos = {1: (0, 0), 2: (400, 80), 3: (800, 160), 4: (400, -400), 5: (400, 600), 6: (800, 600)}
    edges = [(1, 2), (2, 3), (2, 5), (5, 6), (6, 3), (1, 4), (2, 4), (3, 4)]
    return ExplicitTopology("board6", pos, edges, R)

def topo_line(rng=None, n=10, R=R_DEFAULT, step=0.8):
    return GeometricTopology(f"line{n}", {i: (i * step * R, 0.0) for i in range(n)}, R)

def topo_ring(rng=None, n=12, R=R_DEFAULT, step=0.8):
    r = step * R / (2 * math.sin(math.pi / n))
    pos = {i: (r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n)) for i in range(n)}
    return GeometricTopology(f"ring{n}", pos, R)

def topo_grid(rng=None, rows=4, cols=4, R=R_DEFAULT, step=0.8):
    pos = {r * cols + c: (c * step * R, r * step * R) for r in range(rows) for c in range(cols)}
    return GeometricTopology(f"grid{rows}x{cols}", pos, R)

def topo_tree(rng=None, depth=4, R=R_DEFAULT):
    n = 2 ** depth - 1
    pos, edges = {}, []
    for i in range(n):
        lvl = int(math.log2(i + 1)); k = i + 1 - 2 ** lvl
        pos[i] = ((k + 0.5) * 4 * R / 2 ** lvl, -lvl * 0.6 * R)
        if i > 0:
            edges.append(((i - 1) // 2, i))
    return ExplicitTopology(f"tree{n}", pos, edges, R)

def topo_random_mesh(rng, n=30, area=2500.0, R=R_DEFAULT):
    for _ in range(1000):
        pos = {i: (rng.uniform(0, area), rng.uniform(0, area)) for i in range(n)}
        topo = GeometricTopology(f"mesh{n}", pos, R)
        if _connected(topo):
            return topo
    raise RuntimeError("не удалось сгенерировать связную сеть — увеличьте R или плотность")

def topo_rwp(rng, n=30, area=2500.0, R=R_DEFAULT, v_range=(0.5, 1.5), pause_range=(0, 60),
             sim_time=600.0, name="rwp"):
    return RandomWaypointTopology(name, n, area, R, v_range, pause_range, sim_time, rng)


# ⚙️ Каталог топологий: ключ -> (конструктор, поток по умолчанию или None = случайные пары)
TOPOLOGIES = {
    "board6":        (topo_board6,      [(1, 6)]),
    "line10":        (topo_line,        [(0, 6)]),
    "tree15":        (topo_tree,        [(7, 14)]),
    "ring12":        (topo_ring,        [(0, 6)]),
    "grid4x4":       (topo_grid,        [(0, 15)]),
    "mesh30":        (topo_random_mesh, None),
    "rwp30_walk":    (lambda rng, sim_time=600.0: topo_rwp(rng, v_range=(0.5, 1.5), pause_range=(0, 60),
                                                           sim_time=sim_time, name="rwp30_walk"), None),
    "rwp30_vehicle": (lambda rng, sim_time=600.0: topo_rwp(rng, v_range=(8, 15), pause_range=(0, 10),
                                                           sim_time=sim_time, name="rwp30_vehicle"), None),
    "rwp30_drone":   (lambda rng, sim_time=600.0: topo_rwp(rng, v_range=(15, 25), pause_range=(0, 5),
                                                           sim_time=sim_time, name="rwp30_drone"), None),
}

def build_topology(key, rng, sim_time, **kw):
    factory, _ = TOPOLOGIES[key]
    try:
        return factory(rng, sim_time=sim_time, **kw)
    except TypeError:
        return factory(rng, **kw)


def draw_topology(topo, t=0.0, alive=None, path=None, ax=None, title=None, labels=True):
    alive = set(topo.nodes) if alive is None else alive
    P = topo.positions(t)
    L = topo.links(t, alive)
    ax = ax or plt.gca()
    for a, lst in L.items():
        for b, d in lst:
            if a < b:
                ax.plot([P[a][0], P[b][0]], [P[a][1], P[b][1]], color="#bbb", lw=1, zorder=1)
    if path:
        for a, b in zip(path, path[1:]):
            ax.plot([P[a][0], P[b][0]], [P[a][1], P[b][1]], color="#e8590c", lw=3, zorder=2)
    for n in topo.nodes:
        on = n in alive
        ax.scatter(*P[n], s=180 if labels else 40, zorder=3,
                   color="#1c7ed6" if on else "white", edgecolor="#1c7ed6" if on else "#e03131", lw=1.5)
        if not on:
            ax.scatter(*P[n], marker="x", color="#e03131", s=80, zorder=4)
        if labels:
            ax.text(*P[n], str(n), ha="center", va="center", fontsize=8,
                    color="white" if on else "#e03131", zorder=5)
    ax.set_aspect("equal"); ax.set_xticks([]); ax.set_yticks([])
    xs, ys = [p[0] for p in P.values()], [p[1] for p in P.values()]
    span = max(max(xs) - min(xs), max(ys) - min(ys))
    if max(ys) - min(ys) < 0.2 * span:                # вырожденная (линейная) раскладка
        cy = (max(ys) + min(ys)) / 2
        ax.set_ylim(cy - 0.25 * span, cy + 0.25 * span)
    ax.set_title(title or f"{topo.name}, t = {t:.0f} с", fontsize=10)
    return ax


# ⚙️ Наш кейс: до 20 подвижных узлов. Площадь 2000 × 2000 м даёт ту же плотность, что 30 узлов на 2500 × 2500 м
_RWP20 = {"walk": ((0.5, 1.5), (0, 60)), "vehicle": ((8, 15), (0, 10)), "drone": ((15, 25), (0, 5))}
for _k, (_v, _p) in _RWP20.items():
    TOPOLOGIES[f"rwp20_{_k}"] = (
        lambda rng, sim_time=600.0, n=20, area=2000.0, _v=_v, _p=_p, _name=f"rwp20_{_k}":
            topo_rwp(rng, n=n, area=area, v_range=_v, pause_range=_p, sim_time=sim_time, name=_name),
        None)


@dataclass
class ChurnConfig:
    """⚙️ Пропадание и появление узлов."""
    scheduled: list = field(default_factory=list)   # [(узел, t_выкл, t_вкл или None)]
    random_nodes: object = None                      # None | k | [узлы] | "all"
    mtbf_s: float = 120.0                            # среднее время работы
    mttr_s: float = 30.0                             # среднее время отсутствия
    protect: tuple = ()                              # не пропадают случайно
    start_s: float = 0.0


def churn_events(ch: ChurnConfig, nodes, sim_time, rng):
    """Список событий (t, узел, "off" | "on")."""
    ev = []
    for n, t_off, t_on in ch.scheduled:
        ev.append((t_off, n, "off"))
        if t_on is not None:
            ev.append((t_on, n, "on"))
    pool = [n for n in nodes if n not in ch.protect]
    if ch.random_nodes is None:
        chosen = []
    elif ch.random_nodes == "all":
        chosen = pool
    elif isinstance(ch.random_nodes, int):
        chosen = rng.sample(pool, min(ch.random_nodes, len(pool)))
    else:
        chosen = [n for n in ch.random_nodes if n in pool]
    for n in chosen:
        t = ch.start_s + rng.expovariate(1 / ch.mtbf_s)
        while t < sim_time:
            ev.append((t, n, "off"))
            t += rng.expovariate(1 / ch.mttr_s)
            if t >= sim_time:
                break
            ev.append((t, n, "on"))
            t += rng.expovariate(1 / ch.mtbf_s)
    return sorted(ev)


def alive_at(events, nodes, t):
    alive = set(nodes)
    for te, n, kind in events:
        if te > t:
            break
        (alive.discard if kind == "off" else alive.add)(n)
    return alive


@dataclass
class TrafficConfig:
    flows: Optional[list] = "default"     # "default" | [(src, dst)] | None (случайные пары)
    rate_pps: float = 0.2
    start_s: float = 5.0
    stop_margin_s: float = 30.0


@dataclass
class Scenario:
    """⚙️ Сценарий эксперимента."""
    name: str
    topology: str                          # ключ из TOPOLOGIES
    sim_time_s: float = 600.0
    hop_limit: int = 7
    payload_bytes: int = 20
    traffic: TrafficConfig = field(default_factory=TrafficConfig)
    churn: ChurnConfig = field(default_factory=ChurnConfig)
    node_cfg: NodeConfig = field(default_factory=NodeConfig)
    radio: RadioConfig = field(default_factory=RadioConfig)
    channel: ChannelConfig = field(default_factory=ChannelConfig)
    topo_kwargs: dict = field(default_factory=dict)


METHODS = ("flooding", "dijkstra", "dp_hoplimit")


class Simulator:
    def __init__(self, sc: Scenario, method: str, seed: int):
        assert method in METHODS or method in AODV_PRESETS, method
        self.sc, self.method, self.seed = sc, method, seed
        self.rng = random.Random(seed)
        self.topo = build_topology(sc.topology, random.Random(seed * 7919 + 1), sc.sim_time_s, **sc.topo_kwargs)
        self.cfg, self.radio, self.ch = sc.node_cfg, sc.radio, sc.channel
        self.nodes = {n: Node(n, self.cfg, self.radio) for n in self.topo.nodes}
        self.t, self._q, self._seq = 0.0, [], itertools.count()
        self._tx_seq, self._pid_seq, self._ack_seq = itertools.count(), itertools.count(), itertools.count()
        self.active_tx, self.packets = {}, {}
        self.stats, self.air = Counter(), Counter()
        self._nbr_t, self._nbr = None, None
        self.data_toa_nominal = lora_toa(self.cfg.header_bytes + sc.payload_bytes
                                         + 4 * self.cfg.route_bytes_per_hop, self.radio)
        self.ack_toa = lora_toa(self.cfg.ack_bytes, self.radio)
        self.churn = churn_events(sc.churn, self.topo.nodes, sc.sim_time_s, random.Random(seed * 104729 + 7))

    # Очередь событий
    def at(self, t, fn, *args):
        heapq.heappush(self._q, (t, next(self._seq), fn, args))

    def run(self):
        self._schedule_traffic()
        for t, n, kind in self.churn:
            self.at(t, self._node_off if kind == "off" else self._node_on, n)
        if self.cfg.sleep_enabled:
            self._schedule_sleep()
        if math.isfinite(self.cfg.battery_j):
            self.at(1.0, self._energy_tick)
        T = self.sc.sim_time_s
        while self._q:
            t, _, fn, args = heapq.heappop(self._q)
            if t > T:
                break
            self.t = t
            fn(*args)
        self.t = T
        for nd in self.nodes.values():
            nd.set_state(nd.state, T)
        return self.summary()

    # Топология
    def alive_set(self):
        return {n for n, nd in self.nodes.items() if nd.alive}

    def _invalidate(self):
        self._nbr_t = None

    def neighbors(self, n):
        if self._nbr_t != self.t:
            self._nbr = self.topo.links(self.t, self.alive_set())
            self._nbr_t = self.t
        return self._nbr.get(n, [])

    def snapshot_graph(self):
        c0 = self.data_toa_nominal + self.cfg.mcu.t_rx_proc_s + self.cfg.mcu.t_tx_prep_s
        return {n: [(m, c0 * etx(d, self.topo.R, self.ch)) for m, d in lst]
                for n, lst in self.topo.links(self.t, self.alive_set()).items()}

    def _reachable(self, s, d):
        """Есть ли сейчас путь s → d (оракул, только для диагностики: потери из-за распада сети)."""
        return dijkstra(self.snapshot_graph(), s, d)[0] is not None

    # Трафик
    def _schedule_traffic(self):
        tr = self.sc.traffic
        flows = TOPOLOGIES[self.sc.topology][1] if tr.flows == "default" else tr.flows
        t_stop = self.sc.sim_time_s - tr.stop_margin_s
        streams = [(s, d) for s, d in flows] if flows else [(None, None)]
        for s, d in streams:
            t = tr.start_s + self.rng.expovariate(tr.rate_pps)
            while t < t_stop:
                # случайная пара выбирается заранее: у всех методов одинаковый трафик при одном seed
                self.at(t, self.generate, *((s, d) if s is not None else self.rng.sample(self.topo.nodes, 2)))
                t += self.rng.expovariate(tr.rate_pps)

    def generate(self, src, dst):
        if src is None:
            src, dst = self.rng.sample(self.topo.nodes, 2)
        node = self.nodes[src]
        if not node.alive:
            self.stats["gen_skipped_src_off"] += 1
            return
        pid = next(self._pid_seq)
        rec = dict(pid=pid, src=src, dst=dst, t_gen=self.t, t_del=None, hops=None,
                   reason=None, copy_reasons=Counter(), path_len=None, reachable=self._reachable(src, dst))
        self.packets[pid] = rec
        H = self.sc.hop_limit
        base = self.cfg.header_bytes + self.sc.payload_bytes
        if self.method == "flooding":
            fr = Frame("DATA", pid, src, dst, H, size=base)
        else:
            g = self.snapshot_graph()
            if self.method == "dijkstra":
                path, _ = dijkstra(g, src, dst)
                why = None if path else "unreachable"
            else:
                path, _, why = dp_hoplimit(g, src, dst, H)
            if path is None:
                rec["reason"] = why                       # отказ у источника, 0 передач
                return
            rec["path_len"] = len(path) - 1
            fr = Frame("DATA", pid, src, dst, H, link_dst=path[1], route=path, idx=0,
                       size=base + len(path) * self.cfg.route_bytes_per_hop)
        node.mark_seen(pid)
        self._enqueue_now(node, fr, node.epoch)

    # Микроконтроллер: задачи выполняются по одной
    def _mcu_task(self, node, dur, fn, *args, force=False):
        """Поставить задачу MCU длительностью dur; fn(*args) — по завершении.
        False, если очередь MCU полна (force=True — для своих передач, всегда принимается)."""
        if not force and node.mcu_pending >= self.cfg.mcu.queue_capacity:
            self.stats["drop_mcu_overflow"] += 1
            return False
        start = max(self.t, node.mcu_busy_until)
        node.mcu_busy_until = start + dur
        node.mcu_active_s += dur
        node.mcu_pending += 1
        if start > self.t:
            self.stats["mcu_waits"] += 1
        self.at(start + dur, self._mcu_done, node, node.epoch, fn, args)
        return True

    def _mcu_done(self, node, epoch, fn, args):
        if node.epoch != epoch:
            return
        node.mcu_pending -= 1
        fn(*args)

    # Очередь и доступ к каналу
    def _enqueue_now(self, node, frame, epoch):
        if node.epoch != epoch or not node.alive:
            return
        if not node.enqueue(frame):
            self.stats["drop_queue_overflow"] += 1
            self._fail(frame.pid, "queue_overflow", definitive=frame.link_dst is not None)
            return
        self._kick(node)

    def _unbusy_kick(self, node, epoch):
        if node.epoch != epoch:
            return
        node.busy = False
        self._kick(node)

    def _kick(self, node):
        if node.busy or not node.queue or not node.alive or not node.awake or node.state != S.RX:
            return
        while node.queue and self._stale(node.queue[0]):  # срок доставки истёк: не тратим эфир
            self._fail(node.queue.popleft().pid, "deadline", definitive=True)
        if not node.queue:
            return
        frame = node.queue[0]
        dur = lora_toa(frame.size, self.radio)
        w = node.dc_wait(self.t, dur)                    # ограничение 3
        if w > 0:
            node.busy = True
            self.stats["duty_cycle_deferrals"] += 1
            self.at(self.t + w, self._unbusy_kick, node, node.epoch)
            return
        if self.cfg.csma and node.incoming and node.csma_attempts < self.cfg.csma_max_attempts:
            node.csma_attempts += 1
            node.busy = True
            self.stats["csma_backoffs"] += 1
            self.at(self.t + self.rng.uniform(*self.cfg.csma_backoff_s), self._unbusy_kick, node, node.epoch)
            return
        node.csma_attempts = 0
        node.queue.popleft()
        node.busy = True
        self._mcu_task(node, self.cfg.mcu.t_tx_prep_s, self._tx_prepared, node, frame, dur, node.epoch, force=True)

    def _tx_prepared(self, node, frame, dur, epoch):
        """MCU подготовил кадр: запускаем передачу, если радио свободно."""
        if node.epoch != epoch or not node.alive:
            return
        if node.state != S.RX:                           # радио занято (ACK) или узел уснул
            node.queue.appendleft(frame)
            node.busy = False
            return                                       # повторный запуск — по концу ACK или пробуждению
        self._start_tx(node, frame, dur)

    # Передача
    def _start_tx(self, node, frame, dur):
        frame = replace(frame, link_src=node.id)
        node.set_state(S.TX, self.t)
        for k in node.incoming:                          # полудуплекс
            node.incoming[k] = "halfduplex"
        txid = next(self._tx_seq)
        rcv = []
        for m, d in self.neighbors(node.id):
            r = self.nodes[m]
            if not r.can_receive:
                st = "not_listening"
            elif r.incoming:                             # коллизия: портятся все
                for k in r.incoming:
                    r.incoming[k] = "collision"
                st = "collision"
            else:
                st = "ok"
            r.incoming[txid] = st
            rcv.append((m, d))
        self.active_tx[txid] = dict(sender=node.id, frame=frame, rcv=rcv, aborted=False)
        node.tx_log.append((self.t, dur)); node.airtime_s += dur; node.tx_count += 1
        self.air[frame.kind] += dur
        self.stats["tx_" + frame.kind] += 1
        self.at(self.t + dur, self._end_tx, txid, node.epoch)

    def _end_tx(self, txid, epoch):
        tx = self.active_tx.pop(txid)
        node, frame = self.nodes[tx["sender"]], tx["frame"]
        if node.epoch == epoch and node.state == S.TX:
            node.set_state(S.RX if node.awake else S.SLEEP, self.t)
        for m, d in tx["rcv"]:
            r = self.nodes[m]
            st = r.incoming.pop(txid, None)
            if st is None:
                continue
            if tx["aborted"]:
                st = "aborted"
            if st != "ok" or not r.can_receive:
                self.stats["rx_fail_" + (st if st != "ok" else "not_listening")] += 1
                continue
            if self.rng.random() > link_pdr(d, self.topo.R, self.ch):
                self.stats["rx_fail_link_loss"] += 1
                continue
            if not self._mcu_task(r, self.cfg.mcu.t_rx_proc_s, self._on_frame, r, frame, r.epoch):
                if frame.kind == "DATA":
                    self._fail(frame.pid, "mcu_overflow", definitive=False)
        if node.epoch != epoch:
            return
        if frame.kind != "ACK" and frame.link_dst is not None:    # адресный кадр: ждём ACK
            node.current = frame
            node.ack_wait_id = next(self._ack_seq)
            m = self.cfg.mcu
            timeout = m.t_rx_proc_s + m.t_tx_prep_s + self.ack_toa + self.cfg.ack_guard_s
            self.at(self.t + timeout, self._ack_timeout, node, epoch, node.ack_wait_id)
        elif frame.kind != "ACK":                        # широковещательный кадр
            node.busy = False
            self._kick(node)
        else:                                            # закончили ACK
            self._kick(node)

    def _send_ack(self, r, data):
        """ACK вне очереди передачи и без CSMA, но с подготовкой на MCU."""
        self._mcu_task(r, self.cfg.mcu.t_tx_prep_s, self._send_ack_now, r, data, r.epoch, force=True)

    def _send_ack_now(self, r, data, epoch):
        if r.epoch != epoch or r.state != S.RX:
            self.stats["ack_skipped_busy_radio"] += 1
            return
        ack = Frame("ACK", data.pid, r.id, data.link_src, 1, link_dst=data.link_src, size=self.cfg.ack_bytes)
        self._start_tx(r, ack, self.ack_toa)

    def _ack_timeout(self, node, epoch, wid):
        if node.epoch != epoch or node.ack_wait_id != wid:
            return
        node.ack_wait_id = None
        fr = node.current
        if node.retries < self._retry_limit(node, fr):
            node.retries += 1
            self.stats["retransmissions"] += 1
            node.queue.appendleft(fr)
            self.at(self.t + self._retry_delay(node), self._unbusy_kick, node, epoch)
        else:
            node.retries, node.current, node.busy = 0, None, False
            self._on_link_fail(node, fr)
            self._kick(node)

    # Приём
    def _on_frame(self, r, frame, epoch):
        if r.epoch != epoch or not r.alive:
            return
        if frame.kind == "ACK":
            cur = r.current
            if (frame.link_dst == r.id and r.ack_wait_id is not None and cur is not None
                    and frame.pid == cur.pid and frame.link_src == cur.link_dst):
                r.ack_wait_id, r.current, r.retries, r.busy = None, None, 0, False
                self._kick(r)
            return
        self._on_data(r, frame)

    def _on_data(self, r, frame):
        if self.method == "flooding":
            if not r.mark_seen(frame.pid):
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
            return
        # адресная передача (dijkstra, dp_hoplimit)
        if frame.link_dst != r.id:
            return                                        # чужой кадр
        self._send_ack(r, frame)
        if not r.mark_seen(frame.pid):
            self.stats["duplicates"] += 1
            return
        if frame.dst == r.id:
            self._deliver(frame, r)
            return
        if frame.hop_limit <= 1:
            self._fail(frame.pid, "hoplimit_exceeded", definitive=True)   # эфир потрачен впустую
            return
        k = frame.idx + 1
        fwd = replace(frame, hop_limit=frame.hop_limit - 1, hops=frame.hops + 1,
                      idx=k, link_dst=frame.route[k + 1])
        self._enqueue_now(r, fwd, r.epoch)

    def _deliver(self, frame, r):
        rec = self.packets[frame.pid]
        if rec["t_del"] is None:
            rec["t_del"], rec["hops"] = self.t, frame.hops + 1

    def _fail(self, pid, reason, definitive):
        rec = self.packets.get(pid)
        if rec is None or rec["t_del"] is not None:
            return
        if definitive:
            rec["reason"] = rec["reason"] or reason
        else:
            rec["copy_reasons"][reason] += 1

    # Хуки для методов с собственным состоянием (AODV, раздел 4.1)
    def _stale(self, frame):
        """True — кадр устарел, отбросить из очереди не передавая."""
        return False

    def _retry_limit(self, node, fr):
        return self.cfg.max_retries

    def _retry_delay(self, node):
        return self.rng.uniform(*self.cfg.csma_backoff_s)

    def _on_link_fail(self, node, fr):
        """Адресный кадр не подтверждён после max_retries повторов."""
        self._fail(fr.pid, "link_broken", definitive=True)

    def _on_node_off(self, nd):
        pass

    # Динамика
    def _node_off(self, n):
        nd = self.nodes[n]
        if not nd.alive:
            return
        nd.set_state(S.OFF, self.t)
        nd.epoch += 1
        if nd.current is not None:
            self._fail(nd.current.pid, "node_off", definitive=True)
        for fr in nd.queue:
            self._fail(fr.pid, "node_off", definitive=fr.link_dst is not None)
        self._on_node_off(nd)
        nd.reset_volatile()
        nd.mcu_busy_until = self.t
        for tx in self.active_tx.values():
            if tx["sender"] == n:
                tx["aborted"] = True
        self.stats["node_off_events"] += 1
        self._invalidate()

    def _node_on(self, n):
        nd = self.nodes[n]
        if nd.state != S.OFF:
            return
        nd.set_state(S.RX if nd.awake else S.SLEEP, self.t)
        self._invalidate()

    def _energy_tick(self):
        for n, nd in self.nodes.items():
            if nd.alive:
                nd.set_state(nd.state, self.t)
                if nd.battery_empty(self.t):
                    self._node_off(n)
                    nd.state, nd.t_death = S.DEAD, self.t
                    self.stats["battery_deaths"] += 1
        self.at(self.t + 1.0, self._energy_tick)

    # 3*. Сон
    def _schedule_sleep(self):
        P, f = self.cfg.sleep_period_s, self.cfg.awake_fraction
        for n in self.nodes:
            phase = self.rng.uniform(0, P)
            k = 0
            while True:
                t_sleep = k * P - phase + f * P
                t_wake = (k + 1) * P - phase
                if t_sleep > self.sc.sim_time_s:
                    break
                if t_sleep >= 0:
                    self.at(t_sleep, self._sleep_toggle, n, False)
                if t_wake >= 0:
                    self.at(t_wake, self._sleep_toggle, n, True)
                k += 1

    def _sleep_toggle(self, n, awake):
        nd = self.nodes[n]
        nd.awake = awake
        if not nd.alive:
            return
        if not awake and nd.state == S.RX:
            for k in nd.incoming:
                nd.incoming[k] = "not_listening"
            nd.set_state(S.SLEEP, self.t)
        elif awake and nd.state == S.SLEEP:
            nd.set_state(S.RX, self.t)
            self._kick(nd)

    # Итоги
    def packets_df(self):
        rows = []
        for r in self.packets.values():
            if r["t_del"] is not None:
                outcome = "delivered"
            elif r["reason"]:
                outcome = r["reason"]
            elif r["copy_reasons"]:
                outcome = r["copy_reasons"].most_common(1)[0][0]
            else:
                outcome = "lost_in_channel"
            rows.append(dict(pid=r["pid"], src=r["src"], dst=r["dst"], t_gen=r["t_gen"],
                             latency_s=(r["t_del"] - r["t_gen"]) if r["t_del"] is not None else None,
                             hops=r["hops"], outcome=outcome, reachable=r.get("reachable")))
        return pd.DataFrame(rows)

    def summary(self):
        pk = self.packets_df()
        gen = len(pk)
        dl = pk[pk.outcome == "delivered"] if gen else pk
        air_total = sum(self.air.values())
        T = self.sc.sim_time_s
        out = dict(scenario=self.sc.name, topology=self.sc.topology, kind=self.topo.kind,
                   method=self.method, seed=self.seed, hop_limit=self.sc.hop_limit,
                   generated=gen, delivered=len(dl),
                   pdr=len(dl) / gen if gen else float("nan"),
                   pdr_20s=(dl.latency_s <= DEADLINE_S).sum() / gen if gen else float("nan"),
                   reachable_share=pk.reachable.mean() if gen else float("nan"),
                   latency_mean_s=dl.latency_s.mean() if len(dl) else float("nan"),
                   latency_p95_s=dl.latency_s.quantile(0.95) if len(dl) else float("nan"),
                   latency_max_s=dl.latency_s.max() if len(dl) else float("nan"),
                   airtime_total_s=air_total,
                   airtime_per_delivered_s=air_total / len(dl) if len(dl) else float("nan"),
                   tx_per_delivered=sum(v for k, v in self.stats.items() if k.startswith("tx_")) / len(dl) if len(dl) else float("nan"),
                   overhead_share=(air_total - self.air["DATA"]) / air_total if air_total else 0.0,
                   energy_total_j=sum(n.total_energy_j(T) for n in self.nodes.values()),
                   energy_radio_j=sum(n.energy_j for n in self.nodes.values()),
                   energy_mcu_j=sum(n.mcu_energy_j(T) for n in self.nodes.values()),
                   energy_max_node_j=max(n.total_energy_j(T) for n in self.nodes.values()),
                   mcu_util_max=max(n.mcu_active_s for n in self.nodes.values()) / T,
                   mcu_waits=self.stats["mcu_waits"],
                   max_node_duty=max(n.airtime_s for n in self.nodes.values()) / self.sc.sim_time_s,
                   battery_deaths=self.stats["battery_deaths"],
                   collisions_rx=self.stats["rx_fail_collision"],
                   retransmissions=self.stats["retransmissions"],
                   duty_cycle_deferrals=self.stats["duty_cycle_deferrals"])
        if gen:
            for reason, cnt in pk.outcome.value_counts().items():
                if reason != "delivered":
                    out["fail_" + reason] = cnt
        return out


def simulate(sc: Scenario, method: str, seed: int = 1):
    sim = Simulator(sc, method, seed)
    res = sim.run()
    return res, sim


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
    alts: list = field(default_factory=list)       # запасные пути (next, hops, cost, expire) с тем же seq (исследование 5)
    heard: bool = False                            # маршрут подслушан в чужом RREP (исследование 5)


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
        self.heard_air = deque()           # (начало, длительность) кадров в эфире вокруг узла (занятость канала)
        self.pack = {}                     # (источник, rreq_id) -> ждём пересылку нашего RREQ дальше
        self.rreq_heard = OrderedDict()    # (источник, rreq_id) -> соседи, от которых слышали этот RREQ
        self.mp_replied = OrderedDict()    # (источник, rreq_id) -> соседи, через которых получатель уже ответил
        self.rrep_fwd = OrderedDict()      # (получатель, источник, seq) уже пересланных RREP


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
    def _update_route(self, n, dst, nxt, hops, cost, seq, life, heard=False):
        """Правило RFC 3561, 6.2: свежее (больший seq) или при равном seq — короче/дешевле."""
        if dst == n:
            return
        st = self.aodv[n]
        rt = st.routes.get(dst)
        now = self.t
        active = rt is not None and rt.valid and rt.expire > now
        K = self.ac.multipath_k
        if (rt is None or seq > rt.seq
                or (seq == rt.seq and (not active or self._m(hops, cost) < self._m(rt.hops, rt.cost)))):
            pre = rt.precursors if rt is not None and active and rt.nxt == nxt else set()
            alts = []
            if K > 1 and active and seq == rt.seq:      # прежний основной путь становится запасным
                alts = [a for a in rt.alts if a[0] != nxt and a[3] > now]
                if rt.nxt != nxt:
                    alts.insert(0, (rt.nxt, rt.hops, rt.cost, rt.expire))
                alts = alts[:K - 1]
            st.routes[dst] = Route(nxt, hops, cost, seq, now + life, True, pre, alts, heard)
            if len(st.routes) > self.ac.route_table_capacity:   # вытесняем устаревшую запись
                victim = min(st.routes, key=lambda d: (st.routes[d].valid and st.routes[d].expire > now,
                                                        st.routes[d].expire))
                del st.routes[victim]
                self.stats["route_evictions"] += 1
            self.peak["routes"] = max(self.peak["routes"], len(st.routes))
            if dst in st.pending:
                self._flush(n, dst)
            return "new"
        elif active and rt.nxt == nxt:
            rt.expire = max(rt.expire, now + life)
            return "refresh"
        elif (K > 1 and active and seq == rt.seq and hops <= rt.hops + self.ac.multipath_extra_hops
              and not any(a[0] == nxt for a in rt.alts)):
            rt.alts = sorted(rt.alts + [(nxt, hops, cost, now + life)], key=lambda a: self._m(a[1], a[2]))[:K - 1]
            self.stats["alt_routes_added"] += 1
            return "alt"

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
        old = self.aodv[n].routes.get(dst)
        if ring and self.ac.ring_from_known_hops and old is not None:   # путь когда-то был: сразу на его длину
            ttl = min(old.hops + self.ac.ttl_increment, self.net_diam)
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
        if self.ac.piggyback and not (self._overloaded(n) and self.ac.load_no_piggyback):
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

    # Исследования 3–4: занятость канала и надёжный RREQ
    def _start_tx(self, node, frame, dur):
        super()._start_tx(node, frame, dur)
        if self.ac.load_adaptive:                    # кадр слышат сам узел и все соседи в радиусе R
            for m in [node.id] + [m for m, _ in self.neighbors(node.id)]:
                self.aodv[m].heard_air.append((self.t, dur))
        if self.ac.rreq_passive_ack and frame.kind == "RREQ" and frame.hop_limit > 1:
            st = self.aodv[node.id]
            key = (frame.src, frame.ctrl["rreq_id"])
            pk = st.pack.setdefault(key, dict(frame=frame, hops=frame.hops, tries=0))
            pk["token"] = pk.get("token", 0) + 1
            self.at(self.t + dur + self.ac.rreq_pack_timeout_s, self._pack_check, node, key, pk["token"], node.epoch)

    def _pack_check(self, node, key, token, epoch):
        st = self.aodv[node.id]
        pk = st.pack.get(key)
        if node.epoch != epoch or pk is None or pk["token"] != token:
            return
        if pk["tries"] >= self.ac.rreq_pack_retries:
            del st.pack[key]
            return
        known = {v for v, t in st.last_heard.items() if self.t - t <= self.ac.rreq_pack_neighbor_s} - {node.id}
        if self.ac.rreq_pack_max_degree is not None and len(known) > self.ac.rreq_pack_max_degree:
            del st.pack[key]                           # соседей много — запрос дойдёт и без повтора
            self.stats["rreq_pack_skipped"] += 1
            return
        if self.ac.rreq_pack_selective:                # повторяем, только если кто-то из знакомых соседей молчал
            if not known - st.rreq_heard.get(key, set()):
                del st.pack[key]
                self.stats["rreq_pack_skipped"] += 1
                return
        pk["tries"] += 1
        self.stats["rreq_pack_resends"] += 1
        self._enqueue_now(node, pk["frame"], epoch)

    def _busy(self, n):
        """Доля времени за окно, когда в эфире вокруг узла был кадр (по уровню сигнала, как CAD/RSSI)."""
        log, W = self.aodv[n].heard_air, self.ac.busy_window_s
        while log and log[0][0] + log[0][1] < self.t - W:
            log.popleft()
        return min(1.0, sum(min(d, s + d - (self.t - W)) for s, d in log) / W)

    def _duty_used(self, node):
        """Доля окна лимита эфира, которую узел уже занял своими передачами."""
        W = self.cfg.duty_cycle_window_s
        return sum(min(d, s + d - (self.t - W)) for s, d in node.tx_log if s + d > self.t - W) / W

    def _overloaded(self, n):
        return self.ac.load_adaptive and self._busy(n) > self.ac.busy_threshold

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
            if k == "RREP" and self.ac.overhear_rrep and frame.src != r.id:   # сосед u знает свежий путь к frame.src
                c, le = frame.ctrl, self._link_etx(r.id, u)
                if self.ac.overhear_max_etx is not None and le > self.ac.overhear_max_etx:
                    return                            # слабый канал: такой маршрут быстро порвётся
                if self._update_route(r.id, frame.src, u, frame.hops + 1, c["cost"] + le,
                                      c["dst_seq"], c["life"], heard=True) in ("new", "alt"):
                    self.stats["overheard_routes"] += 1
            elif k == "DATA" and self.ac.overhear_data and frame.dst != r.id:
                rt = self._route(r.id, frame.dst)
                if rt is not None and rt.nxt == u:    # сосед u сейчас реально доставляет к frame.dst
                    rt.expire = max(rt.expire, self.t + self.ac.active_route_timeout_s)
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
        pk = st.pack.get(key)
        if pk is not None and frame.hops > pk["hops"]:  # наш RREQ переслали дальше
            del st.pack[key]
        if self.ac.rreq_pack_selective:
            st.rreq_heard.setdefault(key, set()).add(u)
            if len(st.rreq_heard) > self.ac.rreq_cache_capacity:
                st.rreq_heard.popitem(last=False)
        if key in st.rreq_seen:                       # копия уже виденного запроса
            self.stats["rreq_duplicates"] += 1
            rep_set = st.mp_replied.get(key)
            if (rep_set is not None and r.id == frame.dst and u not in rep_set
                    and len(rep_set) < self.ac.multipath_k):  # запасной путь: ответить через другого соседа
                rep_set.add(u)
                self._update_route(r.id, orig, u, hops, cost, c["orig_seq"], self._rev_life(hops))
                self.stats["rrep_dst_extra"] += 1
                self._send_rrep(r, r.id, orig, 0, 0.0, st.seq, 2 * self.ac.active_route_timeout_s, via=u)
                return
            col = st.collect.get(key)
            if col is not None and self._m(hops, cost) < self._m(col["hops"], col["cost"]):
                col.update(u=u, hops=hops, cost=cost)
            elif key in st.rebroadcast:
                st.rebroadcast[key]["dups"] += 1
            return
        self._rreq_mark(st, key)
        if r.id == frame.dst and c.get("data") is not None:     # пакет приехал вместе с поиском
            if self.packets[c["data"].pid]["t_del"] is None:
                self.stats["delivered_in_rreq"] += 1
            self._deliver(replace(c["data"], hops=frame.hops), r)
        if r.id == frame.dst and self.ac.rrep_delay_s > 0:  # получатель ждёт другие копии
            st.collect[key] = dict(u=u, hops=hops, cost=cost, seq=c["orig_seq"], dst_seq=c["dst_seq"])
            self.at(self.t + self.ac.rrep_delay_s, self._dst_reply, r, key, orig, r.epoch)
            return
        self._update_route(r.id, orig, u, hops, cost, c["orig_seq"], self._rev_life(hops))   # обратный маршрут
        if r.id == frame.dst:
            if self.ac.multipath_k > 1:
                st.mp_replied[key] = {u}
                if len(st.mp_replied) > self.ac.rreq_cache_capacity:
                    st.mp_replied.popitem(last=False)
            self._reply_as_dst(r, orig, c["dst_seq"])
            return
        rt = self._route(r.id, frame.dst)
        if (self.ac.intermediate_reply and rt is not None and rt.nxt != u
                and not (rt.heard and self.ac.overhear_no_ireply)
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
        if (self.ac.load_supp_dups is not None and rb["dups"] >= self.ac.load_supp_dups
                and self._overloaded(r.id)):
            self.stats["rreq_suppressed_load"] += 1
            return
        if (self.ac.dc_aware_rreq is not None and rb["dups"] >= self.ac.dc_aware_min_dups
                and self._duty_used(r) > self.ac.dc_aware_rreq * self.cfg.duty_cycle_limit):
            self.stats["rreq_suppressed_dc"] += 1
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

    def _send_rrep(self, r, dst, orig, hops, cost, dst_seq, life, via=None):
        rev = self._route(r.id, orig)
        if rev is None and via is None:
            self.stats["rrep_no_reverse"] += 1
            return
        fr = Frame("RREP", self._cid(), dst, orig, self.net_diam, link_dst=via if via is not None else rev.nxt, hops=hops,
                   size=self.cfg.header_bytes + self.ac.rrep_bytes, ctrl=dict(dst_seq=dst_seq, cost=cost, life=life))
        self._enqueue_now(r, fr, r.epoch)

    def _on_rrep(self, r, frame, u):
        c = frame.ctrl
        hops, cost = frame.hops + 1, c["cost"] + self._link_etx(r.id, u)
        st = self.aodv[r.id]
        for key in [k for k in st.pack if k[0] == frame.dst]:   # ответ идёт — поиск дошёл до цели
            del st.pack[key]
        if frame.dst == r.id:                          # ответ на наш поиск: пакет из RREQ уже доставлен
            self.aodv[r.id].riding.pop(frame.src, None)
        res = self._update_route(r.id, frame.src, u, hops, cost, c["dst_seq"], c["life"])    # прямой маршрут
        if frame.dst == r.id:
            self.stats["rrep_received"] += 1
            return
        if self.ac.multipath_k > 1:                    # повторный RREP без нового пути дальше не шлём
            k2 = (frame.src, frame.dst, c["dst_seq"])
            if k2 in st.rrep_fwd and res not in ("new", "alt"):
                self.stats["rrep_dup_dropped"] += 1
                return
            st.rrep_fwd[k2] = True
            if len(st.rrep_fwd) > self.ac.rreq_cache_capacity:
                st.rrep_fwd.popitem(last=False)
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
            if rt.alts:
                rt.alts = [a for a in rt.alts if a[0] != v and a[3] > self.t]
            if rt.valid and rt.nxt == v:
                if self._use_alt(rt):
                    continue
                rt.valid, rt.seq, rt.expire = False, rt.seq + 1, self.t
                if rt.precursors:
                    unreach.append((dst, rt.seq))
        st.last_heard.pop(v, None)
        if unreach:
            self._send_rerr(n, unreach)

    def _use_alt(self, rt):
        """Основной путь оборвался — перейти на запасной (исследование 5)."""
        if not rt.alts:
            return False
        nxt, hops, cost, expire = rt.alts.pop(0)
        rt.nxt, rt.hops, rt.cost, rt.expire = nxt, hops, cost, max(expire, self.t + 1.0)
        self.stats["alt_switches"] += 1
        return True

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
            if rt is not None and rt.alts:
                rt.alts = [a for a in rt.alts if a[0] != u and a[3] > self.t]
            if rt is not None and rt.valid and rt.nxt == u:
                if self._use_alt(rt):
                    continue
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
                  "piggybacked", "parked", "carry_wakeups", "carry_retries", "delivered_in_rreq",
                  "rreq_suppressed_load", "rreq_suppressed_dc", "rreq_pack_resends", "rreq_pack_skipped",
                  "alt_routes_added", "alt_switches", "rrep_dst_extra", "rrep_dup_dropped", "overheard_routes"):
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


def run_matrix(scenarios, methods=METHODS, seeds=range(1, 6), verbose=True):
    rows = []
    for sc in scenarios:
        for m in methods:
            for s in seeds:
                res, _ = simulate(sc, m, s)
                rows.append(res)
        if verbose:
            print(f"готово: {sc.name}")
    return pd.DataFrame(rows).fillna({c: 0 for c in pd.DataFrame(rows).columns if c.startswith("fail_")})


def aggregate(df, by=("scenario", "method"),
              cols=("pdr", "airtime_per_delivered_s", "latency_mean_s", "tx_per_delivered", "overhead_share", "energy_total_j")):
    """Среднее ± стандартное отклонение по повторам."""
    g = df.groupby(list(by))[list(cols)]
    mean, std = g.mean(), g.std().fillna(0)
    out = mean.copy()
    for c in cols:
        out[c] = [f"{m:.3f} ± {s:.3f}" for m, s in zip(mean[c], std[c])]
    return out


def plot_compare(df, x="scenario", metrics=("pdr", "airtime_per_delivered_s", "latency_mean_s"), title=""):
    fig, axes = plt.subplots(1, len(metrics), figsize=(5 * len(metrics), 3.6))
    xs = list(dict.fromkeys(df[x]))
    methods = list(dict.fromkeys(df["method"]))
    w = 0.8 / len(methods)
    colors = METHOD_COLORS
    for ax, met in zip(axes, metrics):
        for i, m in enumerate(methods):
            sub = df[df.method == m].groupby(x)[met]
            mean, std = sub.mean().reindex(xs), sub.std().reindex(xs).fillna(0)
            pos = [j + (i - (len(methods) - 1) / 2) * w for j in range(len(xs))]
            ax.bar(pos, mean, w, yerr=std, capsize=3, label=m, color=colors.get(m))
        ax.set_xticks(range(len(xs))); ax.set_xticklabels(xs, rotation=20, ha="right", fontsize=8)
        ax.set_title(met, fontsize=10); ax.grid(axis="y", alpha=.3)
    axes[0].legend(fontsize=8)
    fig.suptitle(title); plt.tight_layout(); plt.show()


def plot_snapshots(sc: Scenario, seed=1, times=(0, 150, 300, 450)):
    sim = Simulator(sc, "flooding", seed)
    fig, axes = plt.subplots(1, len(times), figsize=(3.6 * len(times), 3.6))
    for ax, t in zip(axes, times):
        draw_topology(sim.topo, t=t, alive=alive_at(sim.churn, sim.topo.nodes, t), ax=ax,
                      labels=len(sim.topo.nodes) <= 16)
    plt.tight_layout(); plt.show()


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


# ⚙️ Исследование 3: гибрид с бюджетом эфира
AODV_PRESETS["hybrid_dc"] = replace(AODV_PRESETS["hybrid"],
                                    dc_aware_rreq=0.6,      # израсходовал 60 % лимита эфира — не пересылает чужие RREQ
                                    dc_aware_min_dups=0)    # даже если копий не слышал
METHOD_COLORS.update({"hybrid_dc": "#0b7285"})


# ⚙️ Исследование 4: надёжный RREQ
AODV_PRESETS["hybrid_plus"] = replace(AODV_PRESETS["hybrid_dc"],
                                      rreq_passive_ack=True,       # никто не переслал наш RREQ дальше — повторить
                                      rreq_pack_timeout_s=0.8,
                                      rreq_pack_retries=1,
                                      rreq_pack_max_degree=2)      # только у звеньев цепочек и мостов
METHOD_COLORS.update({"hybrid_plus": "#5f3dc4"})


# ⚙️ Исследование 5: идеи из DSR
AODV_PRESETS["hybrid_ovh"] = replace(AODV_PRESETS["hybrid_plus"],
                                     overhear_rrep=True,          # запоминать свежий маршрут из чужого RREP
                                     overhear_no_ireply=True)     # но не отвечать по нему на чужие RREQ
METHOD_COLORS.update({"hybrid_ovh": "#c2255c", "dsr": "#868e96"})


# EXP: общие функции экспериментов
import os
from dataclasses import replace as dc_replace

RESULTS_DIR = os.path.join("results", "1_simple_aodv")
RERUN = False          # True — пересчитать все эксперименты заново (≈ 40 мин на одном ядре); False — взять готовые CSV из RESULTS_DIR
MAIN_METHODS = ("flooding", "dijkstra", "aodv_rfc", "aodv_lora")
MOBILITY = {"rwp20_walk": "пешеходы", "rwp20_vehicle": "техника", "rwp20_drone": "дроны"}


def make_scenario(topo, pattern="random", rate=0.2, churn=False, sim_time=600.0, n=None, area=None, name=None):
    """Сценарий нашего кейса. pattern: random — случайные пары, sink — все шлют узлу 0 (координатору)."""
    kw = {k: v for k, v in dict(n=n, area=area).items() if v is not None}
    nodes = n or 20
    if pattern == "random":
        tr = TrafficConfig(flows=None, rate_pps=rate)
    elif pattern == "sink":
        tr = TrafficConfig(flows=[(i, 0) for i in range(1, nodes)], rate_pps=rate / (nodes - 1))
    else:
        tr = TrafficConfig(flows="default", rate_pps=rate)
    ch = ChurnConfig(random_nodes="all", mtbf_s=300, mttr_s=30) if churn else ChurnConfig()
    return Scenario(name or topo, topo, sim_time_s=sim_time, traffic=tr, churn=ch, topo_kwargs=kw)


def run_spec(spec):
    """Один прогон. spec: topo, method, seed + параметры make_scenario; aodv={...} — вариант AODV поверх base."""
    if "aodv" in spec:
        AODV_PRESETS[spec["method"]] = dc_replace(AODV_PRESETS[spec.get("base", "aodv_rfc")], **spec["aodv"])
    sc_kw = {k: spec[k] for k in ("pattern", "rate", "churn", "sim_time", "n", "area") if k in spec}
    res, _ = simulate(make_scenario(spec["topo"], **sc_kw), spec["method"], spec["seed"])
    res.update({k: v for k, v in spec.items() if k not in ("aodv", "base")})
    return res


def run_grid(name, specs):
    """Прогоняет список спецификаций или берёт сохранённый результат RESULTS_DIR/<name>.csv."""
    path = os.path.join(RESULTS_DIR, name + ".csv")
    if not RERUN and os.path.exists(path):
        return pd.read_csv(path)
    df = pd.DataFrame([run_spec(s) for s in specs])
    df = df.fillna({c: 0 for c in df.columns if c.startswith("fail_")})
    os.makedirs(RESULTS_DIR, exist_ok=True)
    df.to_csv(path, index=False)
    return df


def grid(methods, seeds, **axes):
    """Все сочетания: grid(["flooding"], range(1, 6), topo=[...], rate=[...])."""
    return [dict(zip(axes, combo), method=m, seed=s)
            for combo in itertools.product(*axes.values()) for m in methods for s in seeds]


def variants(names_to_overrides, seeds, base="aodv_rfc", **axes):
    """Варианты AODV: {имя: {параметр: значение}} поверх пресета base."""
    out = []
    for name, d in names_to_overrides.items():
        for sp in grid([name], seeds, **axes):
            out.append({**sp, "aodv": dict(d), "base": base})
    return out


def criteria_table(df, by=("topo", "method")):
    """Проверка требований подвижного случая (см. «Постановку»)."""
    g = df.groupby(list(by), sort=False)
    ci = 1.96 * g.pdr_20s.std() / g.pdr_20s.count() ** 0.5
    t = pd.DataFrame({
        "доставлено за 20 с": g.pdr_20s.mean(),
        "± 95 %": ci,
        "потери, %": 100 * (1 - g.pdr_20s.mean()),
        "из них распад сети, %": 100 * (1 - g.reachable_share.mean()),
        "задержка ср., с": g.latency_mean_s.mean(),
        "задержка p95, с": g.latency_p95_s.mean(),
        "эфир на пакет, с": g.airtime_per_delivered_s.mean(),
    }).round(3)
    lo, hi = t["доставлено за 20 с"] - ci, t["доставлено за 20 с"] + ci
    t["потери ≤ 10 %"] = ["✅" if l >= 1 - LOSS_MAX else ("❌" if h < 1 - LOSS_MAX else "≈ на границе")
                         for l, h in zip(lo, hi)]
    return t


def plot_lines(df, x, metric="pdr_20s", col="topo", hue="method", title="", xlabel=None, ylabel=None,
               target=None, logx=False):
    """Среднее ± ст. откл. по повторам: по оси x — параметр, линии — методы, панели — col."""
    cols = list(dict.fromkeys(df[col]))
    fig, axes = plt.subplots(1, len(cols), figsize=(4.6 * len(cols), 3.5), sharey=True, squeeze=False)
    for ax, cv in zip(axes[0], cols):
        sub = df[df[col] == cv]
        for h in dict.fromkeys(sub[hue]):
            s = sub[sub[hue] == h].groupby(x)[metric]
            m, sd = s.mean(), s.std().fillna(0)
            ax.errorbar(m.index, m.values, yerr=sd.values, marker="o", ms=4, capsize=3, label=h,
                        color=METHOD_COLORS.get(h))
        if target is not None:
            ax.axhline(target, color="#e03131", ls="--", lw=1)
        if logx:
            xs = sorted(set(sub[x]))
            ax.set_xscale("log"); ax.minorticks_off()
            ax.set_xticks(xs); ax.set_xticklabels([f"{v:g}" for v in xs])
        ax.set_title(MOBILITY.get(cv, cv), fontsize=10); ax.set_xlabel(xlabel or x); ax.grid(alpha=.3)
    axes[0][0].set_ylabel(ylabel or metric); axes[0][0].legend(fontsize=8)
    fig.suptitle(title); plt.tight_layout(); plt.show()


# ---------------------------------------------------------------------------------------------------------------------
def _parse_seeds(text):
    out = []
    for part in text.split(","):
        a, _, b = part.partition("-")
        out += list(range(int(a), int(b) + 1)) if b else [int(a)]
    return out


def _show_config(name):
    cfg, base = AODV_PRESETS[name], AodvConfig()
    print(f"{name}: отличия от AODV по RFC 3561 (AodvConfig по умолчанию)")
    for f in fields(AodvConfig):
        v, d = getattr(cfg, f.name), getattr(base, f.name)
        if v != d:
            print(f"  {f.name:24s} = {v!r:12}  (RFC: {d!r})")


def main():
    import argparse, sys
    if not sys.stdout.isatty():                  # вывод в канал или файл — всегда UTF-8
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="hybrid_plus и контрольные методы на сценариях исследования")
    p.add_argument("--methods", default="hybrid_plus",
                   help="через запятую: hybrid_ovh, hybrid_plus, hybrid_dc, hybrid, aodv_lora, aodv_rfc, flooding, flooding_x3, dijkstra")
    p.add_argument("--topo", default="rwp20_vehicle", help="rwp20_walk | rwp20_vehicle | rwp20_drone | line10 | grid4x4 | …")
    p.add_argument("--pattern", default="random", help="random (случайные пары) | sink (все → узел 0) | default (поток топологии)")
    p.add_argument("--rate", type=float, default=0.2, help="суммарный трафик, пакетов/с на всю сеть")
    p.add_argument("--churn", action="store_true", help="узлы пропадают: в среднем 300 с работают, 30 с отсутствуют")
    p.add_argument("--seeds", default="1-10", help="например 1-10 или 1,2,5")
    p.add_argument("--n", type=int, default=None, help="число узлов (для rwp20_*)")
    p.add_argument("--area", type=float, default=None, help="сторона квадрата, м (для rwp20_*)")
    p.add_argument("--config", action="store_true", help="показать параметры hybrid_plus и hybrid_ovh и выйти")
    a = p.parse_args()
    if a.config:
        _show_config("hybrid_plus")
        _show_config("hybrid_ovh")
        return
    rows = []
    for m in a.methods.split(","):
        for s in _parse_seeds(a.seeds):
            sc = make_scenario(a.topo, pattern=a.pattern, rate=a.rate, churn=a.churn, n=a.n, area=a.area)
            res, _ = simulate(sc, m.strip(), s)
            rows.append(res)
    df = pd.DataFrame(rows)
    g = df.groupby("method", sort=False)
    t = pd.DataFrame({"PDR за 20 с": g.pdr_20s.mean(), "± 95 %": 1.96 * g.pdr_20s.std() / g.pdr_20s.count() ** 0.5,
                      "путь существовал": g.reachable_share.mean(), "задержка ср., с": g.latency_mean_s.mean(),
                      "задержка p95, с": g.latency_p95_s.mean(), "эфир на пакет, с": g.airtime_per_delivered_s.mean()})
    print(f"{a.topo}, {a.pattern}, {a.rate} пак/с{', узлы пропадают' if a.churn else ''}, повторов: {len(_parse_seeds(a.seeds))}")
    print(t.round(3).to_string())


if __name__ == "__main__":
    main()
