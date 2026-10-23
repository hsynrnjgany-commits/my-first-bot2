# آزمون‌های آفلاین موتور یادگیری‌سنج (بند ۷ پلن AI) — بدون شبکه
# READ ONLY | PAPER ONLY | NO LIVE ORDERS

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.fleet.learning import (extract_predictions, record_cycle,
                                resolve_cycle, learning_summary,
                                LEARNING_VERSION, MIN_SAMPLES)  # noqa: E402
from src.fleet.judgment import judge_row   # noqa: E402


def mk_row(**kw):
    base = {
        "identity": "gecko:test-coin", "kind": "cex-aggregated",
        "asset_id": "test-coin", "symbol": "TEST", "name": "Test Coin",
        "network": None, "contract": None,
        "primary_source": "coingecko/coins-markets",
        "price_usd": 100.0, "market_cap_usd": 1e9,
        "volume_24h_usd": 5e6, "liquidity_usd": None,
        "change_pct": {"1h": 0.5, "24h": 3.2, "7d": 10.0, "30d": -2.0},
        "wrapped_hint": False, "stablecoin": False,
        "fetched_at_ms": 1730000000000, "data_asof_ms": 1730000000000,
        "quality": {"has_price": True, "has_volume": True,
                    "zero_volume": False, "stale_price": False,
                    "age_ms": 1000},
        "healthy": True,
    }
    base.update(kw)
    return base


def mk_candles(pattern, n=40, start=None):
    if start is None:
        start = 1730000000000 - 3600_000 * n
    out = []
    price = 100.0
    for i in range(n):
        if pattern == "up":
            wave = (i % 8)
            o = price + wave * 0.4
            c = o + 0.8 + (0.5 if i % 8 in (0, 1) else 0.0)
            h = max(o, c) + 0.3
            l = min(o, c) - 0.3
            price += 0.35
        elif pattern == "down":
            wave = (i % 8)
            o = price - wave * 0.4
            c = o - 0.8
            h = max(o, c) + 0.3
            l = min(o, c) - 0.3
            price -= 0.35
        else:
            o = 100.0 + (i % 2) * 0.1
            c = 100.0 - (i % 2) * 0.1
            h = o + 0.2
            l = c - 0.2
        out.append({"open_time": start + i * 3600_000, "open": o,
                    "high": h, "low": l, "close": c,
                    "close_time": start + (i + 1) * 3600_000 - 1})
    return out


def _judged(rows, candles_map=None):
    # همان قرارداد judge_cycle: کندل‌ها با «نماد» کلید خورده‌اند
    return [judge_row(r, candles=(candles_map or {}).get(r.get("symbol")))
            for r in rows]


# ---------- استخراج ----------

def test_extract_uptrend_confirmed_uses_closed_candle_price():
    candles = {"TEST": mk_candles("up")}
    j = _judged([mk_row()], candles)
    out = extract_predictions(j, [mk_row()], candles)
    preds = out["predictions"]
    assert preds, "پیش‌بینی uptrend_confirmed باید ثبت شود"
    p = [x for x in preds if x["class"] == "uptrend_confirmed"][0]
    assert p["direction"] == "long"
    assert p["ref_source"] == "closed_candle"
    assert p["ref_price"] == candles["TEST"][-1]["close"]
    assert p["state"] == "pending"


def test_extract_rising_and_falling_observations():
    candles = {"TEST": mk_candles("flat")}
    rows = [mk_row(change_pct={"1h": 0.5, "24h": 3.2, "7d": 10.0,
                               "30d": -2.0}),
            mk_row(identity="gecko:down-coin", asset_id="down-coin",
                   symbol="DOWN",
                   change_pct={"1h": -0.4, "24h": -2.0, "7d": -5.0,
                               "30d": -9.0})]
    j = _judged(rows, {})
    out = extract_predictions(j, rows, {})
    classes = {p["prediction_id"]: p for p in out["predictions"]}
    assert classes["gecko:test-coin:rising_obs"]["direction"] == "long"
    assert classes["gecko:down-coin:falling_obs"]["direction"] == "short"
    # قیمت مرجع از ردیف دفتر (کندلی نیست)
    assert classes["gecko:test-coin:rising_obs"]["ref_source"] == "row_price"


def test_extract_rejected_is_recorded_not_scored():
    rows = [mk_row(price_usd=None, quality={"has_price": False,
                                            "has_volume": True,
                                            "zero_volume": False,
                                            "stale_price": False,
                                            "age_ms": 1000})]
    j = _judged(rows, {})
    out = extract_predictions(j, rows, {})
    assert out["predictions"] == []
    assert out["skipped"]["no_directional_claim"] >= 1


def test_extract_skips_when_no_price_reference():
    rows = [mk_row(price_usd=None)]
    # داوری با کندل flat → price_rising None، uptrend None → ادعای جهت نیست
    j = _judged([mk_row(price_usd=None)], {})
    out = extract_predictions(j, rows, {})
    assert all(p["class"] not in ("uptrend_confirmed", "opportunity")
               for p in out["predictions"])


def test_opportunity_only_with_volume_floor():
    candles = {"TEST": mk_candles("up")}
    poor = mk_row(volume_24h_usd=1_000.0)  # زیر کف ۱۰۰هزار دلاری
    j = _judged([poor], candles)
    out = extract_predictions(j, [poor], candles)
    assert not any(p["class"] == "opportunity" for p in out["predictions"])
    assert any(p["class"] == "uptrend_confirmed" for p in out["predictions"])


# ---------- ثبت و حل‌وفصل ----------

def _setup(tmp):
    candles = {"TEST": mk_candles("up")}
    rows = [mk_row()]
    j = _judged(rows, candles)
    ext = extract_predictions(j, rows, candles)
    rec = record_cycle(ext["predictions"], asof_ms=1730000000000,
                       state_dir=tmp)
    return candles, rows, ext, rec


def test_record_roundtrip_and_idempotency():
    with tempfile.TemporaryDirectory() as tmp:
        candles, rows, ext, rec = _setup(tmp)
        assert rec["recorded"] >= 1
        assert rec["duplicates"] == 0
        # ثبت دوبارهٔ همان چرخه → تکراری شمرده می‌شود، دفتر دوبرابر نمی‌شود
        rec2 = record_cycle(ext["predictions"], asof_ms=1730000000000,
                            state_dir=tmp)
        assert rec2["recorded"] == 0
        assert rec2["duplicates"] >= 1
        path = os.path.join(tmp, "learning-ledger.jsonl")
        lines = [l for l in open(path, encoding="utf-8") if l.strip()]
        assert len(lines) == rec["recorded"]


def test_resolve_long_correct_and_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        candles, rows, ext, rec = _setup(tmp)
        # چرخهٔ بعد: قیمت ۳۰٪ بالاتر → هر دو پیش‌بینی long درست
        rows2 = [mk_row(price_usd=130.0)]
        res = resolve_cycle(rows2, {}, asof_ms=1730003600000,
                            state_dir=tmp)
        assert res["resolved"] >= 1
        ledger = [json.loads(l) for l in
                  open(os.path.join(tmp, "learning-ledger.jsonl"),
                       encoding="utf-8") if l.strip()]
        done = [r for r in ledger if r["state"] == "resolved"]
        assert all(abs(r["forward_return_pct"]) > 0 for r in done)
        assert all(r["correct"] is True for r in done)
        # حل‌وفصل دوباره → هیچ چیز تازه حل نمی‌شود (ایدمپوتنت)
        res2 = resolve_cycle(rows2, {}, asof_ms=1730007200000,
                             state_dir=tmp)
        assert res2["resolved"] == 0


def test_resolve_short_side_inverse():
    with tempfile.TemporaryDirectory() as tmp:
        rows = [mk_row(identity="gecko:down-coin", asset_id="down-coin",
                       symbol="DOWN",
                       change_pct={"1h": -0.4, "24h": -2.0, "7d": -5.0,
                                   "30d": -9.0})]
        j = _judged(rows, {})
        ext = extract_predictions(j, rows, {})
        record_cycle(ext["predictions"], asof_ms=1730000000000,
                     state_dir=tmp)
        # چرخهٔ بعد: قیمت پایین‌تر → short درست
        rows2 = [mk_row(identity="gecko:down-coin", asset_id="down-coin",
                        symbol="DOWN", price_usd=90.0)]
        res = resolve_cycle(rows2, {}, asof_ms=1730003600000,
                            state_dir=tmp)
        assert res["resolved"] >= 1
        ledger = [json.loads(l) for l in
                  open(os.path.join(tmp, "learning-ledger.jsonl"),
                       encoding="utf-8") if l.strip()]
        falling = [r for r in ledger
                   if r["class"] == "falling_obs" and r["state"] == "resolved"]
        assert falling and all(r["correct"] is True for r in falling)


def test_resolve_uses_fresh_candle_over_row_price():
    with tempfile.TemporaryDirectory() as tmp:
        candles, rows, ext, rec = _setup(tmp)
        candles2 = {"TEST": mk_candles("flat", start=1730003600000)}
        res = resolve_cycle([mk_row(price_usd=999.0)], candles2,
                            asof_ms=1730003600000, state_dir=tmp)
        assert res["resolved"] >= 1
        ledger = [json.loads(l) for l in
                  open(os.path.join(tmp, "learning-ledger.jsonl"),
                       encoding="utf-8") if l.strip()]
        done = [r for r in ledger if r["state"] == "resolved"]
        assert all(r["resolution_source"] == "closed_candle"
                   for r in done)


def test_unknown_asset_stays_pending():
    with tempfile.TemporaryDirectory() as tmp:
        candles, rows, ext, rec = _setup(tmp)
        res = resolve_cycle([mk_row(identity="gecko:other",
                                    asset_id="other")], {},
                            asof_ms=1730003600000, state_dir=tmp)
        assert res["resolved"] == 0
        assert res["still_pending"] == rec["recorded"]


# ---------- خلاصهٔ صادقانه ----------

def test_summary_insufficient_evidence_below_floor():
    with tempfile.TemporaryDirectory() as tmp:
        candles, rows, ext, rec = _setup(tmp)
        rows2 = [mk_row(price_usd=105.0)]
        resolve_cycle(rows2, {}, asof_ms=1730003600000, state_dir=tmp)
        out = learning_summary(asof_ms=1730007200000, state_dir=tmp)
        s = out["summary"]
        assert s["version"] == LEARNING_VERSION
        assert s["resolved_total"] >= 1
        for cls in s["classes"].values():
            assert cls["n"] < MIN_SAMPLES
            assert cls["hit_rate"] is None
            assert cls["verdict"] == "insufficient_evidence"


def test_summary_observation_only_after_floor():
    with tempfile.TemporaryDirectory() as tmp:
        # ۳۰ نمونهٔ مصنوعی از یک کلاس، همگی long و همگی درست
        preds = [{"v": LEARNING_VERSION,
                  "prediction_id": f"gecko:c{i}:rising_obs",
                  "identity": f"gecko:c{i}", "symbol": f"C{i}",
                  "class": "rising_obs", "direction": "long",
                  "ref_price": 100.0, "ref_source": "row_price",
                  "asof_ms": 1730000000000, "state": "pending"}
                 for i in range(MIN_SAMPLES)]
        record_cycle(preds, asof_ms=1730000000000, state_dir=tmp)
        rows = [mk_row(identity=f"gecko:c{i}", asset_id=f"c{i}",
                       symbol=f"C{i}", price_usd=101.0)
                for i in range(MIN_SAMPLES)]
        resolve_cycle(rows, {}, asof_ms=1730003600000, state_dir=tmp)
        out = learning_summary(asof_ms=1730007200000, state_dir=tmp)
        cls = out["summary"]["classes"]["rising_obs"]
        assert cls["n"] == MIN_SAMPLES
        assert cls["hit_rate"] == 1.0
        assert cls["verdict"] == "observation_only"


def test_summary_event_contract_and_persistence():
    with tempfile.TemporaryDirectory() as tmp:
        candles, rows, ext, rec = _setup(tmp)
        resolve_cycle([mk_row(price_usd=105.0)], {},
                      asof_ms=1730003600000, state_dir=tmp)
        out = learning_summary(asof_ms=1730007200000, state_dir=tmp,
                               task_id="t-learning")
        ev = out["event"]
        assert ev["event_type"] == "LEARNING_SUMMARY"
        assert ev["cluster_id"] == "N"
        assert ev["uncertainty"], "رویداد بدون عدم‌قطعیت ممنوع"
        path = os.path.join(tmp, "learning-latest.json")
        doc = json.load(open(path, encoding="utf-8"))
        assert doc["version"] == LEARNING_VERSION
        assert "rule" in doc
