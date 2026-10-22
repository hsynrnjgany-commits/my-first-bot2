# MARI — آزمون‌های پذیرش خوشهٔ I (آن‌چین و توکن جدید) — کاملاً آفلاین
# پوشش دستور: ورودی معتبر/نامعتبر، دادهٔ ناقص/کهنه/تکراری، قطع منبع،
# ضدتکرار در اجرای مجدد، اتصال واقعی به Orchestrator، ایمنی و نشت کلید.

import json
import os
import sys
import tempfile
import unittest

from fleet_loader import load_fleet

fleet = load_fleet()
onchain = fleet.onchain
sources = fleet.sources
contract = fleet.contract
orchestrator_mod = fleet.orchestrator

ASOF = 1_799_000_000_000  # زمان مبنا (ms) — ثابت برای بازتولیدپذیری


def fake_trending(n=2):
    def _f():
        return {"ok": True, "source": "fake.trending", "asof_ms": 0, "tokens": [
            {"asset_id": f"asset-{i}", "symbol": f"SYM{i}", "name": f"Token {i}",
             "market_cap_rank": 100 + i, "price_usd": 1.0 + i}
            for i in range(n)]}
    return _f


def coin_row(i, **over):
    row = {"asset_id": f"new-{i}", "symbol": f"NEW{i}", "name": f"New {i}",
           "market_cap": 50_000.0, "market_cap_rank": 6000,
           "total_volume": 10_000.0, "price_change_24h_pct": 5.0,
           "last_updated": None}
    row.update(over)
    return row


def fake_newly(coins):
    def _f():
        return {"ok": True, "source": "fake.newly", "coins": coins}
    return _f


def fake_identity():
    def _f(asset_id):
        return {"ok": True, "asset_id": asset_id, "symbol": "X", "name": "X",
                "platforms": {"ethereum": "0xabc", "bsc": None},
                "source": "fake.identity"}
    return _f


def fake_network():
    return lambda: {"ok": True, "fees": {"fastestFee": 3}, "difficulty":
                    {"progressPercent": 50.0}, "source": "fake.mempool",
                    "partial": False}


class SeenLedgerTests(unittest.TestCase):
    def test_first_seen_then_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = onchain.SeenAssetLedger(
                path=os.path.join(tmp, "seen.json"))
            self.assertTrue(ledger.is_new("a1"))
            ledger.mark("a1")
            self.assertFalse(ledger.is_new("a1"))
            # بازسازی از دیسک = حافظه پایدار است (ضدتکرار بین اجراها)
            ledger2 = onchain.SeenAssetLedger(
                path=os.path.join(tmp, "seen.json"))
            self.assertFalse(ledger2.is_new("a1"))

    def test_corrupt_ledger_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "seen.json")
            with open(path, "w") as fh:
                fh.write("{broken")
            ledger = onchain.SeenAssetLedger(path=path)
            self.assertTrue(ledger.is_new("a1"))  # از نو شروع صادقانه
            self.assertTrue(ledger.persist_error)

    def test_ledger_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = onchain.SeenAssetLedger(
                path=os.path.join(tmp, "seen.json"), cap=5)
            for i in range(8):
                ledger.mark(f"id-{i}")
            with open(os.path.join(tmp, "seen.json")) as fh:
                self.assertEqual(len(json.load(fh)), 5)


class ScamFlagsTests(unittest.TestCase):
    def test_flags_thresholds(self):
        info = onchain.scam_flags(coin_row(
            1, total_volume=600_000.0, price_change_24h_pct=150.0))
        self.assertIn("FLAG_VOLUME_RATIO_EXTREME", info["flags"])
        self.assertIn("FLAG_PRICE_EXTREME_24H", info["flags"])
        self.assertIn("FLAG_UNRANKED", info["flags"])
        self.assertEqual(info["data_incomplete"], [])

    def test_missing_data_not_flagged_but_recorded(self):
        info = onchain.scam_flags(coin_row(1, market_cap=None,
                                           total_volume=None,
                                           market_cap_rank=500))
        self.assertEqual(info["flags"], {})  # دادهٔ غایب فلگ ساختگی نمی‌شود
        self.assertIn("market_cap", info["data_incomplete"])

    def test_healthy_coin_no_flags(self):
        info = onchain.scam_flags(coin_row(1, market_cap=1_000_000.0,
                                           market_cap_rank=500,
                                           total_volume=10_000.0,
                                           price_change_24h_pct=2.0))
        self.assertEqual(info["flags"], {})


class AnalyzeTests(unittest.TestCase):
    def base(self, *, trending=None, newly=None, identity=None, network=None,
             ledger=None):
        return onchain.analyze(
            data_asof_ms=ASOF, seen_ledger=ledger,
            trending_fetcher=trending or fake_trending(),
            newly_fetcher=newly or fake_newly([coin_row(1)]),
            identity_fetcher=identity or fake_identity(),
            network_fetcher=network or fake_network())

    def test_valid_run_emits_expected_events(self):
        msgs = self.base()
        types = {m["event_type"] for m in msgs}
        self.assertIn("ONCHAIN_NETWORK_SNAPSHOT", types)
        self.assertIn("TRENDING_TOKEN_ATTENTION", types)
        self.assertIn("NEW_TOKEN_FIRST_SEEN", types)

    def test_first_seen_has_discovery_honesty_uncertainty(self):
        msgs = self.base()
        first = next(m for m in msgs
                     if m["event_type"] == "NEW_TOKEN_FIRST_SEEN")
        joined = " ".join(first["uncertainty"])
        self.assertIn("اولین مشاهده", joined)
        self.assertIn("≠ سیگنال خرید", joined)

    def test_repeat_run_does_not_re_register_new_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = onchain.SeenAssetLedger(
                path=os.path.join(tmp, "seen.json"))
            first = self.base(ledger=ledger)
            second = self.base(ledger=ledger)
            self.assertEqual(
                sum(1 for m in first if m["event_type"] == "NEW_TOKEN_FIRST_SEEN"),
                1)
            self.assertEqual(
                sum(1 for m in second if m["event_type"] == "NEW_TOKEN_FIRST_SEEN"),
                0)  # اجرای مجدد = بدون کشف تکراری (بند ۳-I)

    def test_same_symbol_different_asset_id_both_recorded(self):
        coins = [coin_row(1, asset_id="dup-a", symbol="SAME"),
                 coin_row(2, asset_id="dup-b", symbol="SAME")]
        with tempfile.TemporaryDirectory() as tmp:
            ledger = onchain.SeenAssetLedger(os.path.join(tmp, "s.json"))
            msgs = self.base(newly=fake_newly(coins), ledger=ledger)
        first_seen = [m for m in msgs
                      if m["event_type"] == "NEW_TOKEN_FIRST_SEEN"]
        ids = {m["features"]["asset_id"] for m in first_seen}
        self.assertEqual(ids, {"dup-a", "dup-b"})  # هم‌نام‌ها یکی گرفته نشدند

    def test_scam_flags_are_hypothesis_with_identity(self):
        coins = [coin_row(1, total_volume=999_999.0)]
        msgs = self.base(newly=fake_newly(coins))
        scam = next(m for m in msgs if m["event_type"] == "SCAM_RISK_FLAGS")
        self.assertEqual(scam["validation_status"], "HYPOTHESIS")
        self.assertTrue(scam["hypothesis"]["falsifiable_by"])
        self.assertEqual(scam["features"]["identity"]["networks_contracts"],
                         {"ethereum": "0xabc", "bsc": None})

    def test_stale_source_recorded(self):
        old_iso = "2026-10-01T00:00:00Z"
        msgs = self.base(newly=fake_newly([coin_row(1, last_updated=old_iso)]))
        first = next(m for m in msgs
                     if m["event_type"] == "NEW_TOKEN_FIRST_SEEN")
        self.assertTrue(any("به‌روزنشده" in u for u in first["uncertainty"]))

    def test_all_sources_down_emits_unavailable_only(self):
        def dead():
            return {"ok": False, "error": {"error_type": "NETWORK"}}
        msgs = onchain.analyze(
            data_asof_ms=ASOF, trending_fetcher=dead, newly_fetcher=dead,
            identity_fetcher=dead, network_fetcher=dead,
            seen_ledger=onchain.SeenAssetLedger())
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["event_type"], "ONCHAIN_UNAVAILABLE")
        self.assertEqual(msgs[0]["validation_status"], "UNAVAILABLE")

    def test_newly_down_falls_back_to_trending_first_seen(self):
        """دستهٔ تازه‌افزوده قطع (مثلاً 404/429) → اولین‌مشاهده از فهرست توجه
        با برچسب صریح مبنای مشاهده — کشف جهانی اعلام نمی‌شود."""
        def dead():
            return {"ok": False, "error": {"error_type": "HTTP_ERROR",
                                           "status": 429}}
        with tempfile.TemporaryDirectory() as tmp:
            ledger = onchain.SeenAssetLedger(os.path.join(tmp, "s.json"))
            msgs = onchain.analyze(
                data_asof_ms=ASOF, seen_ledger=ledger,
                trending_fetcher=fake_trending(2), newly_fetcher=dead,
                identity_fetcher=fake_identity(),
                network_fetcher=fake_network())
            first_seen = [m for m in msgs
                          if m["event_type"] == "NEW_TOKEN_FIRST_SEEN"]
            self.assertEqual(len(first_seen), 2)
            self.assertTrue(all(m["features"]["basis"] == "fake.trending"
                                for m in first_seen))
            joined = " ".join(first_seen[0]["uncertainty"])
            self.assertIn("فهرست توجه", joined)
            # اجرای مجدد با همان دفتر → هیچ first-seen تکراری
            msgs2 = onchain.analyze(
                data_asof_ms=ASOF + 1, seen_ledger=ledger,
                trending_fetcher=fake_trending(2), newly_fetcher=dead,
                identity_fetcher=fake_identity(),
                network_fetcher=fake_network())
            self.assertEqual(
                sum(1 for m in msgs2
                    if m["event_type"] == "NEW_TOKEN_FIRST_SEEN"), 0)

    def test_partial_failure_keeps_good_events(self):
        def dead():
            return {"ok": False, "error": {"error_type": "TIMEOUT"}}
        msgs = self.base(network=dead)  # فقط شبکه قطع است
        types = {m["event_type"] for m in msgs}
        self.assertIn("TRENDING_TOKEN_ATTENTION", types)
        self.assertIn("ONCHAIN_PARTIAL", types)
        self.assertNotIn("ONCHAIN_NETWORK_SNAPSHOT", types)

    def test_identity_failure_does_not_break_flag_event(self):
        def bad_identity(asset_id):
            return {"ok": False, "error": {"error_type": "HTTP_ERROR",
                                           "status": 429}}
        coins = [coin_row(1, total_volume=999_999.0)]
        msgs = self.base(newly=fake_newly(coins), identity=bad_identity)
        scam = next(m for m in msgs if m["event_type"] == "SCAM_RISK_FLAGS")
        self.assertIsNone(scam["features"]["identity"]["name"])
        self.assertTrue(any("قرارداد" in u for u in scam["uncertainty"]))

    def test_deterministic_event_ids_for_same_cycle(self):
        a = self.base()
        b = self.base()
        self.assertEqual([m["event_id"] for m in a],
                         [m["event_id"] for m in b])  # بازتولیدپذیری

    def test_no_secrets_in_messages(self):
        blob = json.dumps(self.base(), ensure_ascii=False)
        for needle in ("AKIA", "xoxb", "ghp_", "github_pat", "Bearer ",
                       "api_key", "apikey", "sk-proj", "sk-ant",
                       "BEGIN PRIVATE", "secret"):
            self.assertNotIn(needle, blob)


class OrchestratorConnectionTests(unittest.TestCase):
    """بند ۵ دستور: اثبات اتصال واقعی از مسیر رسمی Orchestrator."""

    def _cycle(self, tmp):
        orch = orchestrator_mod.Orchestrator(state_dir=tmp)
        orch.register(onchain.OnchainCluster(
            state_dir=tmp, trending_fetcher=fake_trending(),
            newly_fetcher=fake_newly([coin_row(1)]),
            identity_fetcher=fake_identity(), network_fetcher=fake_network()))
        # یک خوشهٔ همزاد برای اثبات ایزوله‌سازی خطا
        orch.register(_BoomCluster())
        tasks = [{"cluster_id": "I", "symbol": "GLOBAL", "candles": None,
                  "ctx": {"interval": "1h", "data_asof_ms": ASOF}},
                 {"cluster_id": "BOOM", "symbol": "X", "candles": None,
                  "ctx": {"interval": "1h", "data_asof_ms": ASOF}}]
        return orch, orch.run_cycle(tasks)

    def test_task_via_official_path_and_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            orch, result = self._cycle(tmp)
            types = {e["event_type"] for e in result["events"]}
            self.assertIn("NEW_TOKEN_FIRST_SEEN", types)
            self.assertIn("CLUSTER_FAILED", [e["error_type"]
                                             for e in result["report"]["errors"]])
            self.assertEqual(result["report"]["health"]["I"]["status"], "OK")
            self.assertEqual(result["report"]["health"]["BOOM"]["status"],
                             "ERROR")  # شکست BOOM، خوشهٔ I را نشکست
            # اجرای مجدد همان وظیفه → skip (ضدتکرار در سطح وظیفه)
            again = orch.run_cycle([{"cluster_id": "I", "symbol": "GLOBAL",
                                     "candles": None,
                                     "ctx": {"interval": "1h",
                                             "data_asof_ms": ASOF}}])
            self.assertEqual(again["report"]["tasks_skipped_duplicate"], 1)

    def test_contract_fields_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, result = self._cycle(tmp)
            required = ("message_id", "event_id", "cluster_id", "agent_id",
                        "symbol", "exchange", "market_type", "event_time",
                        "data_asof", "generated_at", "features", "evidence",
                        "uncertainty", "validation_status", "source_version",
                        "schema_version")
            for ev in result["events"]:
                for field in required:
                    self.assertIn(field, ev)


class _BoomCluster:
    cluster_id = "BOOM"

    def run(self, task):
        raise RuntimeError("test failure — خوشهٔ منفجر برای آزمون ایزوله‌سازی")


if __name__ == "__main__":
    unittest.main()
