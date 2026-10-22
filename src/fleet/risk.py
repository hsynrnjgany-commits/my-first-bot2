# MARI — خوشهٔ K: Risk & Portfolio (بند ۳-K دستور)
# MODE: READ ONLY | PAPER ONLY | NO LIVE ORDERS
# افت سرمایه، تمرکز (HHI) و همبستگی — همه «پژوهشی و کاغذی» (بند ۳-K صریح).
# ورودی: معاملات شبیه‌سازی‌شدهٔ کاغذی از ارزیاب، نه هیچ معاملهٔ واقعی.

import math


def max_drawdown(curve: list) -> dict:
    """بیشترین افت از قله در یک سری عددی. خروجی با جزئیات قله/کف."""
    if not curve:
        return {"max_dd": 0.0, "peak": None, "trough": None, "peak_index": None,
                "trough_index": None}
    peak = curve[0]
    peak_idx = 0
    best = {"max_dd": 0.0, "peak": peak, "trough": peak,
            "peak_index": 0, "trough_index": 0}
    for i, value in enumerate(curve):
        if value > peak:
            peak, peak_idx = value, i
        if peak > 0:
            dd = (peak - value) / peak
            if dd > best["max_dd"]:
                best = {"max_dd": dd, "peak": peak, "trough": value,
                        "peak_index": peak_idx, "trough_index": i}
    return best


def hhi(weights: list) -> float:
    """شاخص هرفیندال–هیرشمن: 0=پراکنده، 1=تمرکز کامل (ورودی مجموعش 1 فرض می‌شود)."""
    total = sum(weights)
    if total <= 0:
        return 0.0
    return sum((w / total) ** 2 for w in weights)


def pearson(xs: list, ys: list):
    """همبستگی نمونه‌ای — دادهٔ ناکافی یا بدون واریانس → None (نه صفر جعلی)."""
    n = min(len(xs), len(ys))
    if n < 2:
        return None
    xs, ys = xs[:n], ys[:n]
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None
    return cov / math.sqrt(vx * vy)


def concentration(trades: list) -> dict:
    """تمرکز سود/زیان روی نمادها — بند ۵: «تمرکز سود روی تعداد کمی نماد»."""
    per_symbol = {}
    for t in trades:
        per_symbol[t["symbol"]] = per_symbol.get(t["symbol"], 0.0) + t["net_pct"]
    if not per_symbol:
        return {"hhi": 0.0, "top_symbol": None, "top_share": 0.0,
                "symbols": {}}
    total_abs = sum(abs(v) for v in per_symbol.values())
    weights = [abs(v) for v in per_symbol.values()]
    top = max(per_symbol, key=lambda s: abs(per_symbol[s]))
    return {
        "hhi": round(hhi(weights), 4),
        "top_symbol": top,
        "top_share": round(abs(per_symbol[top]) / total_abs, 4)
        if total_abs > 0 else 0.0,
        "symbols": {s: round(v, 4) for s, v in per_symbol.items()},
    }


def portfolio_summary(trades: list) -> dict:
    """خلاصهٔ ریسک پژوهشی: MaxDD منحنی تجمعی + تمرکز + همبستگی درون‌نمادی."""
    ordered = sorted(trades, key=lambda t: t.get("entry_time_ms", 0))
    curve = []
    acc = 0.0
    for t in ordered:
        acc += t["net_pct"]
        curve.append(acc)
    dd = max_drawdown(curve)
    return {
        "max_drawdown_curve": round(dd["max_dd"], 6),
        "cumulative_net_pct": round(acc, 4),
        "concentration": concentration(trades),
        "note": "پژوهش کاغذی روی معاملات شبیه‌سازی‌شده — هیچ سرمایهٔ واقعی",
    }


# ---------- توسعهٔ خوشهٔ K (دستور ممیزی/تکمیل): محاسبات اضافی ----------
from .contract import make_message  # noqa: E402 — پیام قراردادی خوشهٔ K
# همهٔ این محاسبات «پژوهشی و کاغذی»اند و بر معاملات شبیه‌سازی‌شدهٔ ارزیاب سوارند.
# تفکیک صریح: نتایج تاریخی (OBSERVED) / سناریوهای فرضی (scenario) / نامطمئن (uncertainty).

ASSUMED_PAPER_CAPITAL_USD = 10_000.0  # برچسب صریح: سرمایهٔ تمرینی فرضی — نه دارایی کاربر
SCENARIO_FEE_DELTAS_PCT = (0.0, 0.05, 0.1)  # حساسیت به افزایش کارمزد رفت‌وبرگشت
SL_PCT_ASSUMPTION = 1.0  # سناریوی «همهٔ پوزیشن‌های باز به SL خوردند» بر مبنای SL پایه


def multiplicative_equity(trades: list, base_usd: float = ASSUMED_PAPER_CAPITAL_USD) -> dict:
    """منحنی سرمایهٔ ضربی (بازسرگذاری واقعی‌تر از جمع ساده) + MaxDD درصدی.
    ترتیب زمانی با entry_time_ms؛ معاملهٔ بدون زمان → انتهای فهرست."""
    ordered = sorted(trades, key=lambda t: t.get("entry_time_ms") or 0)
    equity = base_usd
    peak = base_usd
    max_dd = 0.0
    curve = []
    for t in ordered:
        equity *= (1.0 + t["net_pct"] / 100.0)
        curve.append(round(equity, 2))
        if equity > peak:
            peak = equity
        if peak > 0:
            dd = (peak - equity) / peak
            max_dd = max(max_dd, dd)
    return {
        "assumed_base_usd": base_usd,
        "final_equity_usd": round(equity, 2),
        "cumulative_pct": round((equity / base_usd - 1.0) * 100, 4),
        "max_drawdown_pct": round(max_dd * 100, 4),
        "curve_len": len(curve),
    }


def historical_var95(nets: list):
    """VaR تاریخی ۹۵٪ (صدک پنجم بازده‌ها) — n<10 → None (پرهیز از دقت کاذب)."""
    if len(nets) < 10:
        return None
    ordered = sorted(nets)
    idx = max(0, int(__import__("math").ceil(0.05 * len(ordered))) - 1)
    return round(ordered[idx], 6)


def fee_sensitivity(trades: list, base_fee_pct: float = 0.1,
                    deltas=SCENARIO_FEE_DELTAS_PCT) -> list:
    """سناریوی فرضی: اگر کارمزد رفت‌وبرگشت δ بیشتر بود، جمع خالص چه می‌شد؟
    هر ردیف با برچسب scenario — هرگز به‌عنوان نتیجهٔ تاریخی گزارش نمی‌شود."""
    gross_total = sum(t["net_pct"] for t in trades) + base_fee_pct * len(trades)
    rows = []
    for d in deltas:
        rows.append({
            "scenario": True,
            "label": f"fee+{round(d, 4)}pp",
            "fee_pct": round(base_fee_pct + d, 4),
            "total_net_pct": round(gross_total - (base_fee_pct + d) * len(trades), 4),
        })
    return rows


def pairwise_correlation(candles_map: dict, symbols: list = None,
                         max_pairs: int = 10) -> dict:
    """همبستگی بازده ساعتانهٔ بسته‌شدن بین نمادها — فقط جفت‌های با دادهٔ مشترک
    کافی (>=50 کندل). هم‌پوشانی زمانی کامل نیست؛ برآورد HEURISTIC ثبت می‌شود."""
    syms = list(symbols or candles_map.keys())[:6]
    pairs = {}
    for i in range(len(syms)):
        for j in range(i + 1, len(syms)):
            a, b = syms[i], syms[j]
            ca, cb = candles_map.get(a), candles_map.get(b)
            if not ca or not cb:
                continue
            n = min(len(ca), len(cb))
            if n < 50:
                pairs[f"{a}/{b}"] = None  # دادهٔ ناکافی — صادقانه None
                continue
            # ورودی نامعتبر (قیمت صفر/منفی) → بازده تعریف‌ناپذیر → None صادقانه
            closes_a = [c["close"] for c in ca[:n]]
            closes_b = [c["close"] for c in cb[:n]]
            if any(x <= 0 for x in closes_a) or any(x <= 0 for x in closes_b):
                pairs[f"{a}/{b}"] = None
                continue
            ra = [closes_a[k] / closes_a[k - 1] - 1.0 for k in range(1, n)]
            rb = [closes_b[k] / closes_b[k - 1] - 1.0 for k in range(1, n)]
            r = pearson(ra, rb)
            pairs[f"{a}/{b}"] = round(r, 4) if r is not None else None
            if len(pairs) >= max_pairs:
                return pairs
    return pairs


def simultaneous_positions(trades: list, hold_ms: int = 24 * 3_600_000) -> dict:
    """ریسک هم‌زمانی: بیشینهٔ پوزیشن‌های باز هم‌پوشان (ورود تا ورود+hold).
    از معاملات شبیه‌سازی‌شده — نمایش ریسک هم‌جهتی چند موقعیت، نه سفارش."""
    spans = sorted((t["entry_time_ms"],
                    (t.get("exit_time_ms") or t["entry_time_ms"] + hold_ms))
                   for t in trades)
    best, cur_end, count = 0, None, 0
    events = []
    for s, e in spans:
        events.append((s, 1))
        events.append((e, -1))
    events.sort(key=lambda x: (x[0], x[1]))
    running = 0
    for _, delta in events:
        running += delta
        best = max(best, running)
    opens = [t for t in trades if t.get("exit_reason") == "OPEN"]
    return {
        "max_simultaneous": best,
        "currently_open": len(opens),
        "open_symbols": sorted({t["symbol"] for t in opens}),
        "all_open_sl_scenario_loss_pct": round(
            len(opens) * SL_PCT_ASSUMPTION + len(opens) * 0.1, 4) if opens else 0.0,
    }


def exposure_table(trades: list, base_usd: float = ASSUMED_PAPER_CAPITAL_USD) -> dict:
    """مواجههٔ هر دارایی: تعداد پوزیشن، سهم از معاملات (٪)، سهم از سود/زیان (٪)
    و «مواجههٔ اسمی فرضی» با برچسب صریح (ریسک کاغذی ۱٪ از سرمایهٔ فرضی هر پوزیشن)."""
    n = len(trades)
    per = {}
    for t in trades:
        row = per.setdefault(t["symbol"], {"positions": 0, "pnl_pct": 0.0})
        row["positions"] += 1
        row["pnl_pct"] += t["net_pct"]
    total_pnl_abs = sum(abs(v["pnl_pct"]) for v in per.values()) or 1.0
    nominal_each = base_usd * 0.01  # ریسک کاغذی ۱٪ — با برچسب فرض
    for sym, row in per.items():
        row["trade_share_pct"] = round(row["positions"] / n * 100, 2) if n else 0.0
        row["pnl_share_pct"] = round(abs(row["pnl_pct"]) / total_pnl_abs * 100, 2)
        row["assumed_nominal_usd"] = round(nominal_each * row["positions"], 2)
    return per


def portfolio_risk_message(trades: list, *, data_asof_ms: int,
                           candles_map: dict = None,
                           task_id: str = None) -> list:
    """پیام قراردادی خوشهٔ K. بدون معامله → UNAVAILABLE صادقانه.
    تفکیک: تاریخی (OBSERVED) / سناریو (features.scenario) / نامطمئن (uncertainty)."""
    if not trades:
        return [make_message(
            cluster_id="K", symbol="PORTFOLIO",
            event_type="PAPER_PORTFOLIO_RISK_UNAVAILABLE",
            event_time_ms=data_asof_ms, data_asof_ms=data_asof_ms,
            exchange="paper", market_type="paper", timeframe=None,
            features={"n_trades": 0},
            evidence={"source": "evaluator.simulate_trades (paper only)",
                      "method": "portfolio_risk/v1"},
            validation_status="UNAVAILABLE", task_id=task_id,
            uncertainty=["سبد کاغذی فعلی خالی است — هیچ سنجهٔ ریسکی جعل نشد"],
        )]
    nets = [t["net_pct"] for t in trades]
    conc = concentration(trades)
    equity = multiplicative_equity(trades)
    simult = simultaneous_positions(trades)
    exposures = exposure_table(trades)
    corr = pairwise_correlation(candles_map) if candles_map else {}
    corr_insufficient = [k for k, v in corr.items() if v is None]
    var95 = historical_var95(nets)
    features = {
        "n_trades": len(trades),
        "assumed_capital_usd": ASSUMED_PAPER_CAPITAL_USD,
        "assumed_capital_is_paper": True,
        "wins": sum(1 for x in nets if x > 0),
        "losses": sum(1 for x in nets if x < 0),
        "cumulative_additive_pct": round(sum(nets), 4),
        "equity_multiplicative": equity,
        "var95_pct": var95,
        "concentration_hhi": conc["hhi"],
        "top_symbol": conc["top_symbol"],
        "top_pnl_share_pct": round(conc["top_share"] * 100, 2),
        "exposures": exposures,
        "simultaneity": simult,
        "fee_sensitivity": fee_sensitivity(trades),
        "correlations_hourly": corr,
    }
    uncertainty = [
        "همهٔ سنجه‌ها پژوهشی/کاغذی‌اند — هیچ مواجههٔ واقعی وجود ندارد",
        "مواجههٔ اسمی با سرمایهٔ تمرینی فرضی ۱۰۰۰۰ USD و ریسک ۱٪/معامله برچسب خورده است",
    ]
    if len(trades) < 10:
        uncertainty.append(f"نمونهٔ کوچک (n={len(trades)} < 10) — دقت آماری ادعا نمی‌شود")
    if var95 is None:
        uncertainty.append("VaR95 برای n<10 گزارش نمی‌شود (پرهیز از دقت کاذب)")
    if corr_insufficient:
        uncertainty.append("همبستگی این جفت‌ها به‌دلیل دادهٔ ناکافی None است: "
                           + ", ".join(corr_insufficient))
    if corr:
        uncertainty.append("پنجرهٔ همبستگی ساعتی هم‌پوشان است — برآورد اکتشافی (HEURISTIC)")
    msg = make_message(
        cluster_id="K", symbol="PORTFOLIO", event_type="PAPER_PORTFOLIO_RISK",
        event_time_ms=data_asof_ms, data_asof_ms=data_asof_ms,
        exchange="paper", market_type="paper", timeframe=None,
        features=features,
        evidence={"source": "evaluator.simulate_trades (paper only)",
                  "method": "portfolio_risk/v1"},
        validation_status="OBSERVED", task_id=task_id,
        uncertainty=uncertainty,
    )
    out = [msg]
    if conc["hhi"] >= 0.6:
        out.append(make_message(
            cluster_id="K", symbol=conc["top_symbol"] or "PORTFOLIO",
            event_type="CONCENTRATION_HYPOTHESIS",
            event_time_ms=data_asof_ms, data_asof_ms=data_asof_ms,
            exchange="paper", market_type="paper", timeframe=None,
            features={"hhi": conc["hhi"], "top_symbol": conc["top_symbol"],
                      "symbols": conc["symbols"]},
            evidence={"source": "evaluator.simulate_trades (paper only)",
                      "method": "portfolio_risk/v1"},
            hypothesis={
                "claim": f"سود/زیان کاغذی به {conc['top_symbol']} متمرکز است "
                         f"(HHI={conc['hhi']})",
                "falsifiable_by": "تنوع‌سازی فرضی سبد و بازمحاسبهٔ PF — "
                                  "اگر PF تغییر معنادار نکرد، فرضیه رد می‌شود",
            },
            validation_status="HYPOTHESIS", task_id=task_id,
            uncertainty=["آستانهٔ HHI=0.6 قاعدهٔ اکتشافی این سامانه است"],
        ))
    return out


class PortfolioRiskCluster:
    """پوستهٔ استاندارد خوشهٔ K برای Orchestrator — فقط گزارش، هیچ سفارشی."""
    cluster_id = "K"

    def run(self, task: dict) -> list:
        ctx = task["ctx"]
        return portfolio_risk_message(
            ctx.get("paper_trades") or [], data_asof_ms=ctx["data_asof_ms"],
            candles_map=ctx.get("candles_map"), task_id=task.get("task_id"))
