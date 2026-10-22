# چرخهٔ مستقل خوشهٔ N — WORLD MARKET CORE
# همان کد رسمی GlobalMarketCluster + قرارداد استاندارد append_events با ضدتکرار.
# برای ثبت پهنای جهانی کامل بین چرخه‌های ساعتی scan. هیچ سفارشی؛ فقط رصد.
# اجرا: python -m src.fleet.n_cycle
# READ ONLY | PAPER ONLY | NO LIVE ORDERS

import os
import sys
import time

from .contract import append_events
from .global_market import GlobalMarketCluster

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
STATE_DIR = os.path.join(ROOT, "data", "fleet")


def main() -> int:
    asof = int(time.time() * 1000)
    cluster = GlobalMarketCluster(state_dir=STATE_DIR)
    events = cluster.run({
        "cluster_id": "N", "symbol": "GLOBAL", "candles": None,
        "ctx": {"interval": "1h", "data_asof_ms": asof},
    })
    res = append_events(os.path.join(STATE_DIR, "events.jsonl"), events)
    print(f"N-cycle asof={asof} | رویداد: {len(events)} | "
          f"نوشته‌شدهٔ نو: {res['written']} | تکرار ردشده: "
          f"{res['duplicates_skipped']}")
    return 0 if res["written"] > 0 or res["duplicates_skipped"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
