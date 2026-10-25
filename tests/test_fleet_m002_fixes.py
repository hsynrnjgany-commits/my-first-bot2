# MARI — آزمون آفلاین اصلاحات گزارش MISSION 002 (A-1/A-2/B-1/B-6/C-1/C-3)
# صفر شبکهٔ واقعی؛ همهٔ منابع با opener جعلی مسخره می‌شوند.

import json
import os
import tempfile
import unittest
import urllib.error

from fleet_loader import load_fleet

fleet = load_fleet()
sources = fleet.sources
evaluator = fleet.evaluator
contract = fleet.contract
orchestrator = fleet.orchestrator

HOUR_MS = 3_600_000
NOW_MS = 1_800_000_000_000


def row(open_time, close=100.0):
    return [open_time, 100.0, close + 1.0, 99.0, close, 10.0]


def kline_payload(open_times, close=100.0):
    return [row(t, close) for t in open_times]


class FakeResponse:
    def __init__(self, raw):
        self._raw = raw

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeOpener:
    """مسیریابی دامنه‌محور؛ بدون فراگمنت مشترک بین toobit/binance."""

    def __init__(self, routes):
        self.routes = routes  # {"toobit": payload|Error, ...}

    def open(self, request, timeout=None):
        url = getattr(request, "full_url", str(request))
        for frag, item in self.routes.items():
            if frag in url:
                if isinstance(item, Exception):
                    raise item
                return FakeResponse(json.dumps(item).encode("utf-8"))
        raise urllib.error.HTTPError(url, 404, "no route", None, None)


def err_opener(*frags):
    return FakeOpener({f: urllib.error.HTTPError(f, 500, "down", None, None)
                       for f in frags})


class TestFrozenSeriesGuard(unittest.TestCase):
    """اصلاح A-1: سری منجمد باید رد شود، نه تحلیل."""

    def test_is_stale_series_math(self):
        fresh = [{"open_time": NOW_MS - 2 * HOUR_MS}]
        stale = [{"open_time": NOW_MS - 31 * HOUR_MS}]
        self.assertFalse(sources.is_stale_series(fresh, HOUR_MS, NOW_MS))
        self.assertTrue(sources.is_stale_series(stale, HOUR_MS, NOW_MS))
        # گارد خاموش وقتی now_ms=None (سازگاری رفتار قدیمی)
        self.assertFalse(sources.is_stale_series(stale, HOUR_MS, None))
        self.assertFalse(sources.is_stale_series([], HOUR_MS, NOW_MS))

    def test_fetch_klines_skips_stale_source(self):
        stale = kline_payload([NOW_MS - 31 * HOUR_MS])
        fresh = kline_payload([NOW_MS - 2 * HOUR_MS])
        op = FakeOpener({"toobit": stale, "binance": fresh})
        out = sources.fetch_klines("BTCUSDT", "1h", 200, op, now_ms=NOW_MS)
        self.assertTrue(out["ok"])
        self.assertEqual(out["source"], "binance")
        types = [e["error_type"] for e in out["errors"]]
        self.assertIn("STALE_FROZEN_SERIES", types)
        self.assertEqual(types[0], "STALE_FROZEN_SERIES")  # بهوبیت اول رد شد

    def test_fetch_klines_all_stale_ok_false(self):
        stale = kline_payload([NOW_MS - 31 * HOUR_MS])
        op = FakeOpener({"toobit": stale})
        out = sources.fetch_klines("BTCUSDT", "1h", 200, op, now_ms=NOW_MS)
        self.assertFalse(out["ok"])
        types = [e["error_type"] for e in out["errors"]]
        self.assertIn("STALE_FROZEN_SERIES", types)

    def test_guard_off_without_now_ms_backward_compat(self):
        stale = kline_payload([NOW_MS - 31 * HOUR_MS])
        op = FakeOpener({"toobit": stale})
        out = sources.fetch_klines("BTCUSDT", "1h", 200, op)  # now_ms=None
        self.assertTrue(out["ok"])
        self.assertEqual(out["source"], "toobit")


class TestRealizedBlock(unittest.TestCase):
    """اصلاح A-2: بلوک realized فقط معاملات بستهٔ TP/SL."""

    @staticmethod
    def _trades():
        return [
            {"symbol": "AAAUSDT", "net_pct": 1.8, "exit_reason": "TP",
             "entry_time_ms": 1000, "exit_time_ms": 2000,
             "mfe_pct": 2.0, "mae_pct": 0.1},
            {"symbol": "BBBUSDT", "net_pct": -0.9, "exit_reason": "SL",
             "entry_time_ms": 3000, "exit_time_ms": 4000,
             "mfe_pct": 0.2, "mae_pct": 1.0},
            {"symbol": "CCCUSDT", "net_pct": 0.5, "exit_reason": "OPEN",
             "entry_time_ms": 5000, "exit_time_ms": None,
             "mfe_pct": 0.5, "mae_pct": 0.0},
        ]

    def test_realized_counts_only_closed(self):
        res = evaluator.evaluate(self._trades())
        self.assertEqual(res["n"], 3)          # بالادستی همه (سازگار عقب)
        rl = res["realized"]
        self.assertEqual(rl["n_closed"], 2)
        self.assertAlmostEqual(rl["sum_net_pct"], 0.9, places=6)
        self.assertAlmostEqual(rl["profit_factor"], 2.0, places=4)
        self.assertAlmostEqual(rl["win_rate"], 0.5, places=4)
        # kelly بلوک realized باید فقط روی بسته‌ها باشد (نه ۱+۰٫۹−۰٫۵ مختلط)
        closed_nets = [1.8, -0.9]
        self.assertEqual(rl["kelly_fraction_paper"],
                         evaluator.kelly_fraction_paper(closed_nets))

    def test_realized_empty_when_all_open(self):
        trades = [dict(self._trades()[0], net_pct=0.3, symbol="DDDUSDT",
                       exit_reason="OPEN")]
        rl = evaluator.evaluate(trades)["realized"]
        self.assertEqual(rl["n_closed"], 0)
        self.assertIsNone(rl["win_rate"])
        self.assertIsNone(rl["kelly_fraction_paper"])


class TestAppendEventsDuplicateIds(unittest.TestCase):
    """اصلاح B-6: شناسهٔ رویدادهای dedup-شده گزارش شود."""

    def _ev(self, eid):
        return {"event_id": eid, "event_type": "TREND_ASSESSMENT",
                "symbol": "TESTUSDT"}

    def test_duplicate_ids_returned(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "events.jsonl")
            first = contract.append_events(path, [self._ev("e1")])
            self.assertEqual(first["written"], 1)
            self.assertEqual(first["duplicate_event_ids"], [])
            second = contract.append_events(path, [self._ev("e1"),
                                                   self._ev("e2")])
            self.assertEqual(second["written"], 1)
            self.assertEqual(second["duplicates_skipped"], 1)
            self.assertEqual(second["duplicate_event_ids"], ["e1"])
            self.assertFalse(second["duplicate_event_ids_truncated"])


class TestOrchestratorSkipDetails(unittest.TestCase):
    """اصلاح B-1/C-3: ریشهٔ skip و مهر first_seen."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = os.path.join(self.tmp.name, "fleet")
        self.orch = orchestrator.Orchestrator(state_dir=self.state,
                                              max_retries=1)
        self.orch.register(GoodCluster())
        self.task = {"cluster_id": "D", "symbol": "BTCUSDT", "candles": [],
                     "ctx": {"interval": "1h", "data_asof_ms": 1_700_000_000_000}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_skip_detail_has_reason_and_first_seen(self):
        self.orch.run_cycle([self.task])
        report = self.orch.run_cycle([self.task])["report"]
        self.assertEqual(report["tasks_skipped_duplicate"], 1)
        detail = report["tasks_skipped_detail"]
        self.assertEqual(len(detail), 1)
        self.assertEqual(detail[0]["reason"], "DUPLICATE_PREVIOUSLY_PROCESSED")
        self.assertIsInstance(detail[0]["first_seen_ms"], int)
        self.assertTrue(report["processed_first_seen_ms_available"])
        self.assertEqual(detail[0]["symbol"], "BTCUSDT")

    def test_legacy_list_processed_file_loads(self):
        path = os.path.join(self.state, "processed-tasks.json")
        os.makedirs(self.state, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(["legacy-tid-1", "legacy-tid-2"], fh)
        orch = orchestrator.Orchestrator(state_dir=self.state, max_retries=1)
        self.assertIn("legacy-tid-1", orch._processed)
        self.assertIsNone(orch._processed["legacy-tid-1"])


class GoodCluster:
    cluster_id = "D"

    def run(self, task):
        return [contract.make_message(
            cluster_id="D", symbol=task["symbol"],
            event_type="TREND_ASSESSMENT",
            event_time_ms=task["ctx"]["data_asof_ms"],
            data_asof_ms=task["ctx"]["data_asof_ms"],
            features={"trend": "BULLISH"},
            evidence={"method": "test"})]


if __name__ == "__main__":
    unittest.main()
