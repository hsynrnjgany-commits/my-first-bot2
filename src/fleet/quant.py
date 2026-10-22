# MARI — خوشهٔ M: Quant Lab / آزمایشگاه کمّی (افزودهٔ ناوگان — ثبت شفاف)
# MODE: READ ONLY | PAPER ONLY | NO LIVE ORDERS
# ریاضیات واقعی روی همان کندل‌های پاک‌شدهٔ خوشهٔ L، بدون نشت اطلاعات آینده:
#   - Hurst (R/S) برای رژیم روند/بازگشت‌به‌میانگین → فقط HYPOTHESIS
#   - نوسان EWMA (RiskMetrics λ=0.94) و صدک ATR → OBSERVED
#   - z-score بازده آخرین کندل در برابر تاریخچهٔ خودش → OBSERVED
#   - هم‌انباشتگی-lite (OLS + نیم‌عمر بازگشت) → کاندید جفت، فقط HYPOTHESIS
# هیچ الگویی بدون آزمون حسابرس، حقیقت قطعی تلقی نمی‌شود (بند ۳-F/۵).

import math

from .contract import make_message

METHOD = "quant_lab/v1"
EWMA_LAMBDA = 0.94          # RiskMetrics کلاسیک
ATR_WINDOW = 14
Z_WINDOW = 50
Z_THRESHOLD = 2.0
HURST_TREND = 0.55          # مرزهای اکتشافی — اعلام‌شده، نه جعلی
HURST_REVERT = 0.45
MIN_COINT_LEN = 60
MAX_PAIRS = 12


def log_returns(candles: list) -> list:
    out = []
    for a, b in zip(candles, candles[1:]):
        if a["close"] > 0 and b["close"] > 0:
            out.append(math.log(b["close"] / a["close"]))
    return out


def _ols_slope(xs: list, ys: list):
    """شیب و عرض OLS ساده — ورودی کوتاه/بدون واریانس → None."""
    n = min(len(xs), len(ys))
    if n < 2:
        return None, None
    xs, ys = xs[:n], ys[:n]
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den <= 0:
        return None, None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
    return slope, my - slope * mx


def hurst_exponent(returns: list) -> "float | None":
    """Hurst با تحلیل R/S روی بلوک‌های بدون هم‌پوشانی — سری کوتاه → None."""
    n = len(returns)
    scales = [s for s in (8, 16, 32, 64) if s <= n]
    if len(scales) < 2:
        return None
    xs, ys = [], []
    for s in scales:
        rs_values = []
        for start in range(0, n - s + 1, s):
            block = returns[start:start + s]
            m = sum(block) / s
            cum = 0.0
            best = -math.inf
            worst = math.inf
            sq = 0.0
            for r in block:
                d = r - m
                cum += d
                best = max(best, cum)
                worst = min(worst, cum)
                sq += d * d
            std = math.sqrt(sq / s)
            if std > 0 and best > worst:
                rs_values.append((best - worst) / std)
        if rs_values:
            xs.append(math.log(s))
            ys.append(math.log(sum(rs_values) / len(rs_values)))
    if len(xs) < 2:
        return None
    slope, _ = _ols_slope(xs, ys)
    if slope is None or not (0.0 < slope < 1.5):
        return None
    return slope


def ewma_volatility(returns: list, lam: float = EWMA_LAMBDA) -> "float | None":
    """σ لحظه‌ای EWMA — σ²_t = λσ²_{t-1} + (1−λ)r²_{t-1}، آغاز از واریانس ۵ نمونهٔ اول."""
    if len(returns) < 6:
        return None
    var = sum(r * r for r in returns[:5]) / 5
    for r in returns[5:]:
        var = lam * var + (1 - lam) * r * r
    return math.sqrt(var)


def return_zscore(returns: list, window: int = Z_WINDOW,
                  z_threshold: float = Z_THRESHOLD) -> "float | None":
    """z بازده آخرین در برابر پنجرهٔ قبل از خودش (بدون نشت). واریانس صفر → None."""
    if len(returns) < window + 1:
        return None
    hist = returns[-(window + 1):-1]
    mean = sum(hist) / window
    std = math.sqrt(sum((r - mean) ** 2 for r in hist) / window)
    if std <= 0:
        return None
    z = (returns[-1] - mean) / std
    return z if abs(z) >= z_threshold else None


def atr_series(candles: list) -> list:
    trs = []
    for a, b in zip(candles, candles[1:]):
        trs.append(max(b["high"] - b["low"],
                       abs(b["high"] - a["close"]),
                       abs(b["low"] - a["close"])))
    return trs


def atr_percentile(candles: list, window: int = ATR_WINDOW) -> "float | None":
    """صدک ATR آخر در برابر همهٔ ATRهای غلتان تاریخچهٔ همان نماد [0..1]."""
    trs = atr_series(candles)
    if len(trs) < window + 5:
        return None
    rolling = [sum(trs[i - window:i]) / window for i in range(window, len(trs) + 1)]
    if not rolling:
        return None
    last = rolling[-1]
    below = sum(1 for v in rolling if v <= last)
    return below / len(rolling)


def cointegration_lite(log_y: list, log_x: list) -> "dict | None":
    """y = α + βx → باقیمانده → φ در Δe_t = φe_{t-1} → نیم‌عمر بازگشت.
    پذیرش اکتشافی: φ<0 و نیم‌عمر در [1, 200] کندل — برچسب: HEURISTIC."""
    if len(log_y) != len(log_x) or len(log_y) < MIN_COINT_LEN:
        return None
    beta, alpha = _ols_slope(log_x, log_y)
    if beta is None:
        return None
    resid = [y - (alpha + beta * x) for y, x in zip(log_y, log_x)]
    mean_r = sum(resid) / len(resid)
    sigma = math.sqrt(sum((r - mean_r) ** 2 for r in resid) / len(resid))
    if sigma <= 0:
        return None
    lags = resid[:-1]
    deltas = [r2 - r1 for r1, r2 in zip(resid, resid[1:])]
    phi, _ = _ols_slope(lags, deltas)
    if phi is None or phi >= -1e-9 or (1 + phi) <= 0:
        return None
    half_life = -math.log(2) / math.log(1 + phi)
    if not (1.0 <= half_life <= 200.0):
        return None
    return {"beta": beta, "alpha": alpha, "phi": phi,
            "half_life_candles": half_life, "resid_sigma": sigma,
            "last_z": (resid[-1] - mean_r) / sigma}


def analyze_multi(candles_map: dict, *, timeframe: str,
                  data_asof_ms: int, task_id: str = None,
                  max_pairs: int = MAX_PAIRS) -> list:
    """ورودی: نگاشت نماد → کندل‌های پاک. خروجی: پیام‌های قراردادی خوشهٔ M."""
    events = []
    symbols = sorted(candles_map.keys())

    for sym in symbols:
        candles = candles_map[sym]
        if len(candles) < Z_WINDOW + 2:
            continue
        rets = log_returns(candles)

        z = return_zscore(rets)
        if z is not None:
            events.append(make_message(
                cluster_id="M", symbol=sym,
                event_type="RETURN_Z_EXTREME",
                event_time_ms=candles[-1]["open_time"],
                data_asof_ms=data_asof_ms, timeframe=timeframe,
                features={"z": round(z, 3), "window": Z_WINDOW,
                          "last_return": round(rets[-1], 6)},
                evidence={"method": METHOD},
                validation_status="OBSERVED", task_id=task_id,
            ))

        sigma = ewma_volatility(rets)
        atr_p = atr_percentile(candles)
        if sigma is not None:
            events.append(make_message(
                cluster_id="M", symbol=sym,
                event_type="VOLATILITY_REGIME",
                event_time_ms=candles[-1]["open_time"],
                data_asof_ms=data_asof_ms, timeframe=timeframe,
                features={"ewma_vol_per_bar": round(sigma, 6),
                          "atr_percentile": round(atr_p, 4) if atr_p is not None else None,
                          "ewma_lambda": EWMA_LAMBDA},
                evidence={"method": METHOD},
                validation_status="OBSERVED", task_id=task_id,
            ))

        if len(rets) >= 16:
            h = hurst_exponent(rets)
            if h is not None and (h >= HURST_TREND or h <= HURST_REVERT):
                regime = "TRENDING_CANDIDATE" if h >= HURST_TREND \
                    else "MEAN_REVERTING_CANDIDATE"
                events.append(make_message(
                    cluster_id="M", symbol=sym,
                    event_type="HURST_REGIME",
                    event_time_ms=candles[-1]["open_time"],
                    data_asof_ms=data_asof_ms, timeframe=timeframe,
                    features={"hurst": round(h, 4),
                              "regime": regime,
                              "bounds": [HURST_REVERT, HURST_TREND]},
                    evidence={"method": "rescaled_range_rs/v1"},
                    validation_status="HYPOTHESIS", task_id=task_id,
                    hypothesis={"statement":
                                f"برآورد Hurst={round(h, 3)} — فرضیهٔ رژیم "
                                "روند/بازگشت؛ مرزهای ۰٫۴۵/۰٫۵۵ اکتشافی‌اند "
                                "و باید در نمونه‌های بیرونی تأیید شوند"},
                    uncertainty=["R/S روی ۲۰۰ کندل کوتاه است",
                                 "برآورد H پرنوسان است؛ مبنای تصمیم نیست"],
                ))

    # کاندیدهای جفت: OLS + نیم‌عمر بازگشت — سقف MAX_PAIRS برای سبک‌ماندن اجرا
    pairs_made = 0
    for i, a in enumerate(symbols):
        if pairs_made >= max_pairs:
            break
        for b in symbols[i + 1:]:
            if pairs_made >= max_pairs:
                break
            ca, cb = candles_map[a], candles_map[b]
            if len(ca) != len(cb) or len(ca) < MIN_COINT_LEN:
                continue
            la = [math.log(c["close"]) for c in ca if c["close"] > 0]
            lb = [math.log(c["close"]) for c in cb if c["close"] > 0]
            if len(la) != len(lb) or len(la) < MIN_COINT_LEN:
                continue
            fit = cointegration_lite(la, lb)
            if fit is None:
                continue
            pairs_made += 1
            events.append(make_message(
                cluster_id="M", symbol=f"{a}/{b}",
                event_type="PAIR_CANDIDATE",
                event_time_ms=cb[-1]["open_time"],
                data_asof_ms=data_asof_ms, timeframe=timeframe,
                features={**{k: round(v, 6) if isinstance(v, float) else v
                             for k, v in fit.items()},
                          "method_label": "HEURISTIC"},
                evidence={"method": "ols_ar1_halflife/v1"},
                validation_status="HYPOTHESIS", task_id=task_id,
                hypothesis={"statement":
                            "کاندید هم‌انباشتگی با نیم‌عمر بازگشت مشخص — "
                            "فرضیهٔ معاملهٔ جفتی کاغذی؛ تا آزمون Walk-Forward "
                            "و حسابرس مستقل هیچ اعتباری ندارد"},
                uncertainty=["هم‌انباشتگی درون‌نمونه‌ای است (بیش‌برازش محتمل)",
                             "بدون آزمون بیرون از نمونه هنوز",
                             "کارمزد/لغزش دو پا محاسبه نشده"],
            ))
    return events


class QuantCluster:
    """پوستهٔ استاندارد — یک وظیفه در هر چرخه با candles_map کامل در ctx."""
    cluster_id = "M"

    def run(self, task: dict) -> list:
        ctx = task["ctx"]
        return analyze_multi(task["ctx"].get("candles_map", {}),
                             timeframe=ctx.get("interval", "1h"),
                             data_asof_ms=ctx["data_asof_ms"],
                             task_id=task.get("task_id"))
