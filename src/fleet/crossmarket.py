# MARI — خوشهٔ H: Cross-Market (بند ۳-H دستور)
# MODE: READ ONLY | PAPER ONLY | NO LIVE ORDERS
# مقایسهٔ قیمت یک دارایی در چند منبع. پیش از معتبر دانستن «فرصت آربیتراژ»،
# کارمزد/لغزش/تازگی داده/محدودیت‌های اجرا بررسی و در uncertainty ثبت می‌شود.
# هیچ اختلاف قیمتی به‌تنهایی «فرصت» شمرده نمی‌شود (بند ۳-H صریح است).

from .contract import make_message

METHOD = "cross_market_divergence/v1"
DEFAULT_FEE_PCT = 0.001      # فرض کارمزد هر پا (شفاف در evidence)
DEFAULT_SLIPPAGE_PCT = 0.001 # فرض لغزش هر پا
STALENESS_MS = 120_000       # تازگی مجاز کوتیشن‌ها (۲ دقیقه)


def analyze(symbol: str, prices: dict, *, quotes_asof_ms: dict = None,
            data_asof_ms: int = 0, fee_pct: float = DEFAULT_FEE_PCT,
            slippage_pct: float = DEFAULT_SLIPPAGE_PCT,
            timeframe: str = "1h", task_id: str = None) -> list:
    quotes_asof_ms = quotes_asof_ms or {}
    if len(prices) < 2:
        return [make_message(
            cluster_id="H", symbol=symbol, event_type="CROSS_MARKET_UNAVAILABLE",
            event_time_ms=data_asof_ms, data_asof_ms=data_asof_ms,
            exchange="multi", timeframe=timeframe,
            features={"available_exchanges": sorted(prices.keys())},
            evidence={"method": METHOD},
            validation_status="UNAVAILABLE", task_id=task_id,
            uncertainty=["کمتر از دو منبع در دسترس بود — مقایسه ممکن نشد"],
        )]

    hi_ex = max(prices, key=prices.get)
    lo_ex = min(prices, key=prices.get)
    hi, lo = prices[hi_ex], prices[lo_ex]
    divergence_pct = (hi - lo) / lo * 100 if lo > 0 else 0.0

    asof_values = [quotes_asof_ms[e] for e in prices if quotes_asof_ms.get(e)]
    fresh = bool(asof_values) and len(asof_values) == len(prices) and all(
        abs(data_asof_ms - a) <= STALENESS_MS for a in asof_values
    )
    round_trip_cost_pct = 2 * (fee_pct + slippage_pct) * 100

    if fresh and divergence_pct > round_trip_cost_pct:
        status, ev_type = "UNVALIDATED", "CROSS_MARKET_DIVERGENCE"
        hypothesis = {"statement":
                      f"اختلاف قیمت {round(divergence_pct, 4)}٪ بین {lo_ex} و "
                      f"{hi_ex} از هزینهٔ رفت‌وبرگشت فرضی بیشتر است — "
                      "کاندید فرصت آربیتراژ؛ هنوز هیچ‌کدام از شرایط اجرا تأیید نشده"}
        uncertainty = ["کارمزد و لغزش «فرض» هستند، از منبع واقعی نمی‌آیند",
                       "تأخیر داده بین دو منبع بررسی‌نشده است",
                       "محدودیت انتقال دارایی بین صرافی‌ها بررسی نشده",
                       "عمق دفتر سفارش و امکان اجرای واقعی بررسی نشده"]
    else:
        status, ev_type = "OBSERVED", "NO_ACTIONABLE_EDGE"
        hypothesis = None
        uncertainty = [] if fresh else ["کوتیشن‌ها تازه نبودند — قضاوت متوقف ماند"]

    return [make_message(
        cluster_id="H", symbol=symbol, event_type=ev_type,
        event_time_ms=data_asof_ms, data_asof_ms=data_asof_ms,
        exchange="multi", timeframe=timeframe,
        features={"prices": prices,
                  "high_exchange": hi_ex, "low_exchange": lo_ex,
                  "divergence_pct": round(divergence_pct, 4),
                  "round_trip_cost_assumed_pct": round(round_trip_cost_pct, 4),
                  "quotes_fresh": fresh},
        evidence={"method": METHOD,
                  "fee_assumption_pct": fee_pct,
                  "slippage_assumption_pct": slippage_pct,
                  "staleness_limit_ms": STALENESS_MS},
        validation_status=status, task_id=task_id,
        hypothesis=hypothesis, uncertainty=uncertainty,
    )]


class CrossMarketCluster:
    """پوستهٔ استاندارد برای Orchestrator — قیمت‌ها توسط scan واکشی و در ctx می‌آیند."""
    cluster_id = "H"

    def run(self, task: dict) -> list:
        ctx = task["ctx"]
        return analyze(task["symbol"], ctx.get("prices", {}),
                       quotes_asof_ms=ctx.get("quotes_asof_ms", {}),
                       data_asof_ms=ctx["data_asof_ms"],
                       timeframe=ctx.get("interval", "1h"),
                       task_id=task.get("task_id"))
