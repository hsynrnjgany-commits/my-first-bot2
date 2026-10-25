# MARI — cost_model: واقع‌گرایی هزینهٔ اجرا (پروکسی اسپرد + لغزش) — فقط آفلاین
# MODE: READ ONLY | PAPER ONLY | NO LIVE ORDERS
#
# خاستگاه: اولویت P2 گزارش EXECUTION ORDER 001 (2026-10-25) — شکاف‌های M-1/M-5.
# این ماژول هیچ سیم‌کشی‌ای به چرخهٔ زندهٔ ناوگان ندارد و هیچ شبکه‌ای باز نمی‌کند؛
# روی خروجی evaluator.simulate_trades به‌صورت «پوشش هزینه» (cost overlay) کار
# می‌کند و منطق TP/SL/کارمزد شبیه‌ساز را یک حرف تغییر نمی‌دهد.
# برآورد اسپرد: Corwin-Schultz (Journal of Finance 2012, 67(2):719-760) از
# های/لوی کندل‌های متوالی — برچسب اجباری: PROXY؛ جایگزین دفتر سفارش نیست.
# هر خروجی فقط REPORTED یا INSUFFICIENT_EVIDENCE است — هیچ آستانه‌ای «موفقیت»
# جعل نمی‌شود. بدون مهر زمانی → خروجی قطعی و بازتولیدپذیر.

import json
import math

from . import evaluator

COST_METHOD = "cost_model/overlay_v1"
SPREAD_ESTIMATOR = "corwin_schultz_2012_high_low"
_SQRT2 = math.sqrt(2.0)
_CS_DENOM = 3.0 - 2.0 * _SQRT2  # ثابت ۳−۲√۲ در فرمول CS
DEFAULT_SLIPPAGE_BPS = (0, 5, 10, 20)


def _median(xs: list):
    """میانهٔ سادهٔ قطعی — لیست خالی → None."""
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


# ---------- پروکسی اسپرد (Corwin-Schultz 2012) ----------

def corwin_schultz_spread_bps(candles: list) -> "float | None":
    """پروکسی اسپرد بر حسب bps از جفت‌کندل‌های متوالی (های/لو).
    α منفی → صفر (توصیهٔ مقاله)؛ پنجرهٔ نامعتبر (قیمت غیرمثبت یا های<لو) پرش؛
    کمتر از دو کندل معتبر → None.
    برچسب: PROXY — روی دادهٔ روزانه طراحی شده و روی ۱ساعته فقط «مرتبهٔ
    بزرگی» می‌دهد؛ نوسان بالا را به اسپرد نسبت می‌دهد (سوگیری رو به بالا)."""
    spreads = []
    for i in range(1, len(candles)):
        a, b = candles[i - 1], candles[i]
        hi_a, lo_a = a.get("high"), a.get("low")
        hi_b, lo_b = b.get("high"), b.get("low")
        if None in (hi_a, lo_a, hi_b, lo_b):
            continue
        if min(hi_a, lo_a, hi_b, lo_b) <= 0 or hi_a < lo_a or hi_b < lo_b:
            continue
        beta = math.log(hi_b / lo_b) ** 2 + math.log(hi_a / lo_a) ** 2
        hi2, lo2 = max(hi_a, hi_b), min(lo_a, lo_b)
        gamma = math.log(hi2 / lo2) ** 2 if hi2 > lo2 else 0.0
        alpha = (math.sqrt(2.0 * beta) - math.sqrt(beta)) / _CS_DENOM \
            - math.sqrt(gamma / _CS_DENOM)
        if alpha < 0:
            alpha = 0.0
        spreads.append(2.0 * (math.exp(alpha) - 1.0)
                       / (1.0 + math.exp(alpha)))
    if not spreads:
        return None
    return round(_median(spreads) * 10_000, 4)


def half_cost_pct(spread_bps: float, slippage_bps: float) -> float:
    """هزینهٔ زیان‌سوی هر پا (اعشار): نصف اسپرد + لغزش سرانه."""
    return (spread_bps / 2.0 + slippage_bps) / 10_000


# ---------- پوشش هزینه روی معاملات شبیه‌ساز ----------

def apply_execution_costs(trades: list, *, spread_bps: float = 0.0,
                          slippage_bps: float = 0.0,
                          fee_pct: float = evaluator.FEE_PCT) -> list:
    """پوشش هزینهٔ اجرا — بدون تغییر منطق TP/SL شبیه‌ساز.
    لانگ: ورود در ask (گران‌تر با h)، خروج در bid (ارزان‌تر با h)؛ شورت قرینه.
    h = نصف اسپرد + لغزش. کارمزد با همان قرارداد ارزیاب: net = gross − 2×fee.
    در h=0 دقیقاً همان معاملهٔ اصلی بازتولید می‌شود (خاصیت آزمون‌شده)."""
    h = half_cost_pct(spread_bps, slippage_bps)
    out = []
    for t in trades:
        long = t.get("direction") == "long"
        entry, exitp = t["entry"], t["exit"]
        entry_eff = entry * (1.0 + h) if long else entry * (1.0 - h)
        exit_eff = exitp * (1.0 - h) if long else exitp * (1.0 + h)
        gross = (exit_eff - entry_eff) / entry_eff if long \
            else (entry_eff - exit_eff) / entry_eff
        net = gross - 2.0 * fee_pct
        out.append(dict(t, entry_eff=entry_eff, exit_eff=exit_eff,
                        gross_pct_adj=round(gross * 100, 6),
                        net_pct_adj=round(net * 100, 6)))
    return out


def realized_metrics(trades: list, *, key: str = "net_pct_adj") -> dict:
    """سنجه‌های realized فقط روی بسته‌های TP/SL — هم‌راستا با اصلاح A-2 ارزیاب."""
    closed = [t for t in trades if t.get("exit_reason") in ("TP", "SL")]
    nets = [t[key] for t in closed]
    wins = sum(1 for x in nets if x > 0)
    gw = sum(x for x in nets if x > 0)
    gl = abs(sum(x for x in nets if x < 0))
    return {
        "n_closed": len(closed),
        "n_open": len(trades) - len(closed),
        "profit_factor": round(gw / gl, 6) if gl > 0
        else ("UNDEFINED_NO_LOSSES" if gw > 0 else None),
        "win_rate": round(wins / len(closed), 4) if closed else None,
        "avg_net_pct": round(sum(nets) / len(nets), 6) if nets else None,
        "sum_net_pct": round(sum(nets), 6) if nets else None,
    }


# ---------- سناریوها و نقطهٔ سربه‌سر ----------

def scenario_grid(trades: list, *, spread_bps: float,
                  slippage_bps_list=DEFAULT_SLIPPAGE_BPS,
                  fee_pct: float = evaluator.FEE_PCT) -> dict:
    """جدول سناریوی لغزش — هر ردیف فقط REPORTED است، نه پیش‌بینی.
    baseline_zero_cost با صفر هزینه باید عین مدل کارمزدی ارزیاب باشد."""
    base = realized_metrics(apply_execution_costs(
        trades, spread_bps=0.0, slippage_bps=0.0, fee_pct=fee_pct))
    rows = []
    for slip in slippage_bps_list:
        m = realized_metrics(apply_execution_costs(
            trades, spread_bps=spread_bps, slippage_bps=float(slip),
            fee_pct=fee_pct))
        decay = None
        if base["sum_net_pct"] is not None and base["sum_net_pct"] > 0 \
                and m["sum_net_pct"] is not None:
            decay = round(100.0 * (1.0 - m["sum_net_pct"]
                                   / base["sum_net_pct"]), 4)
        rows.append(dict(slippage_bps=slip, **m, edge_decayed_pct=decay))
    return {"baseline_zero_cost": base, "rows": rows}


def break_even_slippage_bps(trades: list, *, spread_bps: float = 0.0,
                            fee_pct: float = evaluator.FEE_PCT,
                            hi_bps: float = 500.0, iters: int = 60) -> dict:
    """لغزش سرانهٔ سربه‌سر (bps، هر پا) با دوبخشی قطعی زیر مدل پوشش.
    مجموع خالص بسته‌ها نسبت به لغزش نانوصعودی است → دوبخشی بدون بذر.
    اگر در لغزش صفر هم مجموع ≤ ۰ باشد → ۰.۰ با پرچم صادقانه."""
    closed = [t for t in trades if t.get("exit_reason") in ("TP", "SL")]
    if not closed:
        return {"bps": None, "note": "NO_CLOSED_TRADES"}

    def total(slip_bps: float) -> float:
        adj = apply_execution_costs(closed, spread_bps=spread_bps,
                                    slippage_bps=slip_bps, fee_pct=fee_pct)
        return sum(t["net_pct_adj"] for t in adj)

    if total(0.0) <= 0:
        return {"bps": 0.0, "note": "NO_POSITIVE_EDGE_AT_ZERO_SLIPPAGE"}
    lo, hi = 0.0, float(hi_bps)
    for _ in range(int(iters)):
        mid = (lo + hi) / 2.0
        if total(mid) > 0:
            lo = mid
        else:
            hi = mid
    return {"bps": round((lo + hi) / 2.0, 4), "note": "BISECTION_DETERMINISTIC"}


# ---------- گزارش تلفیقی ----------

def cost_report(candles_map: dict, trades: list, *,
                fee_pct: float = evaluator.FEE_PCT,
                slippage_bps_list=DEFAULT_SLIPPAGE_BPS,
                min_samples: int = evaluator.MIN_SAMPLES) -> dict:
    """گزارش هزینهٔ اجرا: پروکسی اسپرد هر نماد + میانهٔ تلفیقی + سناریوهای
    لغزش + نقطهٔ سربه‌سر. آفلاین، قطعی، بدون مهر زمانی، بدون نوشتن فایل."""
    base = {
        "method": COST_METHOD,
        "engine": evaluator.METHOD,
        "mode": "READ ONLY | PAPER ONLY | NO LIVE ORDERS",
        "spread_proxy": {
            "estimator": SPREAD_ESTIMATOR,
            "label": "PROXY_NOT_ORDER_BOOK",
            "per_symbol_bps": {s: corwin_schultz_spread_bps(cs)
                               for s, cs in sorted(candles_map.items())},
        },
        "verdict": "REPORTED",
        "limitations": [
            "پروکسی CS روی کندل ۱ساعته فقط مرتبهٔ بزرگی می‌دهد و نوسان را به "
            "اسپرد نسبت می‌دهد (سوگیری رو به بالا)؛ دفتر سفارش/عمق/صف دیده نمی‌شود",
            "پوشش هزینه منطق برخورد TP/SL را عوض نمی‌کند؛ برخوردهای مرزی در "
            "اجرای واقعی ممکن است برعکس شوند",
            "فاندینگ، تأخیر پرکردن و تفاوت نقدشوندگی نمادها مدل نشده است",
            "خروجی فقط REPORTED است — هیچ آستانه‌ای موفقیت جعل نشده",
        ],
    }
    if not candles_map or not trades:
        return dict(base, verdict="INSUFFICIENT_EVIDENCE",
                    reason="EMPTY_INPUT_NO_TRADES_OR_CANDLES")
    valid = [v for v in base["spread_proxy"]["per_symbol_bps"].values()
             if isinstance(v, (int, float))]
    spread_used = round(_median(valid), 4) if valid else None
    base["spread_proxy"]["median_bps"] = spread_used
    if spread_used is None:
        return dict(base, verdict="INSUFFICIENT_EVIDENCE",
                    reason="NO_VALID_SPREAD_ESTIMATE")
    base["scenarios"] = scenario_grid(
        trades, spread_bps=spread_used, slippage_bps_list=slippage_bps_list,
        fee_pct=fee_pct)
    base["break_even"] = break_even_slippage_bps(
        trades, spread_bps=spread_used, fee_pct=fee_pct)
    n_closed = base["scenarios"]["baseline_zero_cost"]["n_closed"]
    if n_closed < min_samples:
        return dict(base, verdict="INSUFFICIENT_EVIDENCE",
                    reason="CLOSED_BELOW_MIN_SAMPLES",
                    n_closed=n_closed, min_samples_required=min_samples)
    base["n_closed"] = n_closed
    return base


def canonical_json(report: dict) -> str:
    """نمایش قطعی برای آزمون بازتولیدپذیری (کل خروجی بدون مهر زمانی است)."""
    return json.dumps(report, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
