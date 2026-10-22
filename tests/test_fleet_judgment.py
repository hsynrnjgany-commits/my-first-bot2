# آزمون‌های آفلاین موتور داوری ۴وضعیتی (بند ۴ دستور C) — بدون شبکه
# READ ONLY | PAPER ONLY | NO LIVE ORDERS

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.fleet.judgment import (judge_row, judge_cycle, uptrend_structure,
                                JUDGMENT_VERSION)   # noqa: E402
from src.fleet.contract import make_message          # noqa: E402


def mk_row(**kw):
    base = {
        "identity": "gecko:test-coin", "kind": "cex-aggregated",
        "asset_id": "test-coin", "symbol": "TEST", "name": "Test Coin",
        "network": None, "contract": None,
        "primary_source": "coingecko/coins-markets",
        "price_usd": 1.5, "market_cap_usd": 1e9, "volume_24h_usd": 5e6,
        "liquidity_usd": None,
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
    """الگوها: 'up' = HH+HL، 'down' = LH+LL، 'flat'. خروجی کندل بستهٔ ۱ساعته."""
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
            price += 0.35  # رشد پله‌ای → سقف/کف‌های بالاتر
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
                    "volume": 1000.0, "close_time": start + (i + 1) * 3600_000 - 1,
                    "closed": True})
    return out


def approx(a, b, tol=1e-9):
    return abs(a - b) <= tol


# ---------- ۱) price_rising — مشاهدهٔ خالص ----------

def test_price_rising_positive():
    j = judge_row(mk_row())
    assert j["price_rising"] is True
    assert j["rising_windows"] == ["1h", "24h", "7d"]
    assert j["falling_windows"] == ["30d"]


def test_price_rising_negative():
    j = judge_row(mk_row(change_pct={"1h": -0.5, "24h": -3.0,
                                     "7d": None, "30d": None}))
    assert j["price_rising"] is False
    assert j["uptrend"]["state"] is None          # بدون کندل حدس ممنوع
    assert j["uptrend"]["reason"] == "no_candles_in_cycle"


def test_price_rising_none_without_data():
    j = judge_row(mk_row(change_pct={"1h": None, "24h": None,
                                     "7d": None, "30d": None}))
    assert j["price_rising"] is None
    assert j["hypothesis"]["state"] == "unverified"
    assert "no_change_data" in j["hypothesis"]["missing"]


# ---------- ۲) rejected — دادهٔ ناسالم با علت ----------

def test_rejected_no_price():
    j = judge_row(mk_row(price_usd=None,
                         quality={"has_price": False, "has_volume": True,
                                  "zero_volume": False, "stale_price": False}))
    assert j["hypothesis"] == {"state": "rejected", "reason": "no_price_data"}
    assert j["price_rising"] is None and j["uptrend"] is None


def test_rejected_stale():
    j = judge_row(mk_row(quality={"has_price": True, "has_volume": True,
                                  "zero_volume": False, "stale_price": True,
                                  "age_ms": 9 * 3600 * 1000}))
    assert j["hypothesis"]["state"] == "rejected"
    assert j["hypothesis"]["reason"] == "stale_price"


def test_rejected_zero_volume():
    j = judge_row(mk_row(volume_24h_usd=0.0,
                         quality={"has_price": True, "has_volume": True,
                                  "zero_volume": True, "stale_price": False}))
    assert j["hypothesis"]["reason"] == "zero_volume"


# ---------- ۳) uptrend — فقط با کندل بسته ----------

def test_uptrend_confirmed_on_up_candles():
    j = judge_row(mk_row(identity="cex:toobit:spot:TESTUSDT",
                         asset_id="TESTUSDT"), candles=mk_candles("up"))
    assert j["uptrend"]["state"] is True
    assert j["uptrend"]["method"] == "hh_hl_closed_candles"
    assert j["uptrend"]["close_above_last_low"] is True


def test_uptrend_rejected_on_down_candles():
    j = judge_row(mk_row(), candles=mk_candles("down"))
    assert j["uptrend"]["state"] is False
    assert j["uptrend"]["reason"] == "no_higher_highs_and_lows"


def test_uptrend_unverified_without_candles():
    j = judge_row(mk_row())
    assert j["uptrend"]["state"] is None
    assert j["hypothesis"]["state"] == "unverified"


def test_uptrend_unverified_few_candles():
    j = judge_row(mk_row(), candles=mk_candles("up", n=6))
    assert j["uptrend"]["state"] is None
    assert j["uptrend"]["reason"] == "insufficient_closed_candles"


def test_structure_broken_when_close_below_last_low():
    cs = mk_candles("up")
    # کندل آخر: سقف بالاتر ولی بستن زیر آخرین کف سوئینگ → ساختار شکسته
    last_low = min(c["low"] for c in cs[-8:-2])
    cs[-1] = {**cs[-1], "close": last_low * 0.9, "open": last_low * 0.95}
    r = uptrend_structure(cs)
    assert r["state"] is False
    assert r["reason"] == "structure_broken_close_below_last_low"


# ---------- ۴) استقلال وضعیت‌ها — رشد قیمت ≠ فرصت ----------

def test_opportunity_never_from_price_rising_alone():
    j = judge_row(mk_row())   # price_rising=True ولی بدون کندل
    assert j["price_rising"] is True
    assert j["opportunity"]["state"] is None
    assert j["opportunity"]["reason"] == "uptrend_not_confirmed"


def test_opportunity_granted_with_uptrend_and_volume():
    j = judge_row(mk_row(), candles=mk_candles("up"))
    assert j["uptrend"]["state"] is True
    assert j["opportunity"]["state"] is True
    assert j["opportunity"]["evidence"]["volume_24h_usd"] == 5e6


def test_opportunity_denied_below_liquidity_floor():
    j = judge_row(mk_row(volume_24h_usd=500.0), candles=mk_candles("up"))
    assert j["uptrend"]["state"] is True
    assert j["opportunity"]["state"] is None
    assert j["opportunity"]["reason"] == "liquidity_volume_below_floor"
    assert j["hypothesis"]["state"] == "unverified"


def test_opportunity_via_liquidity_field():
    j = judge_row(mk_row(volume_24h_usd=None, liquidity_usd=250_000.0),
                  candles=mk_candles("up"))
    assert j["opportunity"]["state"] is True


def test_stablecoin_never_opportunity():
    j = judge_row(mk_row(stablecoin=True, symbol="USDT",
                         change_pct={"1h": 0.01, "24h": 0.02,
                                     "7d": 0.01, "30d": None}),
                  candles=mk_candles("up"))
    assert j["opportunity"]["state"] is None
    assert j["opportunity"]["reason"] == "stablecoin_not_opportunity"


# ---------- ۵) داوری چرخه + قرارداد ----------

def test_judge_cycle_counts_and_independence_guard():
    rows = [
        mk_row(identity="gecko:a", asset_id="a"),                    # rising
        mk_row(identity="gecko:b", asset_id="b",
               change_pct={"1h": -1.0, "24h": -2.0, "7d": None,
                           "30d": None}),                            # falling
        mk_row(identity="cex:toobit:spot:TESTUSDT", asset_id="TESTUSDT",
               symbol="TEST"),                                       # + candles
        mk_row(identity="gecko:c", asset_id="c",
               quality={"has_price": False, "has_volume": False,
                        "zero_volume": False, "stale_price": False}),  # reject
    ]
    cmap = {"TESTUSDT": mk_candles("up")}
    out = judge_cycle(rows, cmap, asof_ms=1730000000000)
    c = out["summary"]["counts"]
    assert c["total"] == 4
    assert c["price_rising"] == 2      # a و TESTUSDT (کندل up، تغییر مثبت)
    assert c["price_falling"] == 1
    assert c["uptrend_confirmed"] == 1
    assert c["uptrend_unverified"] == 2
    assert c["opportunity"] == 1
    assert c["rejected"] == 1
    # گارد استقلال داخل judge_cycle نقض را با ValueError می‌بندد — رسیدیم یعنی پاس


def test_judgment_event_contract():
    out = judge_cycle([mk_row()], {}, asof_ms=1730000001234)
    ev = out["event"]
    assert ev["cluster_id"] == "N" and ev["symbol"] == "JUDGMENT"
    assert ev["event_type"] == "JUDGMENT_SUMMARY"
    assert ev["validation_status"] == "OBSERVED"
    assert ev["event_id"]  # سازگار با قرارداد make_message
    assert "صرف رشد قیمت هرگز سیگنال خرید نیست" in ev["features"]["rule"]
    assert any("uptrend" in u for u in ev["uncertainty"])


def test_judge_cycle_dedup_key_stable():
    e1 = judge_cycle([mk_row()], {}, asof_ms=1730000001234)["event"]
    e2 = judge_cycle([mk_row()], {}, asof_ms=1730000001234)["event"]
    assert e1["event_id"] == e2["event_id"]  # ضدتکرار بین اجرا


def test_save_judgments_atomic(tmpdir=None):
    d = tempfile.mkdtemp()
    doc = {"version": JUDGMENT_VERSION, "counts": {"total": 1}}
    from src.fleet.judgment import save_judgments
    p = save_judgments(d, doc)
    assert os.path.exists(p)
    assert json.load(open(p, encoding="utf-8"))["counts"]["total"] == 1
    assert not os.path.exists(p + ".tmp")


# ---------- ۶) سوئینگ — جزئیات الگوریتم ----------

def test_swings_find_local_extrema():
    cs = mk_candles("up", n=24)
    from src.fleet.judgment import swings
    sw = swings(cs)
    assert len(sw["swing_highs"]) >= 2
    assert len(sw["swing_lows"]) >= 2
    # در الگوی صعودی، آخرین سوئینگ‌ها بالاتر از قبلی‌اند
    assert sw["swing_highs"][-1][1] > sw["swing_highs"][-2][1]
    assert sw["swing_lows"][-1][1] > sw["swing_lows"][-2][1]


def test_uptrend_structure_none_empty():
    assert uptrend_structure([])["state"] is None
    assert uptrend_structure(None)["state"] is None


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"---- {len(fns) - failed}/{len(fns)} passed ----")
    sys.exit(1 if failed else 0)
