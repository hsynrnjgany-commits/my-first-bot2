# MARI — خوشهٔ A: Master Orchestrator (بند ۳-A دستور)
# MODE: READ ONLY | PAPER ONLY | NO LIVE ORDERS
# تقسیم مأموریت بین خوشه‌ها، جلوگیری از اجرای تکراری (task_id قطعی)، ایزوله‌سازی
# خطا (شکست یک پهپاد خروجی بقیه را مخدوش نمی‌کند)، تلاش مجدد محدود، ثبت سلامت
# و تجمیع نتایج در دفتر append-only (data/fleet/events.jsonl).

import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone

from .contract import append_events, utc_iso_ms, SOURCE_VERSION

PROCESSED_CAP = 5000
METHOD = "orchestrator_cycle/v1"


def _utc_now_ms() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)


class Orchestrator:
    """ثبت خوشه‌ها + اجرای چرخه + سلامت + دفتر رویداد."""

    def __init__(self, *, max_retries: int = 2, state_dir: str = None,
                 now_ms=None):
        self.clusters = {}
        self.health = {}
        self.max_retries = max_retries
        self.state_dir = state_dir
        self.now_ms = now_ms or _utc_now_ms
        self._processed = {}  # tid → first_seen_ms (اصلاح C-3)؛ None برای legacy
        self._load_processed()

    # ---------- مدیریت دامنهٔ پردازش‌شده (ضد تکرار) ----------

    @staticmethod
    def task_id(cluster_id: str, symbol: str, timeframe: str,
                data_asof_ms: int) -> str:
        raw = f"{cluster_id}|{symbol}|{timeframe}|{data_asof_ms}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def _load_processed(self):
        path = self._processed_path()
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    raw = json.load(fh)
            except (json.JSONDecodeError, OSError):
                self._processed = {}  # دفتر خراب = از نو؛ گزارش می‌شود
                return
            # اصلاح C-3 گزارش MISSION 002: نگاشت tid→first_seen_ms؛ فرمت قدیمی
            # (فهرست رشته) هم خوانده می‌شود با first_seen=None (صادقانه، نه حدس).
            if isinstance(raw, dict):
                self._processed = {str(k): raw[k] for k in raw}
            elif isinstance(raw, list):
                self._processed = {str(t): None for t in raw}
            else:
                self._processed = {}

    def _persist_processed(self):
        path = self._processed_path()
        if not path:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # نگه‌داشتن جدیدترین‌ها بر اساس first_seen (None‌ها قدیمی‌ترین فرض می‌شوند)
        ordered = sorted(self._processed.items(),
                         key=lambda kv: kv[1] if isinstance(kv[1], int) else 0)
        keep = dict(ordered[-PROCESSED_CAP:])
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(keep, fh)

    def _processed_path(self):
        if not self.state_dir:
            return None
        return os.path.join(self.state_dir, "processed-tasks.json")

    # ---------- ثبت و اجرا ----------

    def register(self, cluster):
        """هر خوشه فقط با cluster_id یکتا — ثبت دوباره همان شناسه = ValueError."""
        if cluster.cluster_id in self.clusters:
            raise ValueError(f"خوشهٔ تکراری: {cluster.cluster_id}")
        self.clusters[cluster.cluster_id] = cluster
        self.health.setdefault(cluster.cluster_id, {
            "status": "REGISTERED", "runs_ok": 0, "runs_failed": 0,
            "last_error": None, "retries_used": 0,
        })

    def run_cycle(self, tasks: list) -> dict:
        """tasks: [{"cluster_id","symbol","candles","ctx"}] — خروجی چرخهٔ کامل.
        اصلاح B-1/C-3 گزارش MISSION 002: هر skip با ریشه و شناسه ثبت می‌شود
        تا «تکراری» دیگر علت پنهان (مثل سری منجمد) را پوشش نکند."""
        cycle_id = uuid.uuid4().hex[:12]
        started = self.now_ms()
        events = []
        errors = []
        skipped = 0
        executed = 0
        skipped_details = []

        for task in tasks:
            cluster = self.clusters.get(task["cluster_id"])
            if cluster is None:
                errors.append({"error_type": "UNREGISTERED_CLUSTER",
                               "cluster_id": task["cluster_id"],
                               "symbol": task.get("symbol")})
                continue
            ctx = task.get("ctx", {})
            tid = self.task_id(cluster.cluster_id, task.get("symbol", ""),
                               ctx.get("interval", "1h"),
                               ctx.get("data_asof_ms", 0))
            if tid in self._processed:
                skipped += 1
                skipped_details.append({
                    "task_id": tid, "cluster_id": cluster.cluster_id,
                    "symbol": task.get("symbol"),
                    "data_asof_ms": ctx.get("data_asof_ms"),
                    "first_seen_ms": self._processed.get(tid),
                    "reason": "DUPLICATE_PREVIOUSLY_PROCESSED",
                })
                continue

            attempts = 0
            done = False
            last_err = None
            while attempts <= self.max_retries and not done:
                try:
                    output = cluster.run(task) or []
                    events.extend(output)
                    done = True
                except Exception as err:  # noqa: BLE001 — ایزوله‌سازی خطای پهپاد
                    attempts += 1
                    last_err = f"{type(err).__name__}: {err}"
            h = self.health[cluster.cluster_id]
            if done:
                executed += 1
                h["status"] = "OK"
                h["runs_ok"] += 1
                h["retries_used"] = attempts
                h["last_ok"] = utc_iso_ms(self.now_ms())
                self._processed[tid] = self.now_ms()  # اصلاح C-3: مهر زمانی per-tid
            else:
                h["status"] = "ERROR"
                h["runs_failed"] += 1
                h["last_error"] = last_err
                h["retries_used"] = attempts
                errors.append({"error_type": "CLUSTER_FAILED",
                               "cluster_id": cluster.cluster_id,
                               "symbol": task.get("symbol"),
                               "message": last_err})

        report = {
            "cycle_id": cycle_id,
            "generated_at": utc_iso_ms(self.now_ms()),
            "elapsed_ms": self.now_ms() - started,
            "tasks_total": len(tasks),
            "tasks_executed": executed,
            "tasks_skipped_duplicate": skipped,
            "tasks_skipped_detail": skipped_details[-200:],
            "processed_first_seen_ms_available": any(
                isinstance(v, int) for v in self._processed.values()),
            "events_collected": len(events),
            "errors": errors,
            "health": self.health,
            "source_version": SOURCE_VERSION,
            "method": METHOD,
            "safety": "READ_ONLY | PAPER_ONLY | NO_LIVE_ORDERS",
        }
        self._persist_processed()
        return {"report": report, "events": events}

    # ---------- ماندگاری ----------

    def save(self, events: list, report: dict) -> dict:
        """دفتر append-only + وضعیت چرخه. state_dir خاموش → فقط بازگشت آمار.
        سلامت خوشه‌ها «تجمعی» نگه داشته می‌شود: چرخهٔ تکراری (skip) نباید
        سابقهٔ اجراهای سالم قبلی را پاک کند — واقعیت یعنی تاریخچهٔ واقعی."""
        if not self.state_dir:
            return {"written": 0, "duplicates_skipped": 0}
        os.makedirs(self.state_dir, exist_ok=True)
        res = append_events(os.path.join(self.state_dir, "events.jsonl"), events)
        status_path = os.path.join(self.state_dir, "status.json")
        previous = None
        if os.path.exists(status_path):
            try:
                with open(status_path, "r", encoding="utf-8") as fh:
                    previous = json.load(fh)
            except (json.JSONDecodeError, OSError):
                previous = None
        # تجمیع سلامت: اجراهای قبلی محفوظ می‌مانند
        if isinstance(previous, dict) and isinstance(previous.get("health"), dict):
            for cid, h in previous["health"].items():
                cur = report["health"].get(cid)
                if cur is None:
                    report["health"][cid] = h
                    continue
                cur["runs_ok"] = (h.get("runs_ok") or 0) + (cur.get("runs_ok") or 0)
                cur["runs_failed"] = (h.get("runs_failed") or 0) + (cur.get("runs_failed") or 0)
                if cur.get("status") in (None, "REGISTERED"):
                    cur["status"] = h.get("status", cur.get("status"))
                if cur.get("last_ok") is None:
                    cur["last_ok"] = h.get("last_ok")
            report["cumulative_health"] = True
        with open(status_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        return res
