# MARI — strategy_lab: آزمایشگاه آفلاین Walk-Forward نقطه‌لنگری + کنترل انتخاب
# MODE: READ ONLY | PAPER ONLY | NO LIVE ORDERS
#
# خاستگاه: بخش ۶–۸ گزارش EXECUTION ORDER 001 (2026-10-25).
# این ماژول هیچ سیم‌کشی‌ای به چرخهٔ زندهٔ ناوگان ندارد و هیچ شبکه‌ای باز نمی‌کند؛
# شبیه‌ساز یگانهٔ آن evaluator.simulate_trades است (بدون تغییر رفتار).
# هر خروجی فقط REPORTED یا INSUFFICIENT_EVIDENCE است — هیچ آستانه‌ای «موفقیت» جعل
# نمی‌شود. انتخاب پارامتر فقط از گذشتهٔ نقطه‌لنگری (anchored) هر فولد مجاز است.

import json
import math
import random
from statistics import NormalDist

from . import evaluator
from .sources import is_stale_series

Z95 = NormalDist().inv_cdf(0.975)
LAB_METHOD = "strategy_lab/anchored_wf_v1"


# ---------- ابزار آماری (خالص، قطعی) ----------

def wilson_ci(wins: int, n: int, z: float = Z95) -> "tuple | None":
    """بازهٔ اطمینان ویلسون نرخ برد — n=0 → None."""
    if not n:
        return None
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (round(centre - half, 4), round(centre + half, 4))


def bootstrap_avg_ci(nets: list, *, seed: int, n_boot: int = 2000,
                     lo: float = 0.025, hi: float = 0.975) -> "tuple | None":
    """بازهٔ bootstrap صدکی برای میانگین خالص — با بذر ثابت (قطعی)."""
    if not nets:
        return None
    rng = random.Random(seed)
    means = []
    for _ in range(n_boot):
        s = 0.0
        for _ in range(len(nets)):
            s += nets[rng.randrange(len(nets))]
        means.append(s / len(nets))
    means.sort()
    return (round(means[int(lo * len(means))], 6),
            round(means[int(hi * len(means))], 6))


def expected_max_sr(srs: list) -> "float | None":
    """DSR-lite (Bailey & López de Prado, JPM 2014): بیشینهٔ SR موردانتظار
    زیر N آزمایش مستقل با واریانس مشاهده‌شدهٔ SRها. ورودی کوتاه/ثابت → None.
    این «کنترل گزارش‌دهی» است، نه آزمون معناداری کامل."""
    n = len(srs)
    if n < 2:
        return None
    mean = sum(srs) / n
    var = sum((x - mean) ** 2 for x in srs) / (n - 1)
    if var <= 0:
        return None
    gamma = 0.5772155649  # ثابت اویلر–ماسکرونی
    nd = NormalDist()
    e_max = math.sqrt(var) * ((1 - gamma) * nd.inv_cdf(1 - 1.0 / n)
                              + gamma * nd.inv_cdf(1 - 1.0 / (n * math.e)))
    return round(e_max, 6)


def _fold_metrics(trades: list, *, seed: int, n_boot: int) -> dict:
    closed = [t for t in trades if t["exit_reason"] in ("TP", "SL")]
    nets = [t["net_pct"] for t in closed]
    wins = sum(1 for x in nets if x > 0)
    gw = sum(x for x in nets if x > 0)
    gl = abs(sum(x for x in nets if x < 0))
    return {
        "n": len(trades),
        "closed": len(closed),
        "open": len(trades) - len(closed),
        "wins": wins,
        "profit_factor": round(gw / gl, 6) if gl > 0
        else ("UNDEFINED_NO_LOSSES" if gw > 0 else None),
        "win_rate_pct": round(100 * wins / len(closed), 4) if closed else None,
        "win_rate_wilson95": wilson_ci(wins, len(closed)),
        "avg_net_pct": round(sum(nets) / len(nets), 6) if nets else None,
        "sum_net_pct": round(sum(nets), 6) if nets else None,
        "avg_net_bootstrap95": bootstrap_avg_ci(nets, seed=seed, n_boot=n_boot),
        "exit_mix": {
            "TP": sum(1 for t in closed if t["exit_reason"] == "TP"),
            "SL": sum(1 for t in closed if t["exit_reason"] == "SL"),
        },
    }


def _choose_params(candles_map: dict, events: list, grid: list,
                   *, fold_start_ms: int, interval_ms: int,
                   min_train_closed: int, seed: int, n_boot: int) -> dict:
    """انتخاب فقط از گذشتهٔ نقطه‌لنگری: کندل‌ها به پیش از شروع فولد بریده می‌شوند."""
    trials = []
    for g in grid:
        closed_n = 0
        gw = gl = 0.0
        for sym, candles in candles_map.items():
            train_candles = [c for c in candles
                             if c["open_time"] + interval_ms <= fold_start_ms]
            train_events = [e for e in events if e.get("symbol") == sym]
            trades = evaluator.simulate_trades(
                train_candles, train_events, symbol=sym,
                tp_pct=g.get("tp_pct", evaluator.TP_PCT),
                sl_pct=g.get("sl_pct", evaluator.SL_PCT),
                fee_pct=g.get("fee_pct", evaluator.FEE_PCT))
            for t in trades:
                if t["exit_reason"] in ("TP", "SL"):
                    closed_n += 1
                    if t["net_pct"] > 0:
                        gw += t["net_pct"]
                    elif t["net_pct"] < 0:
                        gl += abs(t["net_pct"])
        pf = round(gw / gl, 6) if gl > 0 else None
        trials.append({"params": g, "train_closed": closed_n,
                       "train_profit_factor": pf,
                       "qualifies": closed_n >= min_train_closed})
    ok = [t for t in trials if t["qualifies"] and
          isinstance(t["train_profit_factor"], float)]
    chosen = max(ok, key=lambda t: t["train_profit_factor"]) if ok else None
    srs_hint = [t["train_profit_factor"] for t in trials
                if isinstance(t["train_profit_factor"], float)]
    return {
        "chosen": chosen["params"] if chosen else None,
        "selection_basis": "max_train_pf_with_min_closed" if chosen
        else "NO_QUALIFIED_CANDIDATE",
        "trials": trials,
        "n_trials": len(trials),
        "train_pf_range": [min(srs_hint), max(srs_hint)] if srs_hint else None,
    }


def anchored_walk_forward(candles_map: dict, events: list, config: dict) -> dict:
    """آزمایشگاه آفلاین WF نقطه‌لنگری روی رویدادهای BOS.

    candles_map: {symbol: candles} — کندل بستهٔ ۱ساعته (قرارداد parse_klines).
    events: رویدادهای BOS با features.entry_index (قرارداد contract.make_message).
    config: folds[{name,start_ms,end_ms}] + grid[{tp_pct,sl_pct,fee_pct?}] +
            interval_ms + seed + n_bootstrap + min_train_closed + now_ms؟
    خروجی: JSON فقط‌گزارشی — بدون شبکه، بدون نوشتن فایل، قطعی با بذر."""
    interval_ms = int(config.get("interval_ms", 3_600_000))
    grid = config.get("grid") or [
        {"tp_pct": evaluator.TP_PCT, "sl_pct": evaluator.SL_PCT}]
    seed = int(config.get("seed", 20261025))
    n_boot = int(config.get("n_bootstrap", 2000))
    min_train_closed = int(config.get("min_train_closed", 10))
    folds_cfg = sorted(config.get("folds") or [],
                       key=lambda f: f["start_ms"])

    base = {
        "method": LAB_METHOD,
        "engine": evaluator.METHOD,
        "mode": "READ ONLY | PAPER ONLY | NO LIVE ORDERS",
        "n_symbols": len(candles_map),
        "n_events": len({e.get("event_id") for e in events}),
        "grid": grid,
        "seed": seed,
        "n_bootstrap": n_boot,
        "verdict": "REPORTED",
        "folds": [],
    }

    if not candles_map or not folds_cfg:
        return dict(base, verdict="INSUFFICIENT_EVIDENCE",
                    reason="EMPTY_INPUT_NO_FOLDS")

    # گارد سری منجمد (اصلاح A-1) — اگر اکنون داده شود و نمادِ منجمد باشد، رد
    now_ms = config.get("now_ms")
    stale = sorted(sym for sym, candles in candles_map.items()
                   if is_stale_series(candles, interval_ms, now_ms))
    if stale and len(stale) == len(candles_map):
        return dict(base, verdict="INSUFFICIENT_EVIDENCE",
                    reason="STALE_FROZEN_SERIES_ALL_SYMBOLS", stale_symbols=stale)

    # dedup رویدادها بر event_id + حذف رویداد بدون نماد شناخته‌شده
    seen = set()
    events = [e for e in events if e.get("event_id") not in seen
              and not seen.add(e.get("event_id"))
              and e.get("symbol") in candles_map
              and isinstance((e.get("features") or {}).get("entry_index"), int)]

    for f in folds_cfg:
        start_ms, end_ms = int(f["start_ms"]), int(f["end_ms"])
        if end_ms <= start_ms:
            return dict(base, verdict="INSUFFICIENT_EVIDENCE",
                        reason="INVALID_FOLD_BOUNDARIES", fold=f.get("name"))
        sel = _choose_params(candles_map, events, grid,
                             fold_start_ms=start_ms, interval_ms=interval_ms,
                             min_train_closed=min_train_closed, seed=seed,
                             n_boot=n_boot)
        params = sel["chosen"] or config.get("fallback") or grid[len(grid) // 2]
        fold_trades = []
        for sym, candles in candles_map.items():
            fold_events = [e for e in events if e.get("symbol") == sym]
            trades = evaluator.simulate_trades(
                candles, fold_events, symbol=sym,
                tp_pct=params.get("tp_pct", evaluator.TP_PCT),
                sl_pct=params.get("sl_pct", evaluator.SL_PCT),
                fee_pct=params.get("fee_pct", evaluator.FEE_PCT))
            fold_trades += [t for t in trades
                            if start_ms <= t["entry_time_ms"] < end_ms]
        metrics = _fold_metrics(fold_trades, seed=seed, n_boot=n_boot)
        # DSR-lite روی PFهای آموزشی این فولد — کنترل انتخاب، نه ادعای سود
        e_max = expected_max_sr([t["train_profit_factor"] for t in sel["trials"]
                                 if isinstance(t["train_profit_factor"], float)])
        best_pf = max((t["train_profit_factor"] for t in sel["trials"]
                       if isinstance(t["train_profit_factor"], float)),
                      default=None)
        verdict = "REPORTED" if metrics["closed"] >= evaluator.MIN_SAMPLES \
            else "INSUFFICIENT_EVIDENCE"
        base["folds"].append({
            "name": f.get("name"), "start_ms": start_ms, "end_ms": end_ms,
            "params_used": params,
            "selection": {k: sel[k] for k in
                          ("selection_basis", "n_trials", "train_pf_range")},
            "selection_control": {
                "expected_max_pf_under_n_trials": e_max,
                "best_train_pf": best_pf,
                "note": "PF جایگزین SR در DSR-lite است — فقط پرچم انتخاب",
            },
            "metrics": metrics,
            "verdict": verdict,
        })

    base["stale_symbols_filtered_note"] = (
        f"{len(stale)} stale symbol(s) present" if stale else None)
    return base


def canonical_json(report: dict) -> str:
    """نمایش قطعی برای آزمون بازتولیدپذیری (بدون مهر زمانی — کل خروجی قطعی است)."""
    return json.dumps(report, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
