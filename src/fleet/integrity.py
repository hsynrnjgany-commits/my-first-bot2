# MARI — خوشهٔ L: Data Integrity & Forensics (بند ۳-L دستور)
# MODE: READ ONLY | PAPER ONLY | NO LIVE ORDERS
# بررسی کامل بودن کندل‌ها، ترتیب زمانی، تکرار، شکاف، ناسازگاری OHLC و حجم.
# هر یافته به منبع و روش قابل ردیابی است؛ دادهٔ نامعتبر بی‌صدا وارد تحلیل نمی‌شود
# (از clean حذف و به‌صورت یافتهٔ OBSERVED ثبت می‌شود).

from .contract import make_message

METHOD = "audit_candles/v1"


def audit_candles(candles: list, *, interval_ms: int, symbol: str,
                  exchange: str, timeframe: str, data_asof_ms: int,
                  task_id: str = None):
    """خروجی: (clean, findings) — findings فهرست پیام قراردادی خوشهٔ L."""
    findings = []
    clean = []
    seen_ts = set()

    def _finding(event_type, idx, extra):
        findings.append(make_message(
            cluster_id="L", symbol=symbol, event_type=event_type,
            event_time_ms=candles[idx]["open_time"], data_asof_ms=data_asof_ms,
            exchange=exchange, timeframe=timeframe,
            features={"index": idx, **extra},
            evidence={"source": f"{exchange}.klines", "method": METHOD},
            validation_status="OBSERVED", task_id=task_id,
        ))

    for idx, c in enumerate(candles):
        bad = False
        if min(c["open"], c["high"], c["low"], c["close"]) <= 0:
            _finding("NONPOSITIVE_PRICE", idx,
                     {"values": [c["open"], c["high"], c["low"], c["close"]]})
            bad = True
        if c["volume"] < 0:
            _finding("NEGATIVE_VOLUME", idx, {"volume": c["volume"]})
            bad = True
        if c["high"] < max(c["open"], c["close"]) or \
                c["low"] > min(c["open"], c["close"]) or c["low"] > c["high"]:
            _finding("INCONSISTENT_OHLC", idx,
                     {"open": c["open"], "high": c["high"],
                      "low": c["low"], "close": c["close"]})
            bad = True
        if c["open_time"] in seen_ts:
            _finding("DUPLICATE_TIMESTAMP", idx, {"open_time": c["open_time"]})
            bad = True
            continue
        seen_ts.add(c["open_time"])
        if not bad:
            clean.append(c)

    clean.sort(key=lambda c: c["open_time"])
    inversions = sum(
        1 for a, b in zip(candles, candles[1:])
        if b["open_time"] < a["open_time"]
    )
    if inversions:
        findings.append(make_message(
            cluster_id="L", symbol=symbol, event_type="OUT_OF_ORDER",
            event_time_ms=candles[-1]["open_time"], data_asof_ms=data_asof_ms,
            exchange=exchange, timeframe=timeframe,
            features={"adjacent_inversions": inversions, "sorted_after_audit": True},
            evidence={"source": f"{exchange}.klines", "method": METHOD},
            validation_status="OBSERVED", task_id=task_id,
        ))

    for a, b in zip(clean, clean[1:]):
        gap = b["open_time"] - a["open_time"]
        if gap > interval_ms:
            findings.append(make_message(
                cluster_id="L", symbol=symbol, event_type="GAP",
                event_time_ms=b["open_time"], data_asof_ms=data_asof_ms,
                exchange=exchange, timeframe=timeframe,
                features={"gap_ms": gap,
                          "gap_intervals": round(gap / interval_ms, 3),
                          "after_open_time": a["open_time"]},
                evidence={"source": f"{exchange}.klines", "method": METHOD},
                validation_status="OBSERVED", task_id=task_id,
            ))

    return clean, findings
