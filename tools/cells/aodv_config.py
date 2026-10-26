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
