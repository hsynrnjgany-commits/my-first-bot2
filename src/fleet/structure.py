# MARI — خوشهٔ D: Market Structure (بند ۳-D دستور)
# MODE: READ ONLY | PAPER ONLY | NO LIVE ORDERS
# روند، سوئینگ‌ها، شکست ساختار (BOS) و تغییر ساختار (CHoCH).
# قید نشت اطلاعات: تشخیص پیوت به کندل‌های بعد از خودش نیاز دارد، پس event_time
# زمان پیوت است ولی رویداد فقط در زمان تأیید (confirmed_at) صادر می‌شود و
# هیچ محاسبه‌ای از داده‌های پس از زمان رویداد استفاده نمی‌کند.
# همهٔ الگوها HYPOTHESIS هستند تا حسابرس مستقل (بند ۵) آن‌ها را بیازماید.

from .contract import make_message

K_FRAC = 2          # تعداد کندل هر سمت برای فرکتال
CONFIRM_LAG = 2     # تأخیر تأیید = k (شفاف و ثابت)
METHOD = "fractal_swing_k2_confirmed2/v1"


def find_swing_points(candles: list, k: int = K_FRAC) -> list:
    """پیوت‌های فرکتالی — هر پیوت با confirmed_at (زمان کندل i+k) صادر می‌شود."""
    points = []
    for i in range(k, len(candles) - k):
        confirmed_at = candles[i + k]["open_time"]
        is_high = all(
            candles[i]["high"] > candles[j]["high"]
            for j in range(i - k, i + k + 1) if j != i
        )
        is_low = all(
            candles[i]["low"] < candles[j]["low"]
            for j in range(i - k, i + k + 1) if j != i
        )
        if is_high:
            points.append({"index": i, "time": candles[i]["open_time"],
                           "price": candles[i]["high"], "kind": "HIGH",
                           "confirmed_at": confirmed_at})
        if is_low:
            points.append({"index": i, "time": candles[i]["open_time"],
                           "price": candles[i]["low"], "kind": "LOW",
                           "confirmed_at": confirmed_at})
    return points


def _ev(symbol, event_type, at_ms, data_asof_ms, features, method, key="",
        exchange="toobit", timeframe=None, task_id=None, hypothesis=None):
    return make_message(
        cluster_id="D", symbol=symbol, event_type=event_type,
        event_time_ms=at_ms, data_asof_ms=data_asof_ms, exchange=exchange,
        timeframe=timeframe, features=features,
        evidence={"method": method},
        validation_status="HYPOTHESIS", task_id=task_id,
        hypothesis=hypothesis, event_key=key,
    )


def analyze(candles: list, *, symbol: str, exchange: str, timeframe: str,
            data_asof_ms: int, task_id: str = None) -> list:
    """خروجی: پیام‌های TREND_ASSESSMENT / BOS_BULLISH / BOS_BEARISH."""
    events = []
    swings = [p for p in find_swing_points(candles) if p["confirmed_at"] <= data_asof_ms]
    highs = [p for p in swings if p["kind"] == "HIGH"]
    lows = [p for p in swings if p["kind"] == "LOW"]

    trend = "UNDETERMINED"
    if len(highs) >= 2 and len(lows) >= 2:
        hh = highs[-1]["price"] > highs[-2]["price"]
        hl = lows[-1]["price"] > lows[-2]["price"]
        if hh and hl:
            trend = "BULLISH"
        elif (not hh) and (not hl):
            trend = "BEARISH"
        events.append(_ev(
            symbol, "TREND_ASSESSMENT", highs[-1]["time"], data_asof_ms,
            {"trend": trend,
             "last_highs": [p["price"] for p in highs[-2:]],
             "last_lows": [p["price"] for p in lows[-2:]]},
            METHOD, key=str(highs[-1]["time"]),
            exchange=exchange, timeframe=timeframe, task_id=task_id,
            hypothesis={"statement":
                        "روند از مقایسهٔ دو سوئینگ آخر استنتاج شده — فرضیه؛ "
                        "ادامه‌ی تداوم آن باید توسط حسابرس مستقل آزمون شود"},
        ))

    # BOS: نخستین کلوز بعد از سوئینگ تأییدشده که سطح آن را می‌شکند
    for kind, ev_type, direction in (("HIGH", "BOS_BULLISH", "long"),
                                     ("LOW", "BOS_BEARISH", "short")):
        pool = highs if kind == "HIGH" else lows
        if not pool:
            continue
        last = pool[-1]
        for j in range(last["index"] + 1, len(candles)):
            c = candles[j]
            broke = (c["close"] > last["price"]) if kind == "HIGH" \
                else (c["close"] < last["price"])
            if broke and c["open_time"] <= data_asof_ms:
                choch = (trend == "BEARISH") if kind == "HIGH" \
                    else (trend == "BULLISH")
                events.append(_ev(
                    symbol, ev_type, c["open_time"], data_asof_ms,
                    {"broken_level": last["price"], "close": c["close"],
                     "choch": choch, "entry_index": j, "direction": direction},
                    METHOD, key=str(c["open_time"]),
                    exchange=exchange, timeframe=timeframe, task_id=task_id,
                    hypothesis={"statement":
                                f"شکست ساختار {'صعودی' if kind == 'HIGH' else 'نزولی'} "
                                "— فرضیهٔ جهت‌دار برای آزمون شبیه‌ساز کاغذی"},
                ))
                break
    return events


class StructureCluster:
    """پوستهٔ استاندارد برای Orchestrator (بند ۳-A تا ۳-D)."""
    cluster_id = "D"

    def run(self, task: dict) -> list:
        ctx = task["ctx"]
        return analyze(task["candles"], symbol=task["symbol"],
                       exchange=ctx.get("exchange", "toobit"),
                       timeframe=ctx.get("interval", "1h"),
                       data_asof_ms=ctx["data_asof_ms"],
                       task_id=task.get("task_id"))
