# موتور یادگیری‌سنج — بند ۷ پلن خوشهٔ AI: اعتبارسنجی خروجی‌های تحلیلی
# علیه داده‌های تاریخی. نسخهٔ mari.learning/v1.
# وظیفه: ثبت پیش‌بینی‌های جهت‌دار موتور داوری ۴وضعیتی با «قیمت مرجع» در یک
# دفتر الحاقی (append-only)، و حل‌وفصل آن‌ها در چرخه‌های بعد با بازده
# پیش‌روی واقعی همان دارایی (کندل بستهٔ تازه، وگرنه قیمت ردیف دفتر).
# اصل صادقگی:
#   - تا رسیدن نمونه‌های هر کلاس به MIN_SAMPLES، فقط INSUFFICIENT_EVIDENCE.
#   - uptrend_rejected ادعای جهت‌دار نیست → ثبت می‌شود ولی هرگز حل‌وفصل نمی‌شود.
#   - هیچ خروجی این موتور سیگنال معامله نیست؛ فقط سنجهٔ اعتبارسنجی است.
#   - دادهٔ اصلی پژوهش هرگز تغییر نمی‌کند؛ دفتر یادگیری دادهٔ افزودهٔ کاغذی است.
# READ ONLY | PAPER ONLY | NO LIVE ORDERS

import json
import os

from .contract import make_message

LEARNING_VERSION = "mari.learning/v1"
# پارامتر شفاف و نسخه‌دار — همان قاعدهٔ سقف ادعا در ارزیاب کاغذی (بند ۵).
MIN_SAMPLES = 30
# کلاس‌های جهت‌دار قابل حل‌وفصل؛ uptrend_rejected عمداً غایب است.
SCORED_CLASSES = ("uptrend_confirmed", "opportunity", "rising_obs",
                  "falling_obs")

LEDGER_FILE = "learning-ledger.jsonl"
LATEST_FILE = "learning-latest.json"


# ---------- استخراج پیش‌بینی از داوری‌های یک چرخه ----------

def extract_predictions(judgments: list, rows: list,
                        candles_map: dict) -> dict:
    """از داوری‌ها فقط ادعاهای جهت‌دارِ قابل سنجش را بیرون می‌کشد.
    قیمت مرجع: آخرین کندل بستهٔ همان چرخه، وگرنه price_usd ردیف دفتر.
    بدون هیچ‌کدام → پیش‌بینی ثبت نمی‌شود و علتش شمرده می‌شود (صادقانه)."""
    candle_hit = {}
    for s, candles in (candles_map or {}).items():
        candle_hit[f"cex:toobit:spot:{s}"] = candles
        candle_hit[s] = candles  # سازگاری با asset_id Toobit
    price_of = {}
    row_candles = {}  # هویت‌های غیر-Toobit: پیوند از طریق نماد ردیف دفتر
    for r in rows or []:
        key = r.get("identity") or r.get("asset_id")
        if not key:
            continue
        price_of.setdefault(key, r.get("price_usd"))
        sym_c = (candles_map or {}).get(r.get("symbol"))
        if sym_c and key not in candle_hit:
            row_candles[key] = sym_c

    predictions = []
    skipped = {"no_price_reference": 0, "no_directional_claim": 0}
    for j in judgments or []:
        ident = j.get("identity") or j.get("asset_id")
        if not ident:
            continue
        cls, direction = None, None
        if (j.get("uptrend") or {}).get("state") is True:
            cls, direction = "uptrend_confirmed", "long"
        elif (j.get("opportunity") or {}).get("state") is True:
            cls, direction = "opportunity", "long"
        elif j.get("price_rising") is True:
            cls, direction = "rising_obs", "long"
        elif j.get("price_rising") is False:
            cls, direction = "falling_obs", "short"
        elif (j.get("uptrend") or {}).get("state") is False:
            skipped["no_directional_claim"] += 1
            continue
        else:
            skipped["no_directional_claim"] += 1
            continue
        # قیمت مرجع — کندل بسته مقدم است (همان شواهد داوری ساختار)
        ref_price, ref_source = None, None
        candles = candle_hit.get(ident) or row_candles.get(ident)
        if candles:
            ref_price, ref_source = candles[-1]["close"], "closed_candle"
        elif price_of.get(ident) is not None:
            ref_price, ref_source = price_of[ident], "row_price"
        if not ref_price or ref_price <= 0:
            skipped["no_price_reference"] += 1
            continue
        predictions.append({
            "v": LEARNING_VERSION,
            "prediction_id": f"{ident}:{cls}",
            "identity": ident, "symbol": j.get("symbol"),
            "class": cls, "direction": direction,
            "ref_price": ref_price, "ref_source": ref_source,
            "asof_ms": j.get("data_asof_ms"),
            "state": "pending",
        })
    return {"predictions": predictions, "skipped": skipped}


# ---------- دفتر الحاقی ----------

def _ledger_path(state_dir: str) -> str:
    return os.path.join(state_dir, LEDGER_FILE)


def _load_ledger(state_dir: str) -> list:
    path = _ledger_path(state_dir)
    if not os.path.exists(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _save_ledger(state_dir: str, records: list) -> str:
    path = _ledger_path(state_dir)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    return path


def record_cycle(predictions: list, *, asof_ms: int,
                 state_dir: str = None) -> dict:
    """پیش‌بینی‌های چرخه را به دفتر الحاقی می‌بندد (تکرارِ prediction_id
    در همان دور ثبت نمی‌شود — دفتر ایدمپوتنت است)."""
    if not state_dir:
        return {"recorded": 0, "duplicates": 0}
    ledger = _load_ledger(state_dir)
    seen = {r["prediction_id"] for r in ledger}
    recorded, duplicates = 0, 0
    with open(_ledger_path(state_dir), "a", encoding="utf-8") as fh:
        for p in predictions or []:
            if p["prediction_id"] in seen:
                duplicates += 1
                continue
            seen.add(p["prediction_id"])
            fh.write(json.dumps({**p, "recorded_ms": asof_ms},
                                ensure_ascii=False) + "\n")
            recorded += 1
    return {"recorded": recorded, "duplicates": duplicates}


# ---------- حل‌وفصل با بازده پیش‌رو ----------

def _fresh_price_map(rows: list, candles_map: dict) -> dict:
    hit = {}
    for s, candles in (candles_map or {}).items():
        hit[f"cex:toobit:spot:{s}"] = ("closed_candle", candles[-1]["close"])
        hit[s] = ("closed_candle", candles[-1]["close"])
    for r in rows or []:
        key = r.get("identity") or r.get("asset_id")
        if not key or key in hit:
            continue
        sym_c = (candles_map or {}).get(r.get("symbol"))
        if sym_c:  # کندل بستهٔ نماد مقدم بر قیمت ردیف است
            hit[key] = ("closed_candle", sym_c[-1]["close"])
        elif r.get("price_usd"):
            hit[key] = ("row_price", r["price_usd"])
    return hit


def resolve_cycle(rows: list, candles_map: dict, *, asof_ms: int,
                  state_dir: str = None) -> dict:
    """هر پیش‌بینی pending که دارایی‌اش در دادهٔ تازهٔ همین چرخه حاضر است،
    با بازده پیش‌رو حل می‌شود. جهت long: بازده > 0 درست؛ short: < 0 درست؛
    صفر دقیق → flat (نه درست نه غلط، صادقانه جدا شمرده می‌شود).
    uptrend_rejected هرگز حل نمی‌شود (ادعای جهت‌دار نیست)."""
    if not state_dir:
        return {"resolved": 0, "flat": 0, "still_pending": 0}
    fresh = _fresh_price_map(rows, candles_map)
    ledger = _load_ledger(state_dir)
    resolved = flat = 0
    for rec in ledger:
        if rec.get("state") != "pending":
            continue
        if rec.get("class") not in SCORED_CLASSES:
            continue  # uptrend_rejected — بدون ادعای جهت، بی‌حل‌وفصل
        fx = fresh.get(rec.get("identity"))
        if not fx:
            continue
        src, price = fx
        ret = (price - rec["ref_price"]) / rec["ref_price"]
        rec["forward_return_pct"] = round(ret * 100, 6)
        rec["correct"] = (ret > 0) if rec["direction"] == "long" \
            else (ret < 0) if rec["direction"] == "short" else None
        rec["resolution_source"] = src
        rec["resolved_ms"] = asof_ms
        rec["state"] = "resolved"
        if rec["correct"] is None:
            flat += 1
        else:
            resolved += 1
    still_pending = sum(1 for r in ledger if r.get("state") == "pending")
    _save_ledger(state_dir, ledger)
    return {"resolved": resolved, "flat": flat,
            "still_pending": still_pending}


# ---------- خلاصهٔ یادگیری + رویداد قراردادی ----------

def learning_summary(*, asof_ms: int, task_id: str = None,
                     state_dir: str = None,
                     min_samples: int = MIN_SAMPLES) -> dict:
    """نرخ اصابت به‌تفکیک کلاس — فقط شمارش خام تا MIN_SAMPLES؛
    بعد از آن هم خروجی «مشاهدهٔ اندازه‌گیری‌شده» است، نه موفقیت."""
    ledger = _load_ledger(state_dir) if state_dir else []
    by_class = {}
    for rec in ledger:
        if rec.get("state") != "resolved":
            continue
        cls = rec.get("class")
        slot = by_class.setdefault(
            cls, {"n": 0, "hits": 0, "misses": 0, "flat": 0})
        slot["n"] += 1
        if rec.get("correct") is True:
            slot["hits"] += 1
        elif rec.get("correct") is False:
            slot["misses"] += 1
        else:
            slot["flat"] += 1
    classes = {}
    for cls, slot in sorted(by_class.items()):
        enough = slot["n"] >= min_samples
        classes[cls] = {
            **slot,
            "hit_rate": round(slot["hits"] / slot["n"], 4)
            if enough else None,
            "verdict": "observation_only" if enough
            else "insufficient_evidence",
        }
    pending = sum(1 for r in ledger if r.get("state") == "pending")
    summary = {
        "version": LEARNING_VERSION, "asof_ms": asof_ms,
        "min_samples_required": min_samples,
        "resolved_total": sum(s["n"] for s in by_class.values()),
        "pending_total": pending,
        "classes": classes,
        "rule": "هیچ نرخ اصابتی سیگنال معامله نیست؛ این سنجه فقط "
                "اعتبارسنجی خروجی تحلیلی علیه تاریخ است (بند ۷)",
    }
    ev = make_message(
        cluster_id="N", symbol="LEARNING",
        event_type="LEARNING_SUMMARY",
        event_time_ms=asof_ms, data_asof_ms=asof_ms,
        market_type="aggregated", exchange="multi",
        features={"summary": summary},
        uncertainty=["نمونه‌های کمتر از حد سقف ادعا → فقط "
                     "INSUFFICIENT_EVIDENCE",
                     "حل‌وفصل روی بازده پیش‌روی همان چرخه بعدی است، نه "
                     "پنجرهٔ چندچرخه‌ای",
                     "دارایی‌های غایب در چرخه‌های بعد pending می‌مانند"],
        evidence={"method": LEARNING_VERSION,
                  "source": "learning-ledger.jsonl (append-only, paper)"},
        task_id=task_id, event_key=f"learning:{asof_ms}")

    if state_dir:
        try:
            doc = {**summary, "event": {"event_type": "LEARNING_SUMMARY",
                                        "event_key": f"learning:{asof_ms}"}}
            path = os.path.join(state_dir, LATEST_FILE)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError:
            pass  # دیسک ناسالم — رویداد همچنان صادقانه صادر می‌شود
    return {"summary": summary, "event": ev}
