# MARI — بند ۵ دستور: موتور ارزیابی و حسابرس مستقل
# MODE: READ ONLY | PAPER ONLY | NO LIVE ORDERS
# هیچ فرصتی صرفاً به دلیل توافق چند پهپاد پذیرفته نمی‌شود. این موتور رویدادهای
# فرضی خوشهٔ D را با شبیه‌ساز کاغذی (TP/SL/کارمزد) می‌سنجد و سنجه‌های واقعی می‌دهد؛
# تا وقتی شواهد کافی نیست، فقط INSUFFICIENT_EVIDENCE یا UNVALIDATED صادر می‌شود
# و «هیچ معیار یا آستانه‌ای به‌عنوان موفقیت قطعی جعل نمی‌شود».

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
    """سنجه‌های واقعی از معاملات شبیه‌سازی‌شده — بدون ادعای موفقیت."""
    n = len(trades)
    nets = [t["net_pct"] for t in trades]
    wins = sum(1 for x in nets if x > 0)
    gross_win = sum(x for x in nets if x > 0)
    gross_loss = abs(sum(x for x in nets if x < 0))
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else None
    dd = risk_mod.max_drawdown(
        [sum(nets[:i + 1]) for i in range(n)]) if n else {"max_dd": 0.0}
    result = {
        "n": n,
        "min_samples_required": min_samples,
        "profit_factor": round(profit_factor, 4) if profit_factor is not None
        else "UNDEFINED_NO_LOSSES",
        "win_rate": round(wins / n, 4) if n else None,
        "avg_net_pct": round(sum(nets) / n, 6) if n else None,
        "max_drawdown_curve": round(dd["max_dd"], 6),
        "avg_mfe_pct": round(sum(t["mfe_pct"] for t in trades) / n, 6) if n else None,
        "avg_mae_pct": round(sum(t["mae_pct"] for t in trades) / n, 6) if n else None,
        "exit_mix": {
            "TP": sum(1 for t in trades if t["exit_reason"] == "TP"),
            "SL": sum(1 for t in trades if t["exit_reason"] == "SL"),
            "OPEN": sum(1 for t in trades if t["exit_reason"] == "OPEN"),
        },
        "concentration": risk_mod.concentration(trades),
        "validation_status": "INSUFFICIENT_EVIDENCE" if n < min_samples
        else "UNVALIDATED",
        "method": METHOD,
        "note": ("شبیه‌سازی کاغذی روی دادهٔ تاریخی؛ UNVALIDATED یعنی حتی "
                 "آزمون خارج از نمونه/Walk-Forward هنوز انجام نشده — "
                 "هیچ ادعای سودآوری وجود ندارد"),
    }
    return result


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
