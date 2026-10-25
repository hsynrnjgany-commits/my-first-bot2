# MARI — بند ۵ دستور: موتور ارزیابی و حسابرس مستقل
# MODE: READ ONLY | PAPER ONLY | NO LIVE ORDERS
# هیچ فرصتی صرفاً به دلیل توافق چند پهپاد پذیرفته نمی‌شود. این موتور رویدادهای
# فرضی خوشهٔ D را با شبیه‌ساز کاغذی (TP/SL/کارمزد) می‌سنجد و سنجه‌های واقعی می‌دهد؛
# تا وقتی شواهد کافی نیست، فقط INSUFFICIENT_EVIDENCE یا UNVALIDATED صادر می‌شود
# و «هیچ معیار یا آستانه‌ای به‌عنوان موفقیت قطعی جعل نمی‌شود».

import math

from .contract import make_message
from . import risk as risk_mod

# پارامترهای شفاف — همان قرارداد mari-paper-v1 داشبورد (TP +2% / SL −1% / کارمزد 0.1%)
TP_PCT = 0.02
SL_PCT = 0.01
FEE_PCT = 0.001
MIN_SAMPLES = 30      # حداقل نمونهٔ اعلام‌شده — آستانهٔ موفقیت نیست، سقف ادعا است

METHOD = "paper_simulator_v1/tp2_sl1_fee01"


def simulate_trades(candles: list, events: list, *, symbol: str,
                    tp_pct: float = TP_PCT, sl_pct: float = SL_PCT,
                    fee_pct: float = FEE_PCT) -> list:
    """شبیه‌سازی کاغذی رویدادهای BOS: ورود در اپن کندل بعد از رویداد (بدون نشت).
    قاعدهٔ محافظه‌کارانهٔ اعلام‌شده: برخورد همزمان TP و SL در یک کندل → SL.
    خروج ندادن تا پایان داده → exit_reason=OPEN (وضعیت صادقانه، نه بستهٔ جعلی)."""
    trades = []
    for ev in events:
        features = ev.get("features", {})
        direction = features.get("direction")
        entry_index = features.get("entry_index")
        if direction not in ("long", "short") or entry_index is None:
            continue
        i = int(entry_index)
        if i + 1 >= len(candles):
            continue
        entry = candles[i + 1]["open"]
        long = direction == "long"
        tp = entry * (1 + tp_pct) if long else entry * (1 - tp_pct)
        sl = entry * (1 - sl_pct) if long else entry * (1 + sl_pct)
        mfe = 0.0
        mae = 0.0
        exit_reason = None
        exit_price = None
        hold = 0
        for c in candles[i + 1:]:
            hold += 1
            favorable = ((c["high"] - entry) / entry) if long \
                else ((entry - c["low"]) / entry)
            adverse = ((entry - c["low"]) / entry) if long \
                else ((c["high"] - entry) / entry)
            mfe = max(mfe, favorable)
            mae = max(mae, adverse)
            hit_sl = c["low"] <= sl if long else c["high"] >= sl
            hit_tp = c["high"] >= tp if long else c["low"] <= tp
            if hit_sl:  # محافظه‌کارانه: هم‌زمانی → SL
                exit_reason, exit_price = "SL", sl
                break
            if hit_tp:
                exit_reason, exit_price = "TP", tp
                break
        if exit_reason is None:
            exit_reason, exit_price = "OPEN", candles[-1]["close"]
        gross = ((exit_price - entry) / entry) if long \
            else ((entry - exit_price) / entry)
        net = gross - 2 * fee_pct  # کارمزد هر دو پا
        trades.append({
            "symbol": symbol,
            "event_id": ev["event_id"],
            "direction": direction,
            "entry_time_ms": candles[i + 1]["open_time"],
            "entry": entry,
            "exit_reason": exit_reason,
            "exit": exit_price,
            "gross_pct": round(gross * 100, 6),
            "net_pct": round(net * 100, 6),
            "mfe_pct": round(mfe * 100, 6),
            "mae_pct": round(mae * 100, 6),
            "hold_candles": hold,
        })
    return trades


def evaluate(trades: list, *, min_samples: int = MIN_SAMPLES) -> dict:
    """سنجه‌های واقعی از معاملات شبیه‌سازی‌شده — بدون ادعای موفقیت.
    اصلاح A-2 گزارش MISSION 002: سنجه‌های بالادستی (win_rate/kelly/MDD) از
    توزیع مختلط realized+OPEN محاسبه می‌شدند؛ اکنون بلوک «realized» جداگانه
    فقط روی معاملات بسته (TP/SL) و MDD به‌صورت زمان‌مرتب گزارش می‌شود."""
    n = len(trades)
    nets = [t["net_pct"] for t in trades]
    wins = sum(1 for x in nets if x > 0)
    gross_win = sum(x for x in nets if x > 0)
    gross_loss = abs(sum(x for x in nets if x < 0))
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else None
    dd = risk_mod.max_drawdown(
        [sum(nets[:i + 1]) for i in range(n)]) if n else {"max_dd": 0.0}
    # ---- بلوک realized (فقط بسته‌ها) — مبنای هر تصمیم ----
    closed = [t for t in trades if t.get("exit_reason") in ("TP", "SL")]
    closed_nets = [t["net_pct"] for t in closed]
    ordered = sorted(closed, key=lambda t: t.get("entry_time_ms", 0))
    curve_pp = []
    acc = 0.0
    peak_abs = 0.0
    mdd_pp = 0.0
    for t in ordered:
        acc += t["net_pct"]
        curve_pp.append(acc)
        peak_abs = max(peak_abs, acc)
        mdd_pp = max(mdd_pp, peak_abs - acc)  # افت مطلق (واحد: pp)
    dd_rel_time = risk_mod.max_drawdown(curve_pp) if curve_pp \
        else {"max_dd": 0.0}
    c_n = len(closed_nets)
    c_wins = sum(1 for x in closed_nets if x > 0)
    c_gw = sum(x for x in closed_nets if x > 0)
    c_gl = abs(sum(x for x in closed_nets if x < 0))
    realized = {
        "n_closed": c_n,
        "profit_factor": round(c_gw / c_gl, 4) if c_gl > 0
        else (None if c_gw == 0 else "UNDEFINED_NO_LOSSES"),
        "win_rate": round(c_wins / c_n, 4) if c_n else None,
        "avg_net_pct": round(sum(closed_nets) / c_n, 6) if c_n else None,
        "sum_net_pct": round(sum(closed_nets), 6) if c_n else None,
        "kelly_fraction_paper": kelly_fraction_paper(closed_nets) if c_n else None,
        "t_stat": t_stat(closed_nets) if c_n else None,
        "note": "فقط TP/SL؛ معاملات OPEN (نشانه‌گذاری‌نشده) در این بلوک نیستند",
    }
    result = {
        "n": n,
        "min_samples_required": min_samples,
        "profit_factor": round(profit_factor, 4) if profit_factor is not None
        else "UNDEFINED_NO_LOSSES",
        "win_rate": round(wins / n, 4) if n else None,
        "avg_net_pct": round(sum(nets) / n, 6) if n else None,
        "max_drawdown_curve": round(dd["max_dd"], 6),
        "max_drawdown_pp_time_ordered": round(mdd_pp, 6),
        "max_drawdown_rel_time_ordered": round(dd_rel_time["max_dd"], 6),
        "realized": realized,
        "metrics_semantics": "win_rate/kelly بالادستی شامل OPENهاست (marked)؛ "
                             "هر تصمیم فقط بر بلوک realized بنا شود",
        "avg_mfe_pct": round(sum(t["mfe_pct"] for t in trades) / n, 6) if n else None,
        "avg_mae_pct": round(sum(t["mae_pct"] for t in trades) / n, 6) if n else None,
        "exit_mix": {
            "TP": sum(1 for t in trades if t["exit_reason"] == "TP"),
            "SL": sum(1 for t in trades if t["exit_reason"] == "SL"),
            "OPEN": sum(1 for t in trades if t["exit_reason"] == "OPEN"),
        },
        "concentration": risk_mod.concentration(trades),
        "t_stat": t_stat(nets),
        "kelly_fraction_paper": kelly_fraction_paper(nets),
        "walk_forward": walk_forward(trades),
        "validation_status": "INSUFFICIENT_EVIDENCE" if n < min_samples
        else "UNVALIDATED",
        "method": METHOD,
        "note": ("شبیه‌سازی کاغذی روی دادهٔ تاریخی؛ UNVALIDATED یعنی حتی "
                 "آزمون خارج از نمونه/Walk-Forward هنوز به قضاوت نرسیده — "
                 "هیچ ادعای سودآوری وجود ندارد"),
    }
    return result


# ---------- بند ۵ (نسخهٔ ۲): سنجه‌های استحکام — همه «پژوهشی» و بدون آستانهٔ جعلی ----------

def t_stat(nets: list) -> "float | None":
    """t تک‌نمونه‌ای برای میانگین بازده خالص — n<2 یا واریانس صفر → None."""
    n = len(nets)
    if n < 2:
        return None
    mean = sum(nets) / n
    var = sum((x - mean) ** 2 for x in nets) / (n - 1)
    std = math.sqrt(var)
    if std <= 0:
        return None
    return round(mean / (std / math.sqrt(n)), 4)


def kelly_fraction_paper(nets: list) -> "float | None":
    """کسری Kelly از توزیع نتایج کاغذی — فقط پژوهشی؛ هرگز توصیهٔ اندازه‌گیری واقعی."""
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x < 0]
    if not wins or not losses:
        return None
    p = len(wins) / len(nets)
    avg_win = sum(wins) / len(wins)
    avg_loss = abs(sum(losses) / len(losses))
    b = avg_win / avg_loss
    return round((p * b - (1 - p)) / b, 4)


def walk_forward(trades: list, n_splits: int = 4, min_per_window: int = 5) -> dict:
    """پنجره‌های زمانی پیوسته: میانگین بازده هر پنجره + سهم پنجره‌های مثبت.
    این «آزمون» است نه حکم؛ خروجی صرفاً اعداد بی‌طرف می‌دهد."""
    ordered = sorted(trades, key=lambda t: t.get("entry_time_ms", 0))
    n = len(ordered)
    if n < n_splits * min_per_window:
        return {"status": "INSUFFICIENT_EVIDENCE", "n": n,
                "required": n_splits * min_per_window}
    chunk = n // n_splits
    windows = []
    for k in range(n_splits):
        part = ordered[k * chunk:(k + 1) * chunk] if k < n_splits - 1 \
            else ordered[(n_splits - 1) * chunk:]
        nets = [t["net_pct"] for t in part]
        windows.append({
            "n": len(nets),
            "avg_net_pct": round(sum(nets) / len(nets), 6),
            "wins": sum(1 for x in nets if x > 0),
        })
    positive = sum(1 for w in windows if w["avg_net_pct"] > 0)
    return {
        "status": "COMPUTED",
        "splits": n_splits,
        "windows": windows,
        "positive_windows": positive,
        "stability_note": "سهم پنجره‌های مثبت فقط توصیف است — آستانهٔ موفقیت جعل نشده",
    }


def evaluation_message(symbol: str, metrics: dict, *, data_asof_ms: int,
                       task_id: str = None) -> dict:
    """بسته‌بندی نتیجهٔ ارزیاب به پیام قراردادی (خوشهٔ A به نمایندگی حسابرس)."""
    return make_message(
        cluster_id="A", symbol=symbol, event_type="EVALUATION_REPORT",
        event_time_ms=data_asof_ms, data_asof_ms=data_asof_ms,
        exchange="paper", market_type="paper", timeframe="1h",
        features=metrics,
        evidence={"method": METHOD,
                  "simulation_params": {"tp_pct": TP_PCT, "sl_pct": SL_PCT,
                                        "fee_pct": FEE_PCT}},
        validation_status=metrics["validation_status"], task_id=task_id,
        uncertainty=["شبیه‌ساز تکی‌ورودی است؛ Walk-Forward و Holdout در "
                     "مرحلهٔ بعدی حسابرس انجام می‌شود"],
    )
