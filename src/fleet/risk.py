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
