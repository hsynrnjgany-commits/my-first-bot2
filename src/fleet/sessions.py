# MARI — خوشهٔ F: AMD & Session (بند ۳-F دستور)
# MODE: READ ONLY | PAPER ONLY | NO LIVE ORDERS
# سشن‌های آسیا/لندن/نیویورک با مرزهای UTC شفاف؛ آمار دامنهٔ هر سشن = مشاهدهٔ
# واقعی از تاریخچهٔ همان نماد. فازهای AMD صرفاً «فرضیهٔ آزمون‌پذیر» صادر می‌شوند
# و هیچ الگوی نظری بدون آزمون، حقیقت قطعی تلقی نمی‌شود.

from .contract import make_message

METHOD = "session_profile_amd_candidate/v1"

# (نام، ساعت شروع UTC، ساعت پایان انحصاری) — هم‌پوشانی لندن/نیویورک عمدی و ثبت‌شده است
SESSIONS_UTC = (
    ("ASIA", 0, 8),
    ("LONDON", 7, 13),
    ("NEWYORK", 12, 21),
)


def session_tags(ts_ms: int) -> list:
    """ساعت UTC → برچسب سشن‌های فعال (ممکن است بیش از یکی باشد)."""
    hour = (ts_ms // 3_600_000) % 24
    return [name for name, start, end in SESSIONS_UTC if start <= hour < end]


def _per_session_ranges(candles: list) -> dict:
    stats = {}
    for name, start, end in SESSIONS_UTC:
        ranges = [(c["high"] - c["low"]) for c in candles
                  if start <= (c["open_time"] // 3_600_000) % 24 < end]
        if ranges:
            stats[name] = {"mean_range": sum(ranges) / len(ranges),
                           "n": len(ranges)}
    return stats


def analyze(candles: list, *, symbol: str, exchange: str, timeframe: str,
            data_asof_ms: int, task_id: str = None) -> list:
    if not candles:
        return []
    last = candles[-1]
    events = [make_message(
        cluster_id="F", symbol=symbol, event_type="SESSION_PROFILE",
        event_time_ms=last["open_time"], data_asof_ms=data_asof_ms,
        exchange=exchange, timeframe=timeframe,
        features={"tags": session_tags(last["open_time"]),
                  "per_session_mean_range": {
                      k: {"mean_range": round(v["mean_range"], 6), "n": v["n"]}
                      for k, v in _per_session_ranges(candles).items()}},
        evidence={"method": METHOD,
                  "session_boundaries_utc": {n: [s, e] for n, s, e in SESSIONS_UTC}},
        validation_status="OBSERVED", task_id=task_id,
    )]

    # AMD فقط به‌عنوان فرضیهٔ آزمون‌پذیر: فشرده‌شدن دامنه → کاندید انباشت
    if len(candles) >= 12:
        recent = [(c["high"] - c["low"]) for c in candles[-6:]]
        prior = [(c["high"] - c["low"]) for c in candles[-12:-6]]
        recent_mean = sum(recent) / len(recent)
        prior_mean = sum(prior) / len(prior)
        phase = None
        rationale = ""
        if prior_mean > 0 and recent_mean / prior_mean <= 0.6:
            phase = "ACCUMULATION_CANDIDATE"
            rationale = ("فشرده‌شدن دامنهٔ شش کندل اخیر نسبت به شش کندل قبل — "
                         "فرضیهٔ انباشت؛ تأیید فقط با شکست جهت‌دار بعدی")
        elif prior_mean > 0 and recent_mean / prior_mean >= 1.8:
            phase = "EXPANSION_OBSERVED"
            rationale = ("گسترش دامنه — فاز توزیع/دست‌کاری احتمالی فقط با "
                         "خوشه‌های C و E قابل آزمون است")
        if phase:
            events.append(make_message(
                cluster_id="F", symbol=symbol, event_type="AMD_CANDIDATE",
                event_time_ms=last["open_time"], data_asof_ms=data_asof_ms,
                exchange=exchange, timeframe=timeframe,
                features={"phase": phase,
                          "recent_mean_range": round(recent_mean, 6),
                          "prior_mean_range": round(prior_mean, 6),
                          "ratio": round(recent_mean / prior_mean, 3)
                          if prior_mean > 0 else None},
                evidence={"method": METHOD},
                validation_status="HYPOTHESIS", task_id=task_id,
                hypothesis={"statement": rationale},
                uncertainty=["AMD در این نسخه فقط مبتنی بر دامنهٔ کندل است؛ "
                             "حجم و نقدینگی جداگانه در خوشه‌های E و C آزمون می‌شوند"],
            ))
    return events


class SessionCluster:
    """پوستهٔ استاندارد برای Orchestrator."""
    cluster_id = "F"

    def run(self, task: dict) -> list:
        ctx = task["ctx"]
        return analyze(task["candles"], symbol=task["symbol"],
                       exchange=ctx.get("exchange", "toobit"),
                       timeframe=ctx.get("interval", "1h"),
                       data_asof_ms=ctx["data_asof_ms"],
                       task_id=task.get("task_id"))
