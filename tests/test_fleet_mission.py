# آزمون‌های آفلاین مأموریت ۰۰۱ (بند ۷/۸ دستور) — بدون شبکه، بدون ادعا
# READ ONLY | PAPER ONLY | NO LIVE ORDERS

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.fleet.mission import (load_cycle, score_candidate,
                               rank_opportunities, build_mission_report,
                               save_mission_report, MISSION_VERSION,
                               W_MACRO, RR_MIN)  # noqa: E402


def _bos(event_id="ev-1", symbol="BTCUSDT", kind="BOS_BULLISH",
         t=1730000000000):
    return {"cluster_id": "D", "symbol": symbol, "event_type": kind,
            "event_id": event_id, "event_time_ms": t,
            "data_asof_ms": t, "ctx": {"interval": "1h"},
            "features": {"direction": "long" if kind == "BOS_BULLISH"
                         else "short"}}


def _cycle(tmp, *, events=(), judgment=None, status=None, learning=None):
    os.makedirs(tmp, exist_ok=True)
    if events:
        with open(os.path.join(tmp, "events.jsonl"), "w",
                  encoding="utf-8") as fh:
            for e in events:
                fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    if judgment:
        json.dump(judgment, open(os.path.join(
            tmp, "judgments-latest.json"), "w", encoding="utf-8"),
            ensure_ascii=False)
    if status:
        json.dump(status, open(os.path.join(
            tmp, "status.json"), "w", encoding="utf-8"),
            ensure_ascii=False)
    if learning:
        json.dump(learning, open(os.path.join(
            tmp, "learning-latest.json"), "w", encoding="utf-8"),
            ensure_ascii=False)
    return load_cycle(tmp)


# ---------- بارگذاری ----------

def test_load_cycle_empty_is_honest():
    with tempfile.TemporaryDirectory() as tmp:
        c = load_cycle(tmp)
        assert c["status"] == {} and c["judgment"] == {}
        assert c["events"] == [] and c["learning"] == {}


def test_load_cycle_skips_broken_lines():
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "events.jsonl"), "w") as fh:
            fh.write(json.dumps(_bos()) + "\n")
            fh.write("NOT-JSON-GARBAGE\n")
        c = load_cycle(tmp)
        assert len(c["events"]) == 1


# ---------- امتیازدهی ----------

def test_score_bos_full_quality_and_rr():
    sc = score_candidate({"source": "bos_event",
                          "volume_24h_usd": 5e6},
                         rising_windows=["1h", "24h", "7d"],
                         integrity_clean=True)
    assert sc["parts"]["data_quality"] == 20
    assert sc["parts"]["pattern"] == 20
    assert sc["parts"]["liquidity_cost"] == 15
    assert sc["parts"]["risk_reward"] == 15   # RR_PAPER=2 >= RR_MIN
    assert sc["parts"]["timeframe_alignment"] == 8   # round(10*3/4)
    assert sc["parts"]["macro_context"] == 0  # منبع کلان متصل نیست
    assert sc["total"] == 20 + 20 + 15 + 15 + 8 + 5 + 5 + 0


def test_score_unknown_liquidity_flags_risk():
    sc = score_candidate({"source": "bos_event"}, integrity_clean=True)
    assert sc["parts"]["liquidity_cost"] == 5
    assert sc["risk_flags"] == "execution_cost_unknown"


def test_score_broken_integrity_zero_data_points():
    sc = score_candidate({"source": "judgment", "volume_24h_usd": 5e6},
                         integrity_clean=False)
    assert sc["parts"]["data_quality"] == 0


# ---------- نامزدها و رتبه‌بندی ----------

def test_bos_dedup_by_event_id():
    evs = [_bos("ev-1"), _bos("ev-1"), _bos("ev-2", symbol="ETHUSDT")]
    c = _cycle(tempfile.mkdtemp(), events=evs)
    ranked = rank_opportunities(c)
    # dedup در استخراج: ev-1 تکراری همان‌جا رد شده (۲ رویداد مستقل)
    assert ranked["candidates"] == 2
    assert ranked["merged"] == 2


def test_bos_bearish_is_short():
    c = _cycle(tempfile.mkdtemp(), events=[_bos(kind="BOS_BEARISH")])
    ranked = rank_opportunities(c)
    assert ranked["top"][0]["direction"] == "short"


def test_judgment_opportunities_enter_ranking():
    judg = {"version": "mari.judgment/v1", "asof_ms": 1730000000000,
            "counts": {"total": 10, "opportunity": 1},
            "opportunities": [
                {"identity": "cex:toobit:spot:ZECUSDT", "symbol": "ZEC",
                 "evidence": {"volume_24h_usd": 2e6,
                              "liquidity_usd": None,
                              "min_usd_vol": 100000}}]}
    c = _cycle(tempfile.mkdtemp(), judgment=judg)
    ranked = rank_opportunities(c)
    assert ranked["candidates"] == 1
    row = ranked["top"][0]
    assert row["symbol"] == "ZEC" and row["direction"] == "long"
    assert row["pattern"] == "hh_hl_uptrend+liquidity"
    assert row["score_parts"]["liquidity_cost"] == 15


def test_correlated_signals_merged_with_sources_kept():
    judg = {"asof_ms": 1730000000000, "counts": {"opportunity": 1},
            "opportunities": [
                {"identity": "cex:toobit:spot:BTCUSDT", "symbol": "BTCUSDT",
                 "evidence": {"volume_24h_usd": 3e6, "liquidity_usd": 1e6}}]}
    c = _cycle(tempfile.mkdtemp(),
               events=[_bos("ev-btc", symbol="BTCUSDT")], judgment=judg)
    ranked = rank_opportunities(c)
    # هر دو منبع روی یک فرصت مستقل ادغام شده‌اند
    assert ranked["merged"] == 1
    row = ranked["top"][0]
    assert set(row["sources"]) == {"bos_event", "judgment"}


def test_no_candidates_is_honest_zero():
    c = _cycle(tempfile.mkdtemp())
    ranked = rank_opportunities(c)
    assert ranked["candidates"] == 0 and ranked["top"] == []
    assert ranked["confirmed"] == 0 and ranked["rejected"] == 0


# ---------- گزارش نهایی ----------

def test_report_sections_labels_and_rule():
    status = {"cycle_id": "c-1", "generated_at": "2026-10-24T00:00:00Z",
              "tasks_total": 52, "tasks_executed": 52,
              "events_collected": 165, "errors": [],
              "health": {c: {"status": "OK"} for c in "DCIKNME"}}
    judg = {"asof_ms": 1730000000000,
            "counts": {"total": 1390, "price_rising": 454,
                       "price_falling": 353, "uptrend_confirmed": 4,
                       "opportunity": 1, "rejected": 576},
            "opportunities": [
                {"identity": "cex:toobit:spot:ZECUSDT", "symbol": "ZEC",
                 "evidence": {"volume_24h_usd": 2e6}}]}
    c = _cycle(tempfile.mkdtemp(), events=[_bos()], judgment=judg,
               status=status)
    doc = build_mission_report(c)
    assert doc["version"] == MISSION_VERSION
    s = doc["sections"]
    assert s["audit"] == "PASS" and s["discovery"] == "PASS"
    assert s["telegram"] == "BLOCKED"  # صادقانه — سیم‌کشی ناتمام
    assert doc["coverage"]["judged_total"] == 1390
    assert doc["coverage"]["confirmed"] >= 1
    assert doc["cycle"]["clusters_ok"] == 7
    assert any("READ ONLY" in x for x in [doc["rule"]])
    assert "منبع کلان" in doc["limitations"][0]


def test_save_mission_report_atomic():
    with tempfile.TemporaryDirectory() as tmp:
        doc = {"version": MISSION_VERSION}
        path = save_mission_report(tmp, doc)
        assert os.path.exists(path)
        assert json.load(open(path, encoding="utf-8"))["version"] \
            == MISSION_VERSION
        assert not os.path.exists(path + ".tmp")


def _write_snapshot(tmp, rows):
    json.dump({"schema": "mari.registry/v1", "rows": rows},
              open(os.path.join(tmp, "global-assets-snapshot.json"), "w",
                   encoding="utf-8"), ensure_ascii=False)


def test_bos_volume_evidence_from_snapshot():
    """بند ۷: نامزد BOS باید شواهد حجم واقعی اسنپ‌شات را بگیرد — نه پرچم ناشناخته."""
    t = 1_730_000_000_000
    with tempfile.TemporaryDirectory() as tmp:
        _write_snapshot(tmp, [{"asset_id": "BTCUSDT",
                               "identity": "cex:toobit:spot:BTCUSDT",
                               "volume_24h_usd": 5_000_000.0}])
        cycle = load_cycle(tmp)
        cycle["events"] = [_bos(t=t)]
        ranked = rank_opportunities(cycle)
        assert ranked["confirmed"] == 1
        row = ranked["top"][0]
        assert row["score_parts"]["liquidity_cost"] == 15
        assert row["risk_flags"] is None


def test_stale_bos_excluded_by_freshness():
    """BOS کهنهٔ ۴۸ ساعته فرصتِ فعلی نیست — فقط BOS تازهٔ ۲۴ ساعت."""
    now = 1_730_000_000_000
    old = _bos(event_id="old", t=now - 48 * 3600 * 1000)
    fresh = _bos(event_id="fresh", symbol="ETHUSDT", t=now - 1 * 3600 * 1000)
    with tempfile.TemporaryDirectory() as tmp:
        cycle = load_cycle(tmp)
        cycle["events"] = [old, fresh]
        ranked = rank_opportunities(cycle)
        assert ranked["candidates"] == 1
        assert ranked["top"][0]["symbol"] == "ETHUSDT"
