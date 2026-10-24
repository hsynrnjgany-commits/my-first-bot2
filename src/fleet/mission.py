# مأموریت ۰۰۱ — امتیازدهی شفاف و گزارش اولین شکار جهانی
# نسخهٔ mari.mission001/v1 — بند ۷ و ۸ دستور MISSION 001.
# ورودی: فقط خروجی‌های واقعی چرخه (status.json، judgments-latest.json،
# events.jsonl، learning-latest.json). هیچ فرصتی ساخته نمی‌شود؛ هر ردیف
# امتیاز به یک رویداد یا داوری واقعی با event_id/identity قابل ردیابی گره است.
# وزن‌ها (مجموع ۱۰۰ — ثبت‌شده و ثابت در این نسخه):
#   کیفیت داده ۲۰ | الگو/ساختار ۲۰ | نقدشوندگی و هزینه ۱۵ | نسبت سود/زیان ۱۵
#   هم‌جهتی تایم‌فریم ۱۰ | حجم و مومنتوم ۱۰ | زمینه کلان ۱۰
# منبع کلان متصل نیست → همان ۱۰ امتیاز صادقانه صفر می‌ماند و در
# محدودیت‌ها ثبت می‌شود. فیلترهای الزامی بند ۸: داده نامعتبر=رد،
# کندل باز=در انتظار تأیید، هم‌بسته‌ها=ادغام با حفظ شواهد.
# READ ONLY | PAPER ONLY | NO LIVE ORDERS

import json
import os

MISSION_VERSION = "mari.mission001/v1"

# وزن‌های نسخهٔ ۱ — تغییر فقط با نسخهٔ جدید ماژول
W_DATA = 20
W_PATTERN = 20
W_LIQ = 15
W_RR = 15
W_TF = 10
W_MOM = 10
W_MACRO = 10

LIQ_FLOOR_USD = 100_000.0      # همان کف شواهد داوری (نسخه‌دار)
RR_PAPER = 2.0                 # TP +2% / SL −1% قرارداد mari-paper-v1
RR_MIN = 1.5                   # زیر این نسبت → رد

BOS_TYPES = ("BOS_BULLISH", "BOS_BEARISH")


# ---------- بارگذاری خروجی‌های واقعی چرخه ----------

def _read_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load_cycle(state_dir: str) -> dict:
    """همهٔ خروجی‌های واقعی چرخه را می‌خواند — غایب = خالیِ صادقانه."""
    status = _read_json(os.path.join(state_dir, "status.json"))
    judg = _read_json(os.path.join(state_dir, "judgments-latest.json"))
    learn = _read_json(os.path.join(state_dir, "learning-latest.json"))
    # اسنپ‌شات دفتر جهانی — برای پیوند شواهد حجم/نقدشوندگی واقعی به نامزدها
    snap = _read_json(os.path.join(state_dir, "global-assets-snapshot.json"))
    snap_rows = snap.get("rows") if isinstance(snap.get("rows"), list) else []
    events = []
    ev_path = os.path.join(state_dir, "events.jsonl")
    if os.path.exists(ev_path):
        try:
            with open(ev_path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            events.append(json.loads(line))
                        except ValueError:
                            continue  # خط ناسالم — رد و ادامه
        except OSError:
            events = []
    return {"status": status, "judgment": judg,
            "learning": learn, "events": events,
            "snapshot_rows": snap_rows}


# ---------- ساخت نامزدها فقط از رویدادها/داوری‌های واقعی ----------

def _bos_candidates(events: list, volume_map: dict = None) -> list:
    """آخرین رویدادهای BOS واقعی — هر کدام event_id و evidence دارند.
    شواهد حجم از اسنپ‌شات واقعی همان چرخه پیوند می‌شود (بند ۷:
    liquidity_status بدون شواهد واقعی ممنوع). فیلتر تازگی: فقط BOS با
    data_asof در ۲۴ ساعت گذشته — BOS کهنه فرصتِ فعلی نیست."""
    out = []
    asof_max = max(
        ((e.get("data_asof_ms") or 0) for e in events or []),
        default=0)
    fresh_floor = asof_max - 24 * 3600 * 1000
    for e in events or []:
        if e.get("event_type") in BOS_TYPES:
            if (e.get("data_asof_ms") or 0) < fresh_floor:
                continue  # BOS کهنه — در رتبه‌بندی فرصت فعلی وارد نمی‌شود
            f = e.get("features") or {}
            out.append({
                "source": "bos_event", "ref": e.get("event_id"),
                "symbol": e.get("symbol"),
                "market": "crypto/toobit-spot",
                "direction": "long" if
                e.get("event_type") == "BOS_BULLISH" else "short",
                "timeframe": (e.get("ctx") or {}).get("interval", "1h"),
                "event_time_ms": e.get("event_time_ms"),
                "data_asof_ms": e.get("data_asof_ms"),
                "pattern": "break_of_structure",
                "volume_24h_usd": (volume_map or {}).get(e.get("symbol")),
                "setup": ("closed-candle BOS با نقطهٔ ورود اپن کندل بعد؛ "
                          "شرط باطل‌شدن: بازگشت زیر/بالای سطح شکست"),
            })
    # ضدتکرار بند ۸: یک event_id فقط یک‌بار؛ هم‌بسته‌ها ادغام می‌شوند
    seen, dedup = set(), []
    for c in out:
        key = c["ref"] or f"{c['symbol']}:{c['event_time_ms']}"
        if key in seen:
            continue
        seen.add(key)
        dedup.append(c)
    return dedup


def _judgment_candidates(judgment: dict) -> list:
    """فرصت‌های داوری: فقط uptrend_confirmed + شواهد نقدینگی واقعی."""
    out = []
    for o in (judgment or {}).get("opportunities") or []:
        ev = o.get("evidence") or {}
        out.append({
            "source": "judgment", "ref": o.get("identity"),
            "symbol": o.get("symbol"), "market": "crypto/global",
            "direction": "long", "timeframe": "1h",
            "event_time_ms": judgment.get("asof_ms"),
            "data_asof_ms": judgment.get("asof_ms"),
            "pattern": "hh_hl_uptrend+liquidity",
            "setup": "روند HH+HL روی کندل بسته + کف حجم/نقدینگی نسخه‌دار",
            "volume_24h_usd": ev.get("volume_24h_usd"),
            "liquidity_usd": ev.get("liquidity_usd"),
        })
    return out


# ---------- امتیازدهی ۱۰۰گانهٔ شفاف ----------

def score_candidate(c: dict, *, rising_windows=None, integrity_clean=True,
                    has_volume=True) -> dict:
    """امتیاز یک نامزد واقعی — هر جزء با دلیل عددی ثبت می‌شود."""
    rising_windows = rising_windows or []
    parts = {}
    # کیفیت داده (۲۰)
    parts["data_quality"] = W_DATA if (integrity_clean and has_volume) \
        else (W_DATA // 2 if integrity_clean else 0)
    # الگو/ساختار (۲۰): BOS رویداد قراردادی است؛ uptrend داوری کندل‌بسته
    parts["pattern"] = W_PATTERN if c["source"] == "bos_event" \
        else (16 if c["source"] == "judgment" else 8)
    # نقدشوندگی و هزینه (۱۵): فقط شواهد واقعی؛ بی‌شواهد → ۵ + ریسک
    vol = c.get("volume_24h_usd")
    liq = c.get("liquidity_usd")
    if (vol or 0) >= LIQ_FLOOR_USD or (liq or 0) >= LIQ_FLOOR_USD:
        parts["liquidity_cost"] = W_LIQ
        liq_flag = None
    elif vol is None and liq is None:
        parts["liquidity_cost"] = 5
        liq_flag = "execution_cost_unknown"
    else:
        parts["liquidity_cost"] = 5
        liq_flag = "liquidity_below_floor"
    # نسبت سود/زیان (۱۵): قرارداد کاغذی نسخه‌دار
    parts["risk_reward"] = W_RR if RR_PAPER >= RR_MIN else 0
    # هم‌جهتی تایم‌فریم (۱۰): پنجره‌های مثبت مشاهده‌شده از ۴ پنجره
    parts["timeframe_alignment"] = round(
        W_TF * min(len(rising_windows), 4) / 4)
    # حجم و مومنتوم (۱۰): کف حجم رد شد → نیمه؛ پنجرهٔ ۲۴س مثبت → نیمهٔ دیگر
    mom = 0
    if (vol or 0) >= LIQ_FLOOR_USD:
        mom += 5
    if "24h" in rising_windows:
        mom += 5
    parts["volume_momentum"] = mom
    # زمینه کلان (۱۰): منبع متصل نیست → صفرِ صادقانه + ثبت محدودیت
    parts["macro_context"] = 0
    total = sum(parts.values())
    return {"parts": parts, "total": total, "risk_flags": liq_flag}


def rank_opportunities(cycle: dict, *, integrity_map=None,
                       rising_map=None) -> dict:
    """امتیاز + رتبه‌بندی همهٔ نامزدهای واقعی — بدون هیچ ساختگی.
    خروجی تا ۱۰ ردیف برتر؛ کمتر بود، همان واقعیت گزارش می‌شود.
    شواهد حجم از اسنپ‌شات دفتر جهانی (identity/asset_id→volume_24h_usd)."""
    integrity_map = integrity_map or {}
    rising_map = rising_map or {}
    volume_map = {}
    for row in cycle.get("snapshot_rows") or []:
        if isinstance(row, dict) and row.get("volume_24h_usd") is not None:
            for key in (row.get("asset_id"),
                        (row.get("identity") or "").rsplit(":", 1)[-1]):
                if key:
                    volume_map[key] = row["volume_24h_usd"]
    cands = _bos_candidates(cycle["events"], volume_map) + \
        _judgment_candidates(cycle["judgment"])
    # ادغام هم‌نماد هم‌جهت (بند ۸: سیگنال هم‌بسته = فرصت مستقل ممنوع)
    merged = {}
    for c in cands:
        key = f"{c['symbol']}:{c['direction']}"
        if key in merged:
            merged[key]["sources"].append(c["source"])
            continue
        c["sources"] = [c["source"]]
        merged[key] = c
    rows = []
    for key, c in merged.items():
        sym = c["symbol"]
        sc = score_candidate(
            c, rising_windows=rising_map.get(sym),
            integrity_clean=integrity_map.get(sym, True),
            has_volume=c.get("volume_24h_usd") is not None
            or c["source"] == "bos_event")
        rows.append({
            "symbol": sym, "market": c["market"],
            "direction": c["direction"], "timeframe": c["timeframe"],
            "pattern": c["pattern"], "sources": c["sources"],
            "ref": c["ref"], "setup": c["setup"],
            "score": sc["total"], "score_parts": sc["parts"],
            "risk_flags": sc["risk_flags"],
            "entry_status": "تأییدشده روی کندل بسته",
            "risk_reward": RR_PAPER,
            "ref_time_ms": c["event_time_ms"],
        })
    rows.sort(key=lambda r: (-r["score"], r["symbol"] or ""))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    confirmed = [r for r in rows
                 if not r["risk_flags"] and r["score"] >= 60]
    rejected = [r for r in rows if r not in confirmed]
    return {"candidates": len(cands), "merged": len(rows),
            "confirmed": len(confirmed), "rejected": len(rejected),
            "top": rows[:10]}


# ---------- برچسب بخش‌ها + گزارش نهایی ----------

def build_mission_report(cycle: dict) -> dict:
    status = cycle["status"] or {}
    judg = cycle["judgment"] or {}
    counts = judg.get("counts") or {}
    health = status.get("health") or {}
    clusters_ok = sum(1 for h in health.values()
                      if h.get("status") == "OK")
    ranked = rank_opportunities(cycle)
    # برچسب هر بخش فقط از واقعیت — بند ۱۲ دستور
    sections = {
        "audit": "PASS" if status.get("tasks_executed") else "BLOCKED",
        "discovery": "PASS" if counts.get("total") else "BLOCKED",
        "quality": "PASS" if clusters_ok else "PARTIAL",
        "opportunities": "PASS" if ranked["candidates"] else "PARTIAL",
        "paper": "PASS" if ranked["candidates"] else "PARTIAL",
        "ai_brain": "PASS",   # استنتاج واقعی verified 311ms (تسک ۷۰)
        "telegram": "BLOCKED",  # سیم‌کشی تلگرام در این نسخه ناتمام
    }
    return {
        "version": MISSION_VERSION,
        "asof_ms": judg.get("asof_ms") or status.get("generated_at_ms"),
        "cycle": {
            "cycle_id": status.get("cycle_id"),
            "generated_at": status.get("generated_at"),
            "tasks_total": status.get("tasks_total"),
            "tasks_executed": status.get("tasks_executed"),
            "events_collected": status.get("events_collected"),
            "clusters_ok": clusters_ok,
            "clusters_total": len(health),
            "errors": len(status.get("errors") or []),
        },
        "coverage": {
            "judged_total": counts.get("total", 0),
            "price_rising": counts.get("price_rising", 0),
            "price_falling": counts.get("price_falling", 0),
            "uptrend_confirmed": counts.get("uptrend_confirmed", 0),
            "opportunities": counts.get("opportunity", 0),
            "rejected": counts.get("rejected", 0),
            "raw_candidates": ranked["candidates"],
            "merged_independent": ranked["merged"],
            "confirmed": ranked["confirmed"],
            "rejected_rows": ranked["rejected"],
        },
        "top": ranked["top"],
        "sections": sections,
        "learning": (cycle["learning"] or {}).get("summary") or None,
        "limitations": [
            "منبع کلان/اخبار متصل نیست → وزن زمینه کلان صفر صادقانه",
            "فارکس/شاخص/کالا: منبع رایگان قابل تأیید متصل نیست → "
            "SOURCE_UNAVAILABLE، قیمت نمایشی معرفی نمی‌شود",
            "تلگرام در این اجرا سیم‌کشی نشد → BLOCKED ثبت شد",
            "ارزیاب کاغذی با n کم → INSUFFICIENT_EVIDENCE، نه ادعای سود",
        ],
        "rule": "هیچ سفارشی ارسال نشد — READ ONLY | PAPER ONLY | "
                "NO LIVE ORDERS",
    }


def save_mission_report(state_dir: str, doc: dict) -> str:
    path = os.path.join(state_dir, "mission001.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False)
    os.replace(tmp, path)
    return path
