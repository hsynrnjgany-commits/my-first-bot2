# MARI — خوشهٔ C: Liquidity Intelligence (بند ۳-C دستور)
# MODE: READ ONLY | PAPER ONLY | NO LIVE ORDERS
# سقف/کف‌های هم‌سطح (استخرهای نقدینگی) و شکست ناموفق (جمع‌آوری نقدینگی احتمالی).
# تفکیک اجباری: مشاهدهٔ عددی در features، فرضیهٔ تفسیری فقط در hypothesis.

from .contract import make_message
from . import structure as structure_cluster

METHOD = "swing_pools_failed_break/v1"
POOL_TOLERANCE = 0.0005   # اختلاف مجاز «هم‌سطح بودن» دو سوئینگ (۵ صدم درصد)
PROBE_CANDLES = 5         # چند کندل بعد از سوئینگ برای شکست ناموفق بررسی شود


def analyze(candles: list, *, symbol: str, exchange: str, timeframe: str,
            data_asof_ms: int, task_id: str = None) -> list:
    events = []
    swings = [p for p in structure_cluster.find_swing_points(candles)
              if p["confirmed_at"] <= data_asof_ms]
    highs = [p for p in swings if p["kind"] == "HIGH"]
    lows = [p for p in swings if p["kind"] == "LOW"]

    def _msg(event_type, at_ms, features, hypothesis=None, key=""):
        return make_message(
            cluster_id="C", symbol=symbol, event_type=event_type,
            event_time_ms=at_ms, data_asof_ms=data_asof_ms,
            exchange=exchange, timeframe=timeframe, features=features,
            evidence={"method": METHOD},
            validation_status="OBSERVED", task_id=task_id,
            hypothesis=hypothesis, event_key=key,
        )

    # استخرهای هم‌سطح: دو سوئینگ مجاور با اختلاف ناچیز
    for pool_list, ev_type, side in ((highs, "LIQ_POOL_ABOVE", "بالا"),
                                     (lows, "LIQ_POOL_BELOW", "پایین")):
        for p1, p2 in zip(pool_list, pool_list[1:]):
            ref = min(p1["price"], p2["price"])
            if ref <= 0:
                continue
            if abs(p1["price"] - p2["price"]) / ref <= POOL_TOLERANCE:
                events.append(_msg(
                    ev_type, p2["time"],
                    {"levels": [p1["price"], p2["price"]],
                     "tolerance": POOL_TOLERANCE, "side": side},
                    hypothesis={"statement":
                                f"هم‌سطحی دو سوئینگ در {side} نماد — فرضیهٔ "
                                "استخر نقدینگی؛ احتمال هدف‌گیری توسط بازیگران"},
                    key=f"{p1['time']}:{p2['time']}",
                ))

    # شکست ناموفق: فتیله از سطح سوئینگ عبور کرد ولی کلوز به داخل برگشت.
    # برای هر سوئینگِ «آخرِ گروه هم‌سطح»، کندل‌های بعد از آن (تا PROBE_CANDLES)
    # بررسی می‌شوند؛ سوئینگ‌های هم‌سطحِ تکراری دوباره کاوش نمی‌شوند.
    def _probe_pools(pool_list, kind, ev_type):
        for pos, p in enumerate(pool_list):
            is_last_of_group = (pos == len(pool_list) - 1) or (
                abs(p["price"] - pool_list[pos + 1]["price"])
                / min(p["price"], pool_list[pos + 1]["price"])
                > POOL_TOLERANCE
            )
            if not is_last_of_group:
                continue  # سطح بعدی همان استخر را نمایندگی می‌کند
            for j in range(p["index"] + 1,
                           min(p["index"] + 1 + PROBE_CANDLES, len(candles))):
                c = candles[j]
                if c["open_time"] > data_asof_ms:
                    break
                pierced = (c["high"] > p["price"]) if kind == "HIGH" \
                    else (c["low"] < p["price"])
                rejected = (c["close"] < p["price"]) if kind == "HIGH" \
                    else (c["close"] > p["price"])
                if pierced and rejected:
                    events.append(_msg(
                        ev_type, c["open_time"],
                        {"swing_level": p["price"],
                         "high": c["high"], "low": c["low"],
                         "close": c["close"],
                         "swing_confirmed_at": p["confirmed_at"]},
                        hypothesis={"statement":
                                    "عبور و بازگشت از سوئینگ — فرضیهٔ "
                                    "جمع‌آوری نقدینگی (sweep) با جهت بازگشتی "
                                    f"{'صعودی' if kind == 'HIGH' else 'نزولی'}؛ "
                                    "نیازمند آزمون مستقل"},
                        key=f"{p['time']}:{c['open_time']}",
                    ))
                    break

    _probe_pools(highs, "HIGH", "FAILED_BREAK_ABOVE")
    _probe_pools(lows, "LOW", "FAILED_BREAK_BELOW")
    return events


class LiquidityCluster:
    """پوستهٔ استاندارد برای Orchestrator."""
    cluster_id = "C"

    def run(self, task: dict) -> list:
        ctx = task["ctx"]
        return analyze(task["candles"], symbol=task["symbol"],
                       exchange=ctx.get("exchange", "toobit"),
                       timeframe=ctx.get("interval", "1h"),
                       data_asof_ms=ctx["data_asof_ms"],
                       task_id=task.get("task_id"))
