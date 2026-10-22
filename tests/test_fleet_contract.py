# MARI — آزمون آفلاین قرارداد بند ۴ (بدون شبکه، قطعی)
# اجرا: python -m unittest discover -s tests -v

import os
import tempfile
import unittest

from fleet_loader import load_fleet

fleet = load_fleet()
contract = fleet.contract


def sample_event(**overrides):
    base = dict(cluster_id="D", symbol="BTCUSDT", event_type="BOS_BULLISH",
                event_time_ms=1_700_000_000_000, data_asof_ms=1_700_000_360_000,
                features={"direction": "long"}, evidence={"method": "test"},
                validation_status="HYPOTHESIS")
    base.update(overrides)
    return contract.make_message(**base)


class TestContractFields(unittest.TestCase):

    def test_all_required_fields_present(self):
        msg = sample_event()
        for field in contract.REQUIRED_FIELDS:
            self.assertIn(field, msg, f"فیلد اجباری غایب: {field}")
        self.assertEqual(msg["schema_version"], contract.SCHEMA_VERSION)

    def test_event_id_deterministic(self):
        a, b = sample_event(), sample_event()
        self.assertEqual(a["event_id"], b["event_id"])
        c = sample_event(event_key="different")
        self.assertNotEqual(a["event_id"], c["event_id"])

    def test_invalid_cluster_rejected(self):
        with self.assertRaises(ValueError):
            sample_event(cluster_id="Z")

    def test_invalid_status_rejected(self):
        with self.assertRaises(ValueError):
            sample_event(validation_status="PROVEN_PROFITABLE")

    def test_hypothesis_separate_from_evidence(self):
        msg = sample_event(hypothesis={"statement": "فرضیهٔ آزمون‌پذیر"},
                           evidence={"method": "m", "values": [1, 2]})
        self.assertNotIn("فرضیهٔ آزمون‌پذیر", str(msg["evidence"]))
        self.assertEqual(msg["hypothesis"]["statement"], "فرضیهٔ آزمون‌پذیر")

    def test_safety_mode_on_every_message(self):
        msg = sample_event()
        self.assertIn("PAPER_ONLY", msg["safety"]["mode"])
        self.assertIn("NO_LIVE_ORDERS", msg["safety"]["mode"])


class TestEventLedgerDedup(unittest.TestCase):

    def test_append_dedup_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "events.jsonl")
            e1, e2 = sample_event(), sample_event(
                cluster_id="E", event_type="VOLUME_SURGE")
            first = contract.append_events(path, [e1, e2])
            self.assertEqual(first["written"], 2)
            second = contract.append_events(path, [e1, e2])
            self.assertEqual(second["written"], 0)
            self.assertEqual(second["duplicates_skipped"], 2)
            e3 = sample_event(cluster_id="C", event_type="LIQ_POOL_ABOVE")
            third = contract.append_events(path, [e3])
            self.assertEqual(third["written"], 1)
            ids = contract.load_event_ids(path)
            self.assertEqual(len(ids), 3)
            self.assertEqual(contract.filter_new([e1], ids), [])


if __name__ == "__main__":
    unittest.main()
