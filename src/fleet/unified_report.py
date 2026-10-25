# MARI — unified_report: بستهٔ ترکیبی per-symbol از سه آزمایشگاه آفلاین — فقط گزارش
# MODE: READ ONLY | PAPER ONLY | NO LIVE ORDERS
#
# خاستگاه: ادامهٔ EXECUTION ORDER 001 (2026-10-25) — تنها کار باقی‌ماندهٔ
# خودگردان: گزارش آزمایشگاه یکپارچه (strategy_lab × cost_model × vol_target).
# پرسش: کدام نمادها لبهٔ پایه دارند، کدام لبه پس از هزینهٔ اجرا زنده می‌ماند،
# و کدام با مقیاس‌دهی نوسان بهتر می‌شوند — همه در یک بستهٔ per-symbol قطعی.
# ترکیب، نه ادغام: این ماژول هیچ منطق جدیدی به شبیه‌ساز اضافه نمی‌کند؛
# فقط خروجی سه آزمایشگاه را روی مجموعهٔ یکسان معاملات کنار هم می‌گذارد.
# هر خروجی فقط REPORTED یا INSUFFICIENT_EVIDENCE است؛ برچسب‌های per-symbol
# توصیفی‌اند (NO_BASELINE_EDGE / EDGE_ERODED_BY_COSTS / ...) — هیچ آستانه‌ای
# «موفقیت» جعل نمی‌شود. بدون مهر زمانی → قطعی و بازتولیدپذیر.

import json

from . import cost_model
from . import evaluator
from . import strategy_lab
from . import vol_target

UNIFIED_METHOD = "unified_report/composition_v1"


def _verdict_label(n_closed: int, min_samples: int, raw_sum, adj_sum,
                   spread_ok: bool) -> str:
    """برچسب صادقانهٔ per-symbol — توصیف وضعیت، نه قضاوت موفقیت."""
    if n_closed < min_samples:
        return "INSUFFICIENT_EVIDENCE"
    if raw_sum is None or raw_sum <= 0:
        return "NO_BASELINE_EDGE"
    if not spread_ok:
        return "SPREAD_NOT_ESTIMABLE"
    if adj_sum is None:
        return "INSUFFICIENT_EVIDENCE"
    return "EDGE_SURVIVES_PROXY_COSTS" if adj_sum > 0 \
        else "EDGE_ERODED_BY_COSTS"


def _per_symbol_block(sym: str, sym_trades: list, candles: list,
                      scaled_all: list, *, fee_pct: float,
                      slippage_bps_list: tuple, min_samples: int) -> dict:
    """بستهٔ یک نماد: خام + هزینه (اسپرد خود نماد) + نوسان + سربه‌سر."""
    closed = [t for t in sym_trades if t.get("exit_reason") in ("TP", "SL")]
    raw = cost_model.realized_metrics(closed, key="net_pct")
    spread_bps = cost_model.corwin_schultz_spread_bps(candles)
    spread_ok = isinstance(spread_bps, (int, float))
    adj = delta_cost = be = None
    if spread_ok:
        adj = cost_model.realized_metrics(
            cost_model.apply_execution_costs(
                sym_trades, spread_bps=float(spread_bps),
                slippage_bps=0.0, fee_pct=fee_pct),
            key="net_pct_adj")
        if raw["sum_net_pct"] is not None and adj["sum_net_pct"] is not None:
            delta_cost = round(adj["sum_net_pct"] - raw["sum_net_pct"], 6)
        be = cost_model.break_even_slippage_bps(
            closed, spread_bps=float(spread_bps), fee_pct=fee_pct)
    sym_scaled = [t for t in scaled_all if t.get("symbol") == sym]
    closed_scaled = [t for t in sym_scaled
                     if t.get("exit_reason") in ("TP", "SL")]
    vol_scaled = cost_model.realized_metrics(closed_scaled,
                                             key="net_pct_scaled")
    delta_vol = None
    if raw["sum_net_pct"] is not None \
            and vol_scaled["sum_net_pct"] is not None:
        delta_vol = round(vol_scaled["sum_net_pct"] - raw["sum_net_pct"], 6)
    worst = None
    if spread_ok and slippage_bps_list:
        worst = cost_model.realized_metrics(
            cost_model.apply_execution_costs(
                sym_trades, spread_bps=float(spread_bps),
                slippage_bps=float(max(slippage_bps_list)),
                fee_pct=fee_pct),
            key="net_pct_adj")
    label = _verdict_label(raw["n_closed"], min_samples,
                           raw["sum_net_pct"],
                           adj["sum_net_pct"] if adj else None, spread_ok)
    return {
        "n_closed": raw["n_closed"], "n_open": raw["n_open"],
        "raw": raw,
        "spread_bps": round(float(spread_bps), 4) if spread_ok else None,
        "cost_adjusted": adj, "delta_cost_pp": delta_cost,
        "worst_case": worst,
        "break_even": be,
        "vol_scaled": vol_scaled, "delta_vol_pp": delta_vol,
        "verdict": label,
    }


def unified_report(candles_map: dict, trades: list, *,
                   fee_pct: float = evaluator.FEE_PCT,
                   slippage_bps_list=cost_model.DEFAULT_SLIPPAGE_BPS,
                   lookback: int = vol_target.DEFAULT_LOOKBACK,
                   target_vol_pct: float = vol_target.DEFAULT_TARGET_VOL_PCT,
                   max_scale: float = vol_target.DEFAULT_MAX_SCALE,
                   min_scale: float = vol_target.DEFAULT_MIN_SCALE,
                   min_samples: int = evaluator.MIN_SAMPLES,
                   events=None, wf_config=None) -> dict:
    """بستهٔ یکپارچهٔ per-symbol: خط پایه × هزینهٔ اجرا × هدف‌گذاری نوسان.

    candles_map: {symbol: candles} — کندل بستهٔ ۱ساعته (قرارداد parse_klines).
    trades: خروجی evaluator.simulate_trades (قرارداد contract.make_message).
    events + wf_config (اختیاری): اگر هردو داده شود، بخش walk_forward
    strategy_lab.anchored_walk_forward نیز در بسته می‌آید.
    خروجی: JSON فقط‌گزارشی — بدون شبکه، بدون نوشتن فایل، قطعی، بدون مهر زمانی.
    """
    base = {
        "method": UNIFIED_METHOD,
        "components": {"engine": evaluator.METHOD,
                       "cost": cost_model.COST_METHOD,
                       "vol": vol_target.VOL_METHOD,
                       "walk_forward": strategy_lab.LAB_METHOD},
        "mode": "READ ONLY | PAPER ONLY | NO LIVE ORDERS",
        "n_symbols": len(candles_map),
        "verdict": "REPORTED",
        "per_symbol": {},
        "limitations": [
            "ترکیب سه آزمایشگاه است، نه آزمون تازه — هیچ مدل یا آستانهٔ جدیدی "
            "اضافه نشده و برچسب PROXY_NOT_ORDER_BOOK cost_model پابرجاست",
            "برچسب‌های per-symbol توصیفی‌اند؛ EDGE_SURVIVES_PROXY_COSTS به "
            "معنای سودآوری تضمین‌شده نیست — فقط جمع خالص مثبت زیر پوشش هزینه",
            "هدف‌گذاری نوسان لبهٔ منفی را حذف نمی‌کند؛ لغزش واقعی دفتر سفارش "
            "دیده نمی‌شود؛ سربه‌سر فقط زیر مدل پوشش معنا دارد",
            "خروجی فقط REPORTED است — هیچ آستانه‌ای موفقیت جعل نشده",
        ],
    }
    if not candles_map or not trades:
        return dict(base, verdict="INSUFFICIENT_EVIDENCE",
                    reason="EMPTY_INPUT_NO_TRADES_OR_CANDLES")
    matched = [t for t in trades if t.get("symbol") in candles_map]
    n_unmatched = len(trades) - len(matched)
    closed = [t for t in matched if t.get("exit_reason") in ("TP", "SL")]
    base["n_trades_total"] = len(trades)
    base["n_unmatched_trades"] = n_unmatched
    base["n_closed"] = len(closed)
    if not closed:
        return dict(base, verdict="INSUFFICIENT_EVIDENCE",
                    reason="NO_CLOSED_TRADES")

    # مقیاس‌دهی نوسان — یک‌بار روی کل مجموعه؛ per-symbol بازترکیب همان خروجی
    scaled_all, scaling_summary = vol_target.apply_vol_scaling(
        matched, candles_map, lookback=lookback,
        target_vol_pct=target_vol_pct, max_scale=max_scale,
        min_scale=min_scale)

    per_symbol = {}
    for sym in sorted(candles_map):
        per_symbol[sym] = _per_symbol_block(
            sym, [t for t in matched if t.get("symbol") == sym],
            candles_map[sym], scaled_all, fee_pct=fee_pct,
            slippage_bps_list=tuple(slippage_bps_list),
            min_samples=min_samples)
    base["per_symbol"] = per_symbol

    # پرتفوی — اسپرد میانهٔ نمادها (هم‌راستا با cost_report)
    spreads = [b["spread_bps"] for b in per_symbol.values()
               if isinstance(b["spread_bps"], (int, float))]
    spread_used = cost_model._median(spreads) if spreads else None
    raw_total = cost_model.realized_metrics(closed, key="net_pct")
    adj_total = worst_total = be_total = None
    spread_ok = isinstance(spread_used, (int, float))
    if spread_ok:
        adj_total = cost_model.realized_metrics(
            cost_model.apply_execution_costs(
                matched, spread_bps=float(spread_used),
                slippage_bps=0.0, fee_pct=fee_pct),
            key="net_pct_adj")
        worst_total = cost_model.realized_metrics(
            cost_model.apply_execution_costs(
                matched, spread_bps=float(spread_used),
                slippage_bps=float(max(slippage_bps_list)),
                fee_pct=fee_pct),
            key="net_pct_adj")
        be_total = cost_model.break_even_slippage_bps(
            closed, spread_bps=float(spread_used), fee_pct=fee_pct)
    by_dir_raw = {}
    for d in ("long", "short"):
        sub = [t for t in closed if t.get("direction") == d]
        if sub:
            by_dir_raw[d] = cost_model.realized_metrics(sub, key="net_pct")
    by_dir_vol = {}
    for d in ("long", "short"):
        sub = [t for t in scaled_all
               if t.get("direction") == d
               and t.get("exit_reason") in ("TP", "SL")]
        if sub:
            by_dir_vol[d] = vol_target.direction_block(sub,
                                                       min_samples=min_samples)
    base["portfolio"] = {
        "raw": raw_total,
        "by_direction_raw": by_dir_raw,
        "spread_bps": round(float(spread_used), 4) if spread_ok else None,
        "cost_adjusted": adj_total, "worst_case": worst_total,
        "break_even": be_total,
        "scaling_summary": scaling_summary,
        "by_direction_vol": by_dir_vol,
    }

    # خوانش تلفیقی صادقانه
    label = _verdict_label(len(closed), min_samples, raw_total["sum_net_pct"],
                           adj_total["sum_net_pct"] if adj_total else None,
                           spread_ok)
    counts = {}
    for b in per_symbol.values():
        counts[b["verdict"]] = counts.get(b["verdict"], 0) + 1
    base["combined_reading"] = {
        "label": label,
        "baseline_sum_pp": raw_total["sum_net_pct"],
        "after_spread_sum_pp": adj_total["sum_net_pct"] if adj_total else None,
        "worst_case_sum_pp": worst_total["sum_net_pct"] if worst_total
        else None,
        "break_even_bps": be_total["bps"] if be_total else None,
        "per_symbol_verdict_counts": counts,
        "note": "برچسب توصیفی است؛ سودآوری پابرجا نیازمند هزینهٔ دفتر سفارش "
                "واقعی (M-5) و دادهٔ عمیق‌تر است",
    }

    if events is not None and wf_config:
        base["walk_forward"] = strategy_lab.anchored_walk_forward(
            candles_map, events, wf_config)

    if len(closed) < min_samples:
        return dict(base, verdict="INSUFFICIENT_EVIDENCE",
                    reason="CLOSED_BELOW_MIN_SAMPLES",
                    min_samples_required=min_samples)
    return base


def canonical_json(report: dict) -> str:
    """نمایش قطعی برای آزمون بازتولیدپذیری (کل خروجی بدون مهر زمانی است)."""
    return json.dumps(report, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
