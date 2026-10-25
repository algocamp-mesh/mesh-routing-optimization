# EXP: общие функции экспериментов
import os
from dataclasses import replace as dc_replace

RESULTS_DIR = "results"
RERUN = False          # True — пересчитать все эксперименты заново (≈ 40 мин на одном ядре); False — взять results/*.csv
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
    """Прогоняет список спецификаций или берёт сохранённый результат results/<name>.csv."""
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
