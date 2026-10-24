# MARI — چرخهٔ کامل اسکن ناوگان (اجرای دستی: python -m src.fleet.scan)
# MODE: READ ONLY | PAPER ONLY | NO LIVE ORDERS
# کشف نماد (بازاستفاده از Stage 1 برای provenance) → سلامت داده → خوشه‌های
# تخصصی → ارزیاب کاغذی → دفتر append-only. هیچ سفارشی در هیچ مرحله‌ای نیست.
# EXIT CODES (هماهنگ با Stage 1): 0=موفق، 10=شبکه/محیط، 20=قرارداد، 30=داخلی

import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone

from . import sources as src
from .contract import append_events, utc_iso_ms
from .crossmarket import CrossMarketCluster
from .derivatives import DerivativesCluster
from .evaluator import evaluate, evaluation_message, simulate_trades
from .integrity import audit_candles
from .judgment import judge_cycle
from .liquidity import LiquidityCluster
from .onchain import OnchainCluster
from .orchestrator import Orchestrator
from .global_market import GlobalMarketCluster
from .quant import QuantCluster
from .risk import PortfolioRiskCluster
from .sessions import SessionCluster
from .structure import StructureCluster
from .volume import VolumeCluster

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_STATE_DIR = os.path.join(ROOT, "data", "fleet")
INTERVAL_MS = {"15m": 900_000, "30m": 1_800_000, "1h": 3_600_000,
               "2h": 7_200_000, "4h": 14_400_000, "6h": 21_600_000,
               "12h": 43_200_000, "1d": 86_400_000}

EXIT_OK, EXIT_ENV, EXIT_CONTRACT, EXIT_INTERNAL = 0, 10, 20, 30


def load_stage1():
    """موتور Stage 1 را برای provenance بار می‌کند — هرگز بازنویسی/ویرایش نمی‌کند."""
    path = os.path.join(ROOT, "src", "market_discovery.py")
    if not os.path.exists(path):
        return None
    spec = importlib.util.spec_from_file_location("mari_stage1_discovery", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="MARI Fleet Scan (READ ONLY)")
    parser.add_argument("--symbols", type=int, default=8,
                        help="تعداد نماد پربحجم برای این چرخه")
    parser.add_argument("--interval", type=str, default="1h",
                        choices=sorted(INTERVAL_MS.keys()))
    parser.add_argument("--limit", type=int, default=200,
                        help="تعداد کندل هر نماد")
    parser.add_argument("--state-dir", type=str, default=None)
    args = parser.parse_args(argv or sys.argv[1:])

    state_dir = args.state_dir or DEFAULT_STATE_DIR
    interval_ms = INTERVAL_MS[args.interval]

    print("=== MARI FLEET SCAN — READ ONLY | PAPER ONLY | NO LIVE ORDERS ===")
    stage1 = load_stage1()
    print(f"Stage 1 (mari.discovery.report/v1): "
          f"{'بارگذاری شد — provenance زنده' if stage1 else 'غایب (غیرمرگبار)'}")

    # ۱) کشف نماد از تیکر واقعی منبع — هیچ عددی از پیش فرض نمی‌شود
    top = src.fetch_top_symbols(args.symbols)
    if not top["ok"]:
        print("FLEET DISCOVERY FAILED:", top.get("error"))
        print("خطای محیط/شبکه — این اجرا موفق شمرده نمی‌شود.")
        return EXIT_ENV
    symbols = top["symbols"]
    print(f"دنیای کشف‌شده از منبع: {top['universe_count']} نماد | "
          f"منبع: {top['source']} | تا {utc_iso_ms(top['asof_ms'])} | "
          f"انتخاب این چرخه: {len(symbols)}")

    # ۲) ممیزی سلامت داده قبل از هر تحلیلی — فقط کندل پاک به خوشه‌ها می‌رسد
    # زمان واقعی سرور منبع: گارد کندل بسته‌نشده (بند ۵-۴ دستور MISSION 001)
    srv = src.fetch_server_time()
    if srv["ok"]:
        server_now_ms = srv["server_time_ms"]
        server_time_source = srv["source"]
    else:
        server_now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        server_time_source = "local_utc_fallback"
        print(f"  [serverTime] شکست: {srv.get('error')} — fallback ساعت محلی UTC")
    print(f"  [serverTime] منبع: {server_time_source} | now={server_now_ms} — "
          f"کندل بسته‌نشده حذف می‌شود (بند ۵-۴)")
    tasks = []
    klines_meta = {}
    integrity_findings = []
    clean_map = {}
    dropped_open = 0
    for s in symbols:
        k = src.fetch_klines(s, args.interval, args.limit)
        if not k["ok"]:
            klines_meta[s] = {"ok": False, "errors": k["errors"]}
            print(f"  [klines] {s}: ناموفق — {k['errors']}")
            continue
        data_asof = k["candles"][-1]["open_time"]
        clean, findings = audit_candles(
            k["candles"], interval_ms=interval_ms, symbol=s,
            exchange=k["source"], timeframe=args.interval,
            data_asof_ms=data_asof, server_now_ms=server_now_ms)
        integrity_findings.extend(findings)
        dropped_open += sum(1 for f in findings
                            if f["event_type"] == "UNCONFIRMED_CANDLE_DROPPED")
        if not clean:
            klines_meta[s] = {"ok": False,
                              "errors": [{"error_type": "NO_VALID_CANDLES"}]}
            print(f"  [integrity] {s}: هیچ کندل معتبری نماند — کنار گذاشته شد")
            continue
        ctx = {"interval": args.interval, "data_asof_ms": data_asof,
               "exchange": k["source"]}
        for cid in ("D", "E", "C", "F"):
            tasks.append({"cluster_id": cid, "symbol": s, "candles": clean,
                          "ctx": ctx})
        tasks.append({"cluster_id": "G", "symbol": s, "candles": None,
                      "ctx": ctx})
        prices, asof = {}, {}
        for ex in ("toobit", "binance", "bybit", "okx"):
            p = src.fetch_price(s, ex)
            if p["ok"]:
                prices[ex] = p["price"]
                asof[ex] = p["asof_ms"]
        tasks.append({"cluster_id": "H", "symbol": s, "candles": None,
                      "ctx": {**ctx, "prices": prices, "quotes_asof_ms": asof}})
        clean_map[s] = (clean, data_asof, k["source"])
        klines_meta[s] = {"ok": True, "source": k["source"],
                          "candles": len(clean)}
    if not clean_map:
        print("هیچ نمادی دادهٔ معتبر نداشت — خطای محیط/منبع، نه موفقیت.")
        return EXIT_ENV
    # خوشهٔ M: یک وظیفه در هر چرخه با نگاشت کامل کندل‌های پاک (برای جفت‌ها)
    max_asof = max(v[1] for v in clean_map.values())
    candles_map = {s: v[0] for s, v in clean_map.items()}
    tasks.append({
        "cluster_id": "M", "symbol": "PAIRS", "candles": None,
        "ctx": {"interval": args.interval, "data_asof_ms": max_asof,
                "candles_map": candles_map},
    })
    # خوشهٔ I: یک وظیفهٔ سراسری در هر چرخه (منابع آن سراسری‌اند، نه نماد-محور)
    tasks.append({
        "cluster_id": "I", "symbol": "GLOBAL", "candles": None,
        "ctx": {"interval": args.interval, "data_asof_ms": max_asof},
    })
    # خوشهٔ N (WORLD MARKET CORE): کشف جهانی + پهنای بازار — یک وظیفه در چرخه
    tasks.append({
        "cluster_id": "N", "symbol": "GLOBAL", "candles": None,
        "ctx": {"interval": args.interval, "data_asof_ms": max_asof},
    })

    # ۳) اجرای چرخه از طریق Orchestrator (ایزوله، ضدتکرار، با تلاش مجدد محدود)
    orch = Orchestrator(state_dir=state_dir)
    for cluster in (StructureCluster(), VolumeCluster(), LiquidityCluster(),
                    SessionCluster(), DerivativesCluster(),
                    CrossMarketCluster(), QuantCluster(),
                    OnchainCluster(state_dir=state_dir),
                    PortfolioRiskCluster(),
                    GlobalMarketCluster(state_dir=state_dir)):
        orch.register(cluster)
    result = orch.run_cycle(tasks)
    events = list(result["events"]) + integrity_findings
    report = result["report"]

    # ۴) حسابرس مستقل: شبیه‌سازی کاغذی رویدادهای BOS خوشهٔ D
    bos_events = [e for e in result["events"]
                  if e["cluster_id"] == "D"
                  and e["event_type"] in ("BOS_BULLISH", "BOS_BEARISH")]
    all_trades = []
    eval_events = []
    for s, (candles, data_asof, _source) in clean_map.items():
        trades = simulate_trades(
            candles, [e for e in bos_events if e["symbol"] == s], symbol=s)
        all_trades.extend(trades)
        eval_events.append(evaluation_message(
            s, evaluate(trades), data_asof_ms=data_asof))
    global_metrics = evaluate(all_trades)
    eval_events.append(evaluation_message(
        "ALL", global_metrics, data_asof_ms=clean_map[next(iter(clean_map))][1]))
    eval_res = append_events(os.path.join(state_dir, "events.jsonl"),
                             eval_events)

    # ۴-ب) خوشهٔ K در چرخهٔ دوم: ورودی آن خروجی ارزیاب است — پس بعد از ارزیاب
    # از مسیر رسمی Orchestrator اجرا می‌شود (همان ضدتکرار/ایزوله‌سازی/سلامت).
    k_tasks = [{
        "cluster_id": "K", "symbol": "PORTFOLIO", "candles": None,
        "ctx": {"interval": args.interval, "data_asof_ms": max_asof,
                "paper_trades": all_trades, "candles_map": candles_map},
    }]
    k_result = orch.run_cycle(k_tasks)
    k_report = k_result["report"]
    events.extend(k_result["events"])
    report["tasks_total"] += k_report["tasks_total"]
    report["tasks_executed"] += k_report["tasks_executed"]
    report["tasks_skipped_duplicate"] += k_report["tasks_skipped_duplicate"]
    report["portfolio_risk_events"] = len(k_result["events"])
    report["onchain_events"] = sum(1 for e in events if e.get("cluster_id") == "I")
    report["global_core_events"] = sum(1 for e in events
                                       if e.get("cluster_id") == "N")

    # ۴-ج) موتور داوری ۴وضعیتی (بند ۴ دستور C): ردیف‌های دفتر جهانی خوشهٔ N
    # + کندل‌های بستهٔ پاک همین چرخه → چهار وضعیت مستقل؛ نقض استقلال = خرابی بلند
    snap_path = os.path.join(state_dir, "global-assets-snapshot.json")
    reg_rows = []
    if os.path.exists(snap_path):
        try:
            with open(snap_path, encoding="utf-8") as fh:
                reg_rows = (json.load(fh) or {}).get("rows") or []
        except (OSError, ValueError):
            reg_rows = []  # اسنپ‌شات ناسالم — داوری صادقانه روی صفر انجام می‌شود
    else:
        print("  [judgment] اسنپ‌شات دفتر جهانی غایب — داوری این چرخه صفرِ صادقانه است")
    judg = judge_cycle(reg_rows, candles_map, asof_ms=max_asof,
                       state_dir=state_dir)
    events.extend([judg["event"]])
    report["judgment_counts"] = judg["summary"]["counts"]

    # ۵) ماندگاری چرخه + یافته‌های L (dedup توسط قرارداد)
    report["integrity_findings"] = len(integrity_findings)
    report["open_candle_guard"] = {
        "enabled": True, "server_time_source": server_time_source,
        "server_now_ms": server_now_ms,
        "unconfirmed_candles_dropped": dropped_open,
        "rule": "open_time + interval > server_now → کندل حذف (بند ۵-۴)",
    }
    report["evaluator_global"] = global_metrics
    report["klines_meta"] = klines_meta
    report["universe"] = {"count": top["universe_count"],
                          "source": top["source"],
                          "asof": utc_iso_ms(top["asof_ms"])}
    saved = orch.save(events, report)

    # ۶) گزارش فارسی خلاصه
    print("---- چرخهٔ ناوگان ----")
    print(f"cycle_id: {report['cycle_id']} | وظایف: {report['tasks_total']} "
          f"(اجرا {report['tasks_executed']}، تکرار ردشده "
          f"{report['tasks_skipped_duplicate']}) | "
          f"رویداد آن‌چین I: {report.get('onchain_events', 0)} | "
          f"رویداد ریسک K: {report.get('portfolio_risk_events', 0)}")
    for cid, h in report["health"].items():
        print(f"  خوشهٔ {cid}: {h['status']} "
              f"(ok={h['runs_ok']} fail={h['runs_failed']})")
    print(f"  کشف جهانی N: {report.get('global_core_events', 0)} رویداد "
          f"(پوشش و پهنای بازار)")
    jc = report.get("judgment_counts") or {}
    print(f"  داوری ۴وضعیتی: مجموع {jc.get('total', 0)} | رشد قیمت "
          f"{jc.get('price_rising', 0)} | روند تأیید "
          f"{jc.get('uptrend_confirmed', 0)} | فرصت "
          f"{jc.get('opportunity', 0)} | ردشده {jc.get('rejected', 0)}")
    print(f"رویداد: {len(events)} | نوشته‌شدهٔ نو: {saved['written']} | "
          f"تکرار ردشده: {saved['duplicates_skipped']} | "
          f"ارزیاب نو: {eval_res['written']}")
    gm = global_metrics
    print(f"ارزیاب کاغذی (کل): n={gm['n']} → {gm['validation_status']} | "
          f"exit_mix={gm['exit_mix']} | PF={gm['profit_factor']}")
    print("یافتهٔ سلامت داده (خوشهٔ L):", report["integrity_findings"])
    if report["errors"]:
        print("خطاهای ثبت‌شدهٔ چرخه:", len(report["errors"]))
    print("هیچ سفارشی ارسال نشد — READ ONLY | PAPER ONLY.")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
