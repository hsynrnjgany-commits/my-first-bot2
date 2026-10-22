# MARI — خوشهٔ E: Volume & Value (بند ۳-E دستور)
# MODE: READ ONLY | PAPER ONLY | NO LIVE ORDERS
# حجم غیرعادی فقط نسبت به تاریخچهٔ «همان نماد» (معیار نسبی، نه حد مطلق جهانی).
# z-score نمونهٔ آخر در برابر پنجرهٔ قبل از خودش — بدون نشت آینده.

import math

from .contract import make_message

METHOD = "relative_volume_zscore/v1"
WINDOW = 20
Z_THRESHOLD = 2.0


def unusual_volume(candles: list, *, symbol: str, exchange: str,
                   timeframe: str, data_asof_ms: int, task_id: str = None,
                   window: int = WINDOW, z_threshold: float = Z_THRESHOLD) -> list:
    """z حجم کندل آخر در برابر میانگین/انحراف پنجرهٔ قبل از آن."""
    if len(candles) < window + 1:
        return []
    i = len(candles) - 1
    hist = [c["volume"] for c in candles[i - window:i]]
    mean = sum(hist) / window
    variance = sum((v - mean) ** 2 for v in hist) / window
    std = math.sqrt(variance)
    if std <= 0:
        return []  # پنجرهٔ بدون واریانس — هیچ عددی جعل نمی‌شود
    z = (candles[i]["volume"] - mean) / std
    ratio = candles[i]["volume"] / mean if mean > 0 else None
    if z < z_threshold:
        return []
    return [make_message(
        cluster_id="E", symbol=symbol, event_type="VOLUME_SURGE",
        event_time_ms=candles[i]["open_time"], data_asof_ms=data_asof_ms,
        exchange=exchange, timeframe=timeframe,
        features={"z": round(z, 3),
                  "ratio_to_mean": round(ratio, 3) if ratio else None,
                  "window": window,
                  "volume": candles[i]["volume"],
                  "mean_prev_volume": round(mean, 6)},
        evidence={"method": METHOD},
        validation_status="HYPOTHESIS", task_id=task_id,
        hypothesis={"statement":
                    "حجم غیرعادی نسبت به تاریخچهٔ همان نماد — فرضیهٔ ورود "
                    "پول تازه؛ جهت آن بدون خوشه‌های دیگر قابل قضاوت نیست"},
        uncertainty=["z-score به پنجرهٔ ۲۰ کندلی حساس است",
                     "تقسیم‌شدگی معاملات (split/aggregate) از این منبع مشخص نیست"],
    )]


class VolumeCluster:
    """پوستهٔ استاندارد برای Orchestrator."""
    cluster_id = "E"

    def run(self, task: dict) -> list:
        ctx = task["ctx"]
        return unusual_volume(task["candles"], symbol=task["symbol"],
                              exchange=ctx.get("exchange", "toobit"),
                              timeframe=ctx.get("interval", "1h"),
                              data_asof_ms=ctx["data_asof_ms"],
                              task_id=task.get("task_id"))
