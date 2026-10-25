# MARI — vol_target: هدف‌گذاری نوسان آفلاین با مقیاس ضدنشت — فقط پژوهشی
# MODE: READ ONLY | PAPER ONLY | NO LIVE ORDERS
#
# خاستگاه: اولویت P3 گزارش EXECUTION ORDER 001 (2026-10-25) — پرسش: آیا
# مقیاس‌دهی وارونِ نوسان، زیان خالص سمت SHORT را برطرف می‌کند یا نه؟
# مفهوم: Moreira & Muir (Journal of Finance 2017, 72(4):1611-1651) —
# «پرتفوی مدیریت‌شده با نوسان». اینجا ساده‌سازی شفاف: اندازهٔ پوزیشن متناسب
# با target/σ در لحظهٔ ورود، با سقف/کف؛ σ از EWMA بازده ساعتی (quant) و
# فقط از کندل‌های بستهٔ پیش از ورود (ضدنشت) برآورد می‌شود.
# مقیاس فقط «اندازه» را تغییر می‌دهد — ورود/خروج/منطق TP/SL دست‌نخورده.
# هر خروجی فقط REPORTED یا INSUFFICIENT_EVIDENCE است؛ اگر امید ریاضی منفی
# باشد، مقیاس‌دهی هم زیان می‌دهد (کمتر یا بیشتر — صادقانه گزارش می‌شود).

import json

from . import cost_model
from . import evaluator
from .quant import EWMA_LAMBDA, ewma_volatility

VOL_METHOD = "vol_target/inverse_ewma_v1"
DEFAULT_LOOKBACK = 24          # کندل بستهٔ ۱ساعته برای پنجرهٔ σ
DEFAULT_TARGET_VOL_PCT = 0.8   # σ هدف ساعته (درصد) — قابل پیکربندی
DEFAULT_MAX_SCALE = 2.0
DEFAULT_MIN_SCALE = 0.0
MIN_RETURNS = 6                # حداقل بازده برای EWMA — هم‌راستا با quant


def entry_vol_scale(candles: list, entry_index: int, *,
                    lookback: int = DEFAULT_LOOKBACK,
                    target_vol_pct: float = DEFAULT_TARGET_VOL_PCT,
                    max_scale: float = DEFAULT_MAX_SCALE,
                    min_scale: float = DEFAULT_MIN_SCALE,
                    lam: float = EWMA_LAMBDA) -> dict:
    """مقیاس لحظهٔ ورود = clip(target/σ) — σ فقط از کندل‌های پیش از ورود.
    پنجره: candles[max(0,entry_index−lookback) : entry_index] (انحصاری).
    خروجی قطعی: {scale, sigma_pct, n_returns, flag} — scale فقط برای
    flag=OK عددی است؛ سایر پرچم‌ها یعنی مقیاس‌دهی نشده."""
    start = max(0, int(entry_index))
    window = candles[max(0, start - lookback):start]
    rets = [b["close"] / a["close"] - 1.0
            for a, b in zip(window, window[1:])
            if a["close"] > 0 and b["close"] > 0]
    base = {"n_returns": len(rets), "sigma_pct": None, "scale": None}
    if len(rets) < MIN_RETURNS:
        return dict(base, flag="UNSCALED_INSUFFICIENT_HISTORY")
    sigma = ewma_volatility(rets, lam=lam)
    if sigma is None:
        return dict(base, flag="UNSCALED_INSUFFICIENT_HISTORY")
    if sigma <= 0:
        # نوسان صفر دقیق — سقف مقیاس با پرچم صادقانه (رویداد نادر)
        return dict(base, sigma_pct=0.0, scale=max_scale,
                    flag="ZERO_VOL_CAPPED")
    scale = (target_vol_pct / 100.0) / sigma
    clipped = min(max(scale, min_scale), max_scale)
    return dict(base, sigma_pct=round(sigma * 100, 6),
                scale=round(clipped, 6),
                flag="DOWNSCALED" if clipped < 0.9999
                else ("UPSCALED_CAPPED" if scale > max_scale else "SCALE_ONE"))


def apply_vol_scaling(trades: list, candles_map: dict, *,
                      interval_ms: int = 3_600_000,
                      lookback: int = DEFAULT_LOOKBACK,
                      target_vol_pct: float = DEFAULT_TARGET_VOL_PCT,
                      max_scale: float = DEFAULT_MAX_SCALE,
                      min_scale: float = DEFAULT_MIN_SCALE,
                      key: str = "net_pct") -> "tuple":
    """مقیاس‌دهی هر معامله بر σ لحظهٔ ورود → net_scaled = scale × net.
    کلیدهای افزوده: scale، sigma_pct، scaling_flag، net_pct_scaled.
    معاملات مقیاس‌نشده net اصلی را نگه می‌دارند و شمرده می‌شوند."""
    idx_maps = {}
    for sym, cs in candles_map.items():
        idx_maps[sym] = {c["open_time"]: i for i, c in enumerate(cs)}
    out = []
    n_scaled = n_unscaled = 0
    flag_counts = {}
    for t in trades:
        sym = t.get("symbol")
        j = idx_maps.get(sym, {}).get(t.get("entry_time_ms"))
        if j is None:
            sc = {"scale": None, "sigma_pct": None, "n_returns": 0,
                  "flag": "UNSCALED_ENTRY_NOT_FOUND"}
        else:
            sc = entry_vol_scale(candles_map[sym], j, lookback=lookback,
                                 target_vol_pct=target_vol_pct,
                                 max_scale=max_scale, min_scale=min_scale)
        flag_counts[sc["flag"]] = flag_counts.get(sc["flag"], 0) + 1
        if sc["scale"] is None:
            n_unscaled += 1
            net_scaled = round(float(t[key]), 6)
            scale_out = None
        else:
            n_scaled += 1
            scale_out = sc["scale"]
            net_scaled = round(sc["scale"] * float(t[key]), 6)
        out.append(dict(t, scale=scale_out, sigma_pct=sc["sigma_pct"],
                        scaling_flag=sc["flag"], n_returns=sc["n_returns"],
                        net_pct_scaled=net_scaled))
    summary = {"n": len(trades), "n_scaled": n_scaled,
               "n_unscaled": n_unscaled, "flag_counts": flag_counts}
    return out, summary


def direction_block(trades: list, *, min_samples: int = evaluator.MIN_SAMPLES) -> dict:
    """بلوک یک جهت: realized خام (net_pct) در برابر مقیاس‌یافته (net_pct_scaled)
    — فقط بسته‌های TP/SL، هم‌راستا با اصلاح A-2."""
    closed = [t for t in trades if t.get("exit_reason") in ("TP", "SL")]
    raw = cost_model.realized_metrics(closed, key="net_pct")
    scaled = cost_model.realized_metrics(closed, key="net_pct_scaled")
    delta = None
    if raw["sum_net_pct"] is not None and scaled["sum_net_pct"] is not None:
        delta = round(scaled["sum_net_pct"] - raw["sum_net_pct"], 6)
    return {
        "raw": raw, "scaled": scaled, "delta_sum_net_pp": delta,
        "verdict": "REPORTED" if raw["n_closed"] >= min_samples
        else "INSUFFICIENT_EVIDENCE",
    }


def vol_report(candles_map: dict, trades: list, *,
               lookback: int = DEFAULT_LOOKBACK,
               target_vol_pct: float = DEFAULT_TARGET_VOL_PCT,
               max_scale: float = DEFAULT_MAX_SCALE,
               min_scale: float = DEFAULT_MIN_SCALE,
               min_samples: int = evaluator.MIN_SAMPLES) -> dict:
    """گزارش P3: خط پایهٔ جهت‌دار در برابر نسخهٔ هدف‌گذاری‌نوسان — آفلاین و
    قطعی؛ اگر مقیاس‌دهی SHORT را «بدتر» هم کند، صادقانه گزارش می‌شود."""
    base = {
        "method": VOL_METHOD,
        "engine": evaluator.METHOD,
        "mode": "READ ONLY | PAPER ONLY | NO LIVE ORDERS",
        "config": {"lookback": lookback, "target_vol_pct": target_vol_pct,
                   "max_scale": max_scale, "min_scale": min_scale,
                   "ewma_lambda": EWMA_LAMBDA,
                   "sigma_estimator": "quant.ewma_volatility_hourly"},
        "verdict": "REPORTED",
        "limitations": [
            "مقیاس فقط اندازه را تغییر می‌دهد؛ فرض خطی بودن بازده نسبت به "
            "اندازه — ورود/خروج و منطق TP/SL شبیه‌ساز دست‌نخورده است",
            "هدف‌گذاری نوسان لبهٔ منفی را حذف نمی‌کند؛ فقط توزیع ریسک را "
            "تغییر می‌دهد — با E[r]<0 همچنان زیان انتظار می‌رود",
            "σ از EWMA بازده ساعتی با دادهٔ پیش از ورود است؛ σ آیندهٔ واقعی "
            "می‌تواند متفاوت باشد",
            "خروجی فقط REPORTED است — هیچ آستانه‌ای موفقیت جعل نشده",
        ],
    }
    if not candles_map or not trades:
        return dict(base, verdict="INSUFFICIENT_EVIDENCE",
                    reason="EMPTY_INPUT_NO_TRADES_OR_CANDLES")
    scaled, summary = apply_vol_scaling(
        trades, candles_map, lookback=lookback,
        target_vol_pct=target_vol_pct, max_scale=max_scale,
        min_scale=min_scale)
    by_dir = {}
    for d in ("long", "short"):
        subset = [t for t in scaled if t.get("direction") == d]
        if subset:
            by_dir[d] = direction_block(subset, min_samples=min_samples)
    total_closed = sum(1 for t in trades
                       if t.get("exit_reason") in ("TP", "SL"))
    if total_closed < min_samples:
        return dict(base, verdict="INSUFFICIENT_EVIDENCE",
                    reason="CLOSED_BELOW_MIN_SAMPLES",
                    n_closed=total_closed, min_samples_required=min_samples,
                    scaling_summary=summary, by_direction=by_dir)
    return dict(base, scaling_summary=summary, by_direction=by_dir,
                n_closed=total_closed)


def canonical_json(report: dict) -> str:
    """نمایش قطعی برای آزمون بازتولیدپذیری (کل خروجی بدون مهر زمانی است)."""
    return json.dumps(report, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
