# MARI — hypothesis_lab: راستی‌آزمایی مستقل دفترچهٔ فرض‌های AI — حلقهٔ M-6
# MODE: READ ONLY | PAPER ONLY | NO LIVE ORDERS
#
# خاستگاه: شکاف M-6 ممیزی EXECUTION ORDER 001 + بند ۴ AI_CLUSTER_PLAN
# («هر خروجی AI بدون اعتبارسنجی مستقل هرگز قابل‌اعتماد نیست») + تصمیم رییس
# (2026-10-25) برای سیم‌کشی دفترچهٔ فرضیه. دفترچهٔ ai-hypotheses.jsonl فقط
# نوشته می‌شد و هرگز محک زده نمی‌شد — این ماژول حلقه را می‌بندد:
# هر ادعای عددیِ قابل‌عبارت‌یابی، مستقلاً روی کندل آرشیو بازمحاسبه و با
# تلورانس اعلام‌شده مقایسه می‌شود. هیچ ادعایی پذیرفته یا رد «جعل» نمی‌شود؛
# فرض‌های غیرقابل‌عبارت‌یابی صادقانه UNVERIFIABLE می‌گیرند.
# ورودی: ردیف‌های JSONL دفترچه (بارگذاری با آزمون/دودآزمون) + کندل آرشیو.
# خروجی: فقط‌گزارشی — بدون شبکه، بدون نوشتن فایل، قطعی، بدون مهر زمانی.

import json
import re

from . import quant
from . import sessions

LAB_METHOD = "hypothesis_lab/independent_recheck_v1"
DEFAULT_WINDOW = 200           # پنجرهٔ بازمحاسبه — هم‌راستا با limit اسکن
DEFAULT_REL_TOLERANCE = 0.05   # تلورانس بازتولید — اعلام‌شده، نه جعلی
MIN_CANDLES = 66               # حداقل کندل پنجره (هورست ≥ دو مقیاس ۸/۱۶)

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")

# الگوهای شناخته‌شدهٔ بیانیه — متن آزاد فارسی؛ فقط سه خانوادهٔ عبارت‌پذیر
_METRIC_RULES = (
    ("EWMA_VOL_PER_BAR", ("EWMA", "هیست اکسپوننشیال")),
    ("HURST", ("هرست",)),
    ("SESSION_RANGE_MEAN", ("سشن نیویورک",)),
)


def parse_claim(statement: str) -> dict:
    """عبارت‌یابی ادعا از بیانیهٔ فارسی — خروجی قطعی: metric/value/regime."""
    out = {"metric": None, "value": None, "regime": None}
    if not isinstance(statement, str) or not statement.strip():
        return out
    for metric, needles in _METRIC_RULES:
        if any(n in statement for n in needles):
            out["metric"] = metric
            break
    if "TRENDING_CANDIDATE" in statement:
        out["regime"] = "TRENDING_CANDIDATE"
    elif "MEAN_REVERTING_CANDIDATE" in statement:
        out["regime"] = "MEAN_REVERTING_CANDIDATE"
    nums = _NUM_RE.findall(statement)
    if nums:
        out["value"] = float(nums[-1])
    return out


def _window_before_asof(candles: list, asof_ms: int, window: int) -> list:
    """کندل‌های بستهٔ پیش از asof (ضدنشت) — آخرین window تا، حفظ ترتیب."""
    past = [c for c in candles
            if isinstance(c.get("open_time"), int)
            and c["open_time"] < int(asof_ms)]
    return past[-int(window):] if past else []


def _recompute(metric: str, window_candles: list) -> "tuple":
    """بازمحاسبهٔ مستقل هر متریک — خروجی (عدد یا None، یادداشت)."""
    if metric == "EWMA_VOL_PER_BAR":
        rets = quant.log_returns(window_candles)
        return quant.ewma_volatility(rets), "ewma_lambda=0.94"
    if metric == "HURST":
        rets = quant.log_returns(window_candles)
        return quant.hurst_exponent(rets), "R/S blocks 8/16/32/64"
    if metric == "SESSION_RANGE_MEAN":
        ranges = [c["high"] - c["low"] for c in window_candles
                  if "NEWYORK" in sessions.session_tags(c["open_time"])]
        if not ranges:
            return None, "NO_NEWYORK_CANDLES_IN_WINDOW"
        return sum(ranges) / len(ranges), \
            "mean(high-low) of NEWYORK candles — DEFINITION_ASSUMED"
    return None, "UNKNOWN_METRIC"


def evaluate_hypotheses(rows: list, candles_map: dict, *,
                        window: int = DEFAULT_WINDOW,
                        rel_tolerance: float = DEFAULT_REL_TOLERANCE) -> dict:
    """مقایسهٔ هر ادعا با بازمحاسبهٔ مستقل — حکم فقط REPORTED.
    حکم‌ها: REPRODUCED / NOT_REPRODUCED / UNVERIFIABLE_* — هیچ چیز جعل نمی‌شود."""
    base = {
        "method": LAB_METHOD,
        "recompute_engine": quant.METHOD,
        "mode": "READ ONLY | PAPER ONLY | NO LIVE ORDERS",
        "window": int(window),
        "rel_tolerance": rel_tolerance,
        "n_hypotheses": len(rows),
        "results": [],
        "summary": {},
        "verdict": "REPORTED",
        "limitations": [
            "بیانیه‌ها متن آزاد فارسی‌اند؛ فقط سه خانوادهٔ عبارت‌پذیر محک زده "
            "می‌شوند — بقیه صادقانه UNVERIFIABLE_CLAIM_UNPARSED می‌گیرند",
            "تعریف «نوسان میانگین سشن» در بیانیه مشخص نشده — mean(high-low) "
            "فرض شد (DEFINITION_ASSUMED)؛ بازتولید دقیق نیازمند spec نویسنده است",
            "پنجرهٔ بازمحاسبه (کندل ۱ساعتهٔ پیش از data_asof) فرض پژوهشی است؛ "
            "اگر فرض AI پنجرهٔ دیگری بوده، اختلاف طبیعی است و در تلورانس می‌ماند",
            "هومرست و EWMA روی بازده لگاریتمی کلوز هستند؛ گرد کردن بیانیه "
            "می‌تواند بخشی از اختلاف باشد",
            "خروجی فقط REPORTED است — هیچ آستانه‌ای موفقیت جعل نشده",
        ],
    }
    if not rows or not candles_map:
        return dict(base, verdict="INSUFFICIENT_EVIDENCE",
                    reason="EMPTY_INPUT_NO_ROWS_OR_CANDLES")
    counts = {}
    for row in rows:
        claim = parse_claim((row.get("features") or {}).get("statement"))
        metric = claim["metric"]
        symbol = row.get("symbol")
        notes = []
        if metric is None or claim["value"] is None:
            verdict = "UNVERIFIABLE_CLAIM_UNPARSED"
            result = {"metric": metric, "claimed": claim["value"],
                      "recomputed": None}
        elif symbol not in candles_map:
            verdict = "UNVERIFIABLE_SYMBOL_MISSING"
            result = {"metric": metric, "claimed": claim["value"],
                      "recomputed": None}
        else:
            wc = _window_before_asof(candles_map[symbol],
                                     row.get("data_asof_ms") or 0, window)
            if len(wc) < MIN_CANDLES:
                verdict = "UNVERIFIABLE_INSUFFICIENT_HISTORY"
                result = {"metric": metric, "claimed": claim["value"],
                          "recomputed": None,
                          "n_window_candles": len(wc)}
            else:
                recomputed, note = _recompute(metric, wc)
                if note == "DEFINITION_ASSUMED":
                    notes.append(note)
                if recomputed is None:
                    verdict = "UNVERIFIABLE_RECOMPUTE_NULL"
                    result = {"metric": metric, "claimed": claim["value"],
                              "recomputed": None,
                              "n_window_candles": len(wc),
                              "note": note}
                else:
                    claimed = claim["value"]
                    rel = abs(recomputed - claimed) / abs(claimed)
                    verdict = "REPRODUCED" if rel <= rel_tolerance \
                        else "NOT_REPRODUCED"
                    result = {"metric": metric, "claimed": claimed,
                              "recomputed": round(recomputed, 8),
                              "abs_diff": round(recomputed - claimed, 8),
                              "rel_diff_pct": round(rel * 100.0, 4),
                              "n_window_candles": len(wc),
                              "note": note}
                    if metric == "HURST":
                        regime_rc = "TRENDING_CANDIDATE" \
                            if recomputed >= quant.HURST_TREND else \
                            ("MEAN_REVERTING_CANDIDATE"
                             if recomputed <= quant.HURST_REVERT else "MIXED")
                        result["regime_claimed"] = claim["regime"]
                        result["regime_recomputed"] = regime_rc
                        if claim["regime"] and claim["regime"] != regime_rc:
                            notes.append("REGIME_MISMATCH_NOTED")
        result_full = {"event_id": row.get("event_id"),
                       "symbol": symbol,
                       "data_asof_ms": row.get("data_asof_ms"),
                       "verdict": verdict, **result}
        if notes:
            result_full["notes"] = notes
        base["results"].append(result_full)
        counts[verdict] = counts.get(verdict, 0) + 1
    base["summary"] = counts
    return base


def load_ledger(path: str) -> list:
    """بارگذار JSONL دفترچه — فقط برای آزمون/دودآزمون؛ خود ماژول فایل نمی‌خواند."""
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def canonical_json(report: dict) -> str:
    """نمایش قطعی برای آزمون بازتولیدپذیری (کل خروجی بدون مهر زمانی است)."""
    return json.dumps(report, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
