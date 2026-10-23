# اجراکنندهٔ مأموریت ۰۰۱ — گزارش از خروجی‌های واقعی چرخه
# اجرا: python -m src.fleet.mission_run
# هیچ شبکه‌ای؛ فقط خواندن data/fleet و تولید mission001.json + خلاصهٔ فارسی.
# READ ONLY | PAPER ONLY | NO LIVE ORDERS

import json
import os
import sys

from .mission import load_cycle, build_mission_report, save_mission_report

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
STATE_DIR = os.path.join(ROOT, "data", "fleet")


def main() -> int:
    cycle = load_cycle(STATE_DIR)
    doc = build_mission_report(cycle)
    path = save_mission_report(STATE_DIR, doc)
    cov = doc["coverage"]
    print("=== MARI GLOBAL FIRST HUNT — MISSION 001 ===")
    print(f"cycle: {doc['cycle']['cycle_id']} | "
          f"تسک: {doc['cycle']['tasks_executed']}/"
          f"{doc['cycle']['tasks_total']} | "
          f"خوشه‌های OK: {doc['cycle']['clusters_ok']}/"
          f"{doc['cycle']['clusters_total']}")
    print(f"داوری: {cov['judged_total']} دارایی | رشد "
          f"{cov['price_rising']} | افت {cov['price_falling']} | "
          f"روند تأیید {cov['uptrend_confirmed']} | فرصت "
          f"{cov['opportunities']} | رد {cov['rejected']}")
    print(f"نامزد خام: {cov['raw_candidates']} | مستقل ادغام‌شده: "
          f"{cov['merged_independent']} | تأیید: {cov['confirmed']} | "
          f"رد: {cov['rejected_rows']}")
    for r in doc["top"][:10]:
        print(f"  #{r['rank']} {r['symbol']} {r['direction']} "
              f"{r['pattern']} score={r['score']} "
              f"flags={r['risk_flags']} src={','.join(r['sources'])}")
    print("بخش‌ها:", json.dumps(doc["sections"], ensure_ascii=False))
    print(f"ذخیره: {path}")
    print("هیچ سفارشی ارسال نشد — READ ONLY | PAPER ONLY.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
