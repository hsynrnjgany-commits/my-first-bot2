# MARI — آزمون آفلاین Orchestrator (خوشهٔ A): ایزوله‌سازی خطا، ضدتکرار، سلامت

import json
import os
import tempfile
import unittest

from fleet_loader import load_fleet

fleet = load_fleet()
orchestrator = fleet.orchestrator
contract = fleet.contract


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


class BadCluster:
    cluster_id = "C"

    def run(self, task):
        raise RuntimeError("شکست عمدی برای آزمون ایزوله‌سازی")


def task_for(symbol, asof_ms=1_700_000_000_000):
    return {"cluster_id": None, "symbol": symbol, "candles": [],
            "ctx": {"interval": "1h", "data_asof_ms": asof_ms}}


class TestOrchestrator(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = os.path.join(self.tmp.name, "fleet")
        self.orch = orchestrator.Orchestrator(
            state_dir=self.state, max_retries=1)

    def tearDown(self):
        self.tmp.cleanup()

    def test_failed_cluster_does_not_block_others(self):
        self.orch.register(GoodCluster())
        self.orch.register(BadCluster())
        tasks = []
        for symbol in ("BTCUSDT", "ETHUSDT"):
            t = task_for(symbol)
            t["cluster_id"] = "D"
            tasks.append(t)
            t2 = task_for(symbol)
            t2["cluster_id"] = "C"
            tasks.append(t2)
        result = self.orch.run_cycle(tasks)
        self.assertEqual(len(result["events"]), 2)  # D برای هر دو نماد زنده ماند
        self.assertEqual(result["report"]["health"]["D"]["status"], "OK")
        self.assertEqual(result["report"]["health"]["C"]["status"], "ERROR")
        self.assertTrue(result["report"]["errors"])

    def test_duplicate_tasks_skipped(self):
        self.orch.register(GoodCluster())
        t = task_for("BTCUSDT")
        t["cluster_id"] = "D"
        first = self.orch.run_cycle([t])
        self.assertEqual(first["report"]["tasks_executed"], 1)
        second = self.orch.run_cycle([dict(t)])
        self.assertEqual(second["report"]["tasks_skipped_duplicate"], 1)
        self.assertEqual(second["report"]["tasks_executed"], 0)

    def test_different_data_asof_not_deduped(self):
        self.orch.register(GoodCluster())
        t1 = task_for("BTCUSDT", asof_ms=1_000)
        t1["cluster_id"] = "D"
        t2 = task_for("BTCUSDT", asof_ms=2_000)
        t2["cluster_id"] = "D"
        result = self.orch.run_cycle([t1, t2])
        self.assertEqual(result["report"]["tasks_executed"], 2)

    def test_register_duplicate_rejected(self):
        self.orch.register(GoodCluster())
        with self.assertRaises(ValueError):
            self.orch.register(GoodCluster())

    def test_state_files_written_and_valid(self):
        self.orch.register(GoodCluster())
        t = task_for("BTCUSDT")
        t["cluster_id"] = "D"
        result = self.orch.run_cycle([t])
        saved = self.orch.save(result["events"], result["report"])
        self.assertEqual(saved["written"], 1)
        events_path = os.path.join(self.state, "events.jsonl")
        with open(events_path, "r", encoding="utf-8") as fh:
            lines = [json.loads(l) for l in fh if l.strip()]
        self.assertEqual(len(lines), 1)
        with open(os.path.join(self.state, "status.json"),
                  "r", encoding="utf-8") as fh:
            status = json.load(fh)
        self.assertIn("cycle_id", status)
        self.assertEqual(status["safety"],
                         "READ_ONLY | PAPER_ONLY | NO_LIVE_ORDERS")

    def test_event_ledger_survives_second_cycle(self):
        self.orch.register(GoodCluster())
        t1 = task_for("BTCUSDT", asof_ms=1_000)
        t1["cluster_id"] = "D"
        r1 = self.orch.run_cycle([t1])
        self.orch.save(r1["events"], r1["report"])
        t2 = task_for("ETHUSDT", asof_ms=2_000)
        t2["cluster_id"] = "D"
        r2 = self.orch.run_cycle([t2])
        self.orch.save(r2["events"], r2["report"])
        events_path = os.path.join(self.state, "events.jsonl")
        ids = contract.load_event_ids(events_path)
        self.assertEqual(len(ids), 2)  # هیچ رویدادی دوباره نوشته نشده


if __name__ == "__main__":
    unittest.main()
