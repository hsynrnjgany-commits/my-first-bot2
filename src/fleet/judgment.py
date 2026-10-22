# موتور داوری ۴وضعیتی — بند ۴ دستور WORLD MARKET CORE
# چهار وضعیت مستقل برای هر دارایی (استقلال واقعی، نه آبشاری):
#   ۱) price_rising — مشاهدهٔ خالص تغییر مثبت قیمت روی پنجره‌های تازه.
#      «صرفِ رشد قیمت هرگز سیگنال خرید نیست» — فقط مشاهده ثبت می‌شود.
#   ۲) uptrend — ساختار صعودی (سقف‌های بالاتر + کف‌های بالاتر) فقط روی
#      کندل‌های بسته‌شدهٔ همان چرخه. بدون کندل → unverified، هیچ حدسی نیست.
#   ۳) opportunity — فقط با روند تأییدشده + شواهد نقدینگی/حجم. رشد قیمت
#      به‌تنهایی هرگز opportunity نمی‌سازد (آزمون استقلال بند ۴).
#   ۴) hypothesis — unverified | rejected با علت صادقانه (دادهٔ ناقص، کهنه،
#      بی‌حجم، استیبل). هیچ داراییِ بی‌داده صعودی/نزولی فرض نمی‌شود.
# ورودی: ردیف‌های دفتر جهانی خوشهٔ N + نگاشت کندل‌های بستهٔ پاک همان چرخه.
# خروجی: داوری per-asset + رویداد قراردادی JUDGMENT_SUMMARY + فایل ماندگار.
# READ ONLY | PAPER ONLY | NO LIVE ORDERS

import json
import os

from .contract import make_message

JUDGMENT_VERSION = "mari.judgment/v1"
# شواهد حداقلی نقدینگی/حجم برای اعطای opportunity — پارامتر شفاف و
# نسخه‌بندی‌شده، نه «حقیقت بازار». تغییر فقط با نسخهٔ جدید.
OPPORTUNITY_MIN_USD_VOL = 100_000.0
# پنجرهٔ ساختار: حداقل کندل بسته و طول همسایگی سوئینگ
SWING_NEIGHBORS = 2
MIN_CANDLES_STRUCTURE = 10
SWING_WINDOW_MAX = 80


# ---------- ساختار بازار روی کندل بسته ----------

def swings(candles: list, neighbors: int = SWING_NEIGHBORS) -> dict:
    """سقف/کف‌های سوئینگ روی کندل‌های بسته — ورودی مرتب‌سازی می‌شود.
    سوئینگ اکسترممِ محلی با «neighbors» همسایه در هر طرف است."""
    cs = sorted(candles or [], key=lambda c: c.get("open_time") or 0)
    highs, lows = [], []
    n = len(cs)
    for i in range(neighbors, n - neighbors):
        win = cs[i - neighbors:i + neighbors + 1]
        h, l = cs[i]["high"], cs[i]["low"]
        if h > max(x["high"] for x in win if x is not cs[i]) and \
           h >= max(x["high"] for x in win):
            highs.append((i, h))
        if l < min(x["low"] for x in win if x is not cs[i]) and \
           l <= min(x["low"] for x in win):
            lows.append((i, l))
    return {"swing_highs": highs, "swing_lows": lows}


def uptrend_structure(candles: list) -> dict:
    """True فقط با HH+HL روی کندل بسته + بسته‌شدن بالای آخرین کف سوئینگ.
    False = ساختار تأیید نشد (شکسته یا نزولی). None = قابل داوری نیست."""
    if not candles or len(candles) < MIN_CANDLES_STRUCTURE:
        return {"state": None, "method": "hh_hl_closed_candles",
                "reason": "insufficient_closed_candles",
                "candles_used": len(candles or [])}
    cs = sorted(candles, key=lambda c: c.get("open_time") or 0)
    cs = cs[-SWING_WINDOW_MAX:]
    sw = swings(cs)
    shs, sls = sw["swing_highs"], sw["swing_lows"]
    if len(shs) < 2 or len(sls) < 2:
        return {"state": None, "method": "hh_hl_closed_candles",
                "reason": "fewer_than_two_swings",
                "swing_highs": len(shs), "swing_lows": len(sls)}
    hh = shs[-1][1] > shs[-2][1]
    hl = sls[-1][1] > sls[-2][1]
    last_low = sls[-1][1]
    close_now = cs[-1]["close"]
    intact = close_now > last_low
    if hh and hl and intact:
        return {"state": True, "method": "hh_hl_closed_candles",
                "last_swing_high": shs[-1][1], "prev_swing_high": shs[-2][1],
                "last_swing_low": last_low, "prev_swing_low": sls[-2][1],
                "close_above_last_low": True,
                "candles_used": len(cs)}
    reason = ("structure_broken_close_below_last_low" if (hh and hl)
              else "no_higher_highs_and_lows")
    return {"state": False, "method": "hh_hl_closed_candles",
            "reason": reason,
            "last_swing_high": shs[-1][1], "prev_swing_high": shs[-2][1],
            "last_swing_low": last_low, "prev_swing_low": sls[-2][1],
            "close_above_last_low": intact, "candles_used": len(cs)}


# ---------- داوری یک ردیف دفتر ----------

def judge_row(row: dict, candles: list = None) -> dict:
    """۴ وضعیت مستقل برای یک ردیف — بدون هیچ تبدیل خودکار به سیگنال."""
    q = row.get("quality") or {}
    ch = row.get("change_pct") or {}
    base = {
        "identity": row.get("identity"),
        "symbol": row.get("symbol"),
        "kind": row.get("kind"),
        "network": row.get("network"),
        "stablecoin": bool(row.get("stablecoin")),
        "wrapped_hint": bool(row.get("wrapped_hint")),
        "primary_source": row.get("primary_source"),
        "data_asof_ms": row.get("data_asof_ms"),
    }

    # ۰) دادهٔ ناقص/ناسالم → rejected با علت؛ هیچ وضعیت جهت‌داری صادر نمی‌شود
    if not q.get("has_price"):
        return {**base, "price_rising": None, "uptrend": None,
                "opportunity": None,
                "hypothesis": {"state": "rejected",
                               "reason": "no_price_data"}}
    if q.get("stale_price"):
        return {**base, "price_rising": None, "uptrend": None,
                "opportunity": None,
                "hypothesis": {"state": "rejected",
                               "reason": "stale_price"}}
    if q.get("zero_volume"):
        return {**base, "price_rising": None, "uptrend": None,
                "opportunity": None,
                "hypothesis": {"state": "rejected",
                               "reason": "zero_volume"}}

    # ۱) price_rising — مشاهدهٔ خالص روی پنجره‌های موجود و تازه
    pos = [w for w in ("1h", "24h", "7d", "30d") if
           isinstance(ch.get(w), (int, float)) and ch.get(w) > 0]
    neg = [w for w in ("1h", "24h", "7d", "30d") if
           isinstance(ch.get(w), (int, float)) and ch.get(w) < 0]
    price_rising = True if pos else (False if neg else None)

    # ۲) uptrend — فقط با کندل بسته؛ بدون کندل هیچ‌گاه True نمی‌شود
    if candles:
        up = uptrend_structure(candles)
    else:
        up = {"state": None, "method": "hh_hl_closed_candles",
              "reason": "no_candles_in_cycle"}

    # ۳) opportunity — نیاز هم‌زمان: روند تأییدشده + شواهد حجم/نقدینگی
    vol = row.get("volume_24h_usd")
    liq = row.get("liquidity_usd")
    if row.get("stablecoin"):
        opp = {"state": None, "reason": "stablecoin_not_opportunity"}
    elif up.get("state") is not True:
        opp = {"state": None,
               "reason": "uptrend_not_confirmed"}
    elif (vol or 0) >= OPPORTUNITY_MIN_USD_VOL or \
            (liq or 0) >= OPPORTUNITY_MIN_USD_VOL:
        opp = {"state": True,
               "evidence": {"volume_24h_usd": vol, "liquidity_usd": liq,
                            "min_usd_vol": OPPORTUNITY_MIN_USD_VOL}}
    else:
        opp = {"state": None,
               "reason": "liquidity_volume_below_floor",
               "evidence": {"volume_24h_usd": vol, "liquidity_usd": liq,
                            "min_usd_vol": OPPORTUNITY_MIN_USD_VOL}}

    # ۴) hypothesis — پیش‌فرض صادقانهٔ unverified با ثبت آنچه کم است
    miss = []
    if price_rising is None:
        miss.append("no_change_data")
    if up.get("state") is None:
        miss.append(up.get("reason", "no_candles_in_cycle"))
    if opp.get("state") is None and row.get("stablecoin") is not True:
        miss.append(opp.get("reason", "no_opportunity_evidence"))
    hyp = {"state": "unverified", "missing": miss}

    return {**base, "price_rising": price_rising,
            "rising_windows": pos, "falling_windows": neg,
            "uptrend": {k: v for k, v in up.items()},
            "opportunity": opp, "hypothesis": hyp}


# ---------- داوری یک چرخه ----------

def judge_cycle(rows: list, candles_map: dict, *, asof_ms: int,
                task_id: str = None, state_dir: str = None) -> dict:
    """داوری کل ردیف‌های دفتر + لایهٔ کندل-تأیید برای نمادهای همین چرخه.
    خروجی: judgments، خلاصه، رویداد قراردادی، فایل ماندگار."""
    judgments = []
    candle_hit = {}
    for s, candles in (candles_map or {}).items():
        candle_hit[f"cex:toobit:spot:{s}"] = candles
        candle_hit[s] = candles  # سازگاری با asset_id Toobit
    for r in rows or []:
        c = candle_hit.get(r.get("identity")) or \
            candle_hit.get(r.get("asset_id"))
        judgments.append(judge_row(r, candles=c))

    counts = {
        "total": len(judgments),
        "price_rising": sum(1 for j in judgments
                            if j["price_rising"] is True),
        "price_falling": sum(1 for j in judgments
                             if j["price_rising"] is False),
        "uptrend_confirmed": sum(1 for j in judgments
                                 if (j["uptrend"] or {}).get("state") is True),
        "uptrend_rejected": sum(1 for j in judgments
                                if (j["uptrend"] or {}).get("state") is False),
        "uptrend_unverified": sum(1 for j in judgments
                                  if (j["hypothesis"] or {}).get("state")
                                  != "rejected"
                                  and (j["uptrend"] or {}).get("state")
                                  is None),
        "opportunity": sum(1 for j in judgments
                           if (j["opportunity"] or {}).get("state") is True),
        "rejected": sum(1 for j in judgments
                        if (j["hypothesis"] or {}).get("state") == "rejected"),
    }
    # اثبات استقلال (بند ۴): هیچ opportunity بدون uptrend تأییدشده ممنوع
    for j in judgments:
        if (j["opportunity"] or {}).get("state") is True and \
                (j["uptrend"] or {}).get("state") is not True:
            raise ValueError("نقض استقلال وضعیت‌ها: opportunity بدون uptrend")

    def _brief(j):
        return {k: j.get(k) for k in
                ("identity", "symbol", "kind", "network",
                 "primary_source", "price_rising", "rising_windows")}

    candle_confirmed = [_brief(j) | {"uptrend": j["uptrend"],
                                     "opportunity": j["opportunity"]}
                        for j in judgments
                        if (j["uptrend"] or {}).get("state") in (True, False)]
    opportunities = [_brief(j) | {"evidence":
                                  (j["opportunity"] or {}).get("evidence")}
                     for j in judgments
                     if (j["opportunity"] or {}).get("state") is True]
    rejected_hist = {}
    for j in judgments:
        if (j["hypothesis"] or {}).get("state") == "rejected":
            rr = j["hypothesis"]["reason"]
            rejected_hist[rr] = rejected_hist.get(rr, 0) + 1

    summary = {"version": JUDGMENT_VERSION, "asof_ms": asof_ms,
               "counts": counts, "rejected_reasons": rejected_hist}
    doc = {**summary, "candle_confirmed": candle_confirmed,
           "opportunities": opportunities}

    ev = make_message(
        cluster_id="N", symbol="JUDGMENT",
        event_type="JUDGMENT_SUMMARY",
        event_time_ms=asof_ms, data_asof_ms=asof_ms,
        market_type="aggregated", exchange="multi",
        features={"summary": summary,
                  "candle_confirmed_count": len(candle_confirmed),
                  "opportunity_count": len(opportunities),
                  "rule": "صرف رشد قیمت هرگز سیگنال خرید نیست؛ "
                          "opportunity فقط با uptrend تأییدشده + شواهد "
                          "نقدینگی/حجم اعطا می‌شود"},
        uncertainty=["داوری بدون کندل بسته هرگز uptrend تأیید نمی‌کند",
                     "دارایی‌های خارج از صف این چرخه داوری نشده‌اند",
                     "آستانهٔ شواهد نقدینگی پارامتر شفاف نسخه‌دار است، "
                     "نه حقیقت بازار"],
        evidence={"method": JUDGMENT_VERSION,
                  "source": "cluster N registry + closed candles of cycle"},
        task_id=task_id, event_key=f"{asof_ms}")

    if state_dir:
        try:
            save_judgments(state_dir, doc)
        except OSError:
            pass  # دیسک ناسالم — رویداد همچنان صادقانه صادر می‌شود
    return {"judgments": judgments, "summary": summary, "event": ev,
            "opportunities": opportunities,
            "candle_confirmed": candle_confirmed}


def save_judgments(state_dir: str, doc: dict) -> str:
    path = os.path.join(state_dir, "judgments-latest.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False)
    os.replace(tmp, path)
    return path
