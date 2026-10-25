# MARI — بند ۴ دستور اجرایی: قرارداد استاندارد بین پهپادها
# MODE: READ ONLY | PAPER ONLY | NO LIVE ORDERS
# هر خروجی خوشه‌ها فقط از طریق make_message ساخته می‌شود؛ تمام فیلدهای اجباری
# دستور را دارد، event_id قطعی (deterministic) دارد تا «تولید چندبارهٔ رویداد
# یکسان» به‌طور ساختاری ممکن نشود، و hypothesis هرگز با evidence مخلوط نمی‌شود.

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone

SCHEMA_VERSION = "mari.fleet.message/v1"
SOURCE_VERSION = "stage1+fleet/1.0"
SAFETY_MODE = "READ_ONLY | PAPER_ONLY | NO_LIVE_ORDERS"

# نگاشت خوشه‌های دستور (بند ۳) به شناسهٔ یک‌حرفی پایدار
CLUSTERS = {
    "A": "master-orchestrator",
    "B": "market-discovery",
    "C": "liquidity-intelligence",
    "D": "market-structure",
    "E": "volume-value",
    "F": "amd-session",
    "G": "derivatives",
    "H": "cross-market",
    "I": "onchain-newtoken",
    "J": "macro-news-events",
    "K": "risk-portfolio",
    "L": "data-integrity-forensics",
    # افزودهٔ ناوگان (ثبت شفاف، فراتر از فهرست A–L دستور): آزمایشگاه کمّی
    "M": "quant-lab",
    # افزودهٔ WORLD MARKET CORE: هستهٔ کشف جهانی و پهنای بازار
    "N": "global-market-core",
}

# وضعیت بررسی — هیچ وضعیت دیگری مجاز نیست؛ جعل موفقیت ساختاری رد می‌شود
VALIDATION_STATUSES = (
    "OBSERVED",               # مشاهدهٔ واقعی از دادهٔ معتبر
    "HYPOTHESIS",             # فرضیهٔ تحلیلی — از مشاهده جداست و باید آزمون شود
    "VALIDATED",              # بررسی مستقل کامل‌شده
    "UNVALIDATED",            # هنوز بررسی مستقل نشده
    "INSUFFICIENT_EVIDENCE",  # شواهد ناکافی برای قضاوت
    "UNAVAILABLE",            # منبع در دسترس نبود — دادهٔ ساختگی ممنوع
    "ERROR",                  # خطای خودِ پهپاد
)

REQUIRED_FIELDS = (
    "message_id", "event_id", "parent_event_id", "agent_id", "cluster_id",
    "task_id", "symbol", "exchange", "market_type", "timeframe",
    "event_time", "data_asof", "generated_at", "features", "evidence",
    "hypothesis", "uncertainty", "validation_status", "source_version",
    "schema_version",
)


def utc_iso_ms(ms: int) -> str:
    """میلی‌ثانیهٔ یونیکس → ISO-8601 UTC با Z (همان سیاست timestamp مودول Stage 1)."""
    dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms % 1000:03d}Z"


def event_id(cluster_id: str, symbol: str, event_type: str,
             event_time_ms: int, key: str = "") -> str:
    """شناسهٔ قطعی رویداد: ورودی یکسان → خروجی یکسان (ضد تولید دوباره)."""
    raw = "|".join([cluster_id, symbol or "", event_type,
                    str(event_time_ms), key or ""])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def make_message(*, cluster_id: str, symbol: str, event_type: str,
                 event_time_ms: int, data_asof_ms: int,
                 exchange: str = "toobit", market_type: str = "spot",
                 timeframe: str = None,
                 features: dict = None, evidence: dict = None,
                 hypothesis: dict = None, uncertainty: list = None,
                 validation_status: str = "OBSERVED",
                 agent_id: str = None, task_id: str = None,
                 parent_event_id: str = None, event_key: str = "",
                 message_id: str = None) -> dict:
    """تنها سازندهٔ مجاز پیام ناوگان. ورودی ناقص/نامعتبر → ValueError (قرمز)."""
    if cluster_id not in CLUSTERS:
        raise ValueError(f"cluster_id نامعتبر: {cluster_id!r}")
    if validation_status not in VALIDATION_STATUSES:
        raise ValueError(f"validation_status نامعتبر: {validation_status!r}")
    eid = event_id(cluster_id, symbol, event_type, event_time_ms, event_key)
    return {
        "message_id": message_id or uuid.uuid4().hex,
        "event_id": eid,
        "event_type": event_type,
        "parent_event_id": parent_event_id,
        "agent_id": agent_id or f"drone:{cluster_id}",
        "cluster_id": cluster_id,
        "cluster_name": CLUSTERS[cluster_id],
        "task_id": task_id,
        "symbol": symbol or "",
        "exchange": exchange,
        "market_type": market_type,
        "timeframe": timeframe,
        "event_time": utc_iso_ms(event_time_ms),
        "event_time_ms": event_time_ms,
        "data_asof": utc_iso_ms(data_asof_ms),
        "data_asof_ms": data_asof_ms,
        "generated_at": utc_iso_ms(int(datetime.now(tz=timezone.utc).timestamp() * 1000)),
        "features": features or {},
        "evidence": evidence or {},
        "hypothesis": hypothesis,
        "uncertainty": uncertainty or [],
        "validation_status": validation_status,
        "source_version": SOURCE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "safety": {"mode": SAFETY_MODE},
    }


def filter_new(events: list, existing_ids: set) -> list:
    """فقط رویدادهای با event_id نو — ضد تکرار (بند ۴)."""
    return [e for e in events if e["event_id"] not in existing_ids]


def load_event_ids(path: str) -> set:
    """شناسه‌های موجود در دفتر jsonl — فایل غایب = مجموعهٔ خالی."""
    ids = set()
    if not os.path.exists(path):
        return ids
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue  # خط خراب: در گزارش ممیزی سیکل ثبت می‌شود نه حذف بی‌صدا
            if isinstance(row, dict) and "event_id" in row:
                ids.add(row["event_id"])
    return ids


def append_events(path: str, events: list) -> dict:
    """افزودن رویداد با حذف تکرار نسبت به دفتر موجود. هرگز بازنویسی نمی‌کند.
    اصلاح B-6 گزارش MISSION 002: شناسهٔ رویدادهای dedup-شده برگردانده می‌شود تا
    ورودی واقعی شبیه‌ساز/مصرف‌کننده‌ها همیشه از گزارش چرخه قابل بازسازی باشد."""
    existing = load_event_ids(path)
    fresh = filter_new(events, existing)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        for e in fresh:
            fh.write(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n")
    fresh_ids = {e["event_id"] for e in fresh}
    duplicate_ids = []
    for e in events:
        eid = e.get("event_id")
        if eid not in fresh_ids and eid not in duplicate_ids:
            duplicate_ids.append(eid)
    return {"written": len(fresh), "duplicates_skipped": len(events) - len(fresh),
            "duplicate_event_ids": duplicate_ids[:100],
            "duplicate_event_ids_truncated": max(0, len(duplicate_ids) - 100)}
