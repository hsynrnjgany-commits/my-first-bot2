# خوشهٔ N — global-market-core (فاز ۳)
# کشف جهانی + دفتر دارایی + پهنای بازار واقعی. هر چرخه:
#   ۱ فراخوان /global + صف چرخشی صفحه‌های /coins/markets + شبکه‌های GT + استخرهای برتر
# سقف سخت صف؛ مدیریت 429؛ خروجی صادقانه؛ هیچ سفارشی.
# READ ONLY | PAPER ONLY | NO LIVE ORDERS

import os
import time

from .contract import make_message
from . import global_sources as gs
from . import asset_registry as ar

MARKETS_PAGES_PER_CYCLE = 2   # ۲×۲۵۰ = ۵۰۰ دارایی در هر چرخه (صف چرخشی)
GT_PAGE = 1


class GlobalMarketCluster:
    """پوستهٔ استاندارد خوشهٔ N برای Orchestrator — فقط رصد و ثبت."""
    cluster_id = "N"

    def __init__(self, state_dir: str = None, opener=None):
        self.state_dir = state_dir
        self.opener = opener  # تزریقی برای آزمون آفلاین

    # ---- دریافت با احترام به 429 (بند ۶: تلاش مجدد کنترل‌شده) ----
    def _fetch(self, fn, *a, **kw) -> dict:
        r = fn(*a, opener=self.opener, **kw)
        err = (r.get("error") or {})
        if not r.get("ok") and err.get("rate_limited"):
            wait = min(gs.RETRY_AFTER_CAP_SEC,
                       float(err.get("retry_after_sec") or 1.0))
            time.sleep(wait)
            r = fn(*a, opener=self.opener, **kw)  # یک تلاش مجدد کنترل‌شده
        return r

    def _cg(self, fn, *a, **kw) -> dict:
        """فراخوان CoinGecko با فاصله‌گذاری احترام به نرخ رایگان."""
        time.sleep(gs.COINGECKO_SPACING_SEC)
        return self._fetch(fn, *a, **kw)

    def run(self, task: dict) -> list:
        ctx = task.get("ctx") or {}
        asof = int(ctx.get("data_asof_ms") or time.time() * 1000)
        events, sources = [], {}
        st = (ar.load_page_queue(self.state_dir)
              if self.state_dir else {"next_page": 1, "last_success_ms": {}})

        # ۰) دنیای کامل CEX واقعی Toobit (یک فراخوان دسته‌ای، بدون محدودیت سخت)
        tb = self._fetch(gs.fetch_toobit_ticker24)
        sources["toobit_ticker24"] = {
            "ok": tb["ok"], "latency_ms": tb.get("latency_ms"),
            "error": tb.get("error"),
            "asof_ms": asof if tb["ok"] else None,
        }
        cex_rows = []
        if tb["ok"]:
            cex_rows = ar.normalize_toobit_rows(
                tb["data"]["rows"], fetched_at_ms=asof)
            st["last_success_ms"]["toobit_ticker24"] = asof

        # ۱) تجمیع جهانی CoinGecko (فاصله‌گذاری‌شده)
        g = self._cg(gs.fetch_global_market)
        sources["coingecko_global"] = {
            "ok": g["ok"], "latency_ms": g.get("latency_ms"),
            "error": g.get("error"),
            "asof_ms": asof if g["ok"] else None,
        }

        # ۲) صف چرخشی صفحه‌های /coins/markets (سقف سخت)
        pages, rows, page_ok = [], [], 0
        p = int(st.get("next_page", 1))
        for _ in range(MARKETS_PAGES_PER_CYCLE):
            r = self._cg(gs.fetch_coins_markets, page=p)
            pages.append({"page": p, "ok": r["ok"],
                          "error": r.get("error"),
                          "rows": r.get("data", {}).get("row_count", 0)
                                  if r["ok"] else 0})
            if r["ok"]:
                page_ok += 1
                st["last_success_ms"][f"markets_p{p}"] = asof
                rows.extend(ar.normalize_coingecko_rows(
                    r["data"]["rows"], fetched_at_ms=asof, page=p))
            p = 1 if p >= gs.MARKETS_MAX_PAGES else p + 1
        if page_ok:
            st["next_page"] = p

        # ۳) شبکه‌های DEX + استخرهای برتر دو شبکهٔ اولویت‌دار
        nets = self._fetch(gs.fetch_gt_networks)
        sources["geckoterminal_networks"] = {
            "ok": nets["ok"], "latency_ms": nets.get("latency_ms"),
            "error": nets.get("error"),
            "asof_ms": asof if nets["ok"] else None,
        }
        pools_rows = []
        for net in gs.GT_POOL_NETWORKS:
            rp = self._fetch(gs.fetch_gt_pools, network=net, page=GT_PAGE)
            sources[f"geckoterminal_pools_{net}"] = {
                "ok": rp["ok"], "latency_ms": rp.get("latency_ms"),
                "error": rp.get("error"),
                "asof_ms": asof if rp["ok"] else None,
            }
            if rp["ok"]:
                st["last_success_ms"][f"gt_pools_{net}"] = asof
                pools_rows.extend(ar.normalize_gt_pools(
                    rp["data"]["pools"], network=net, fetched_at_ms=asof))

        all_rows = cex_rows + rows + pools_rows

        # ۴) ماندگاری (اسنپ‌شات کامل + دفتر خلاصه + وضعیت صف)
        cov = ar.coverage(all_rows)
        breadth_docs = {w: ar.breadth(all_rows, w)
                        for w in ("1h", "24h", "7d")}
        movers = {w: ar.top_movers(all_rows, w, k=10)
                  for w in ("1h", "24h", "7d")}
        gdata = g.get("data") or {}
        summary = {
            "schema": ar.REGISTRY_VERSION,
            "cycle_asof_ms": asof,
            "sources": sources,
            "coverage": cov,
            "breadth": breadth_docs,
            "global": gdata if g["ok"] else None,
            "pages": pages,
        }
        if self.state_dir:
            try:
                ar.save_snapshot(self.state_dir, {
                    "schema": ar.REGISTRY_VERSION, "asof_ms": asof,
                    "coverage": cov, "rows": all_rows})
                ar.append_registry_line(self.state_dir, summary)
                ar.save_page_queue(self.state_dir, st)
            except OSError:
                pass  # دیسک ناسالم — رویداد همچنان صادقانه ثبت می‌شود

        # ۵) رویدادهای قراردادی — OBSERVED با منبع و زمان واقعی
        ev_key = f"{asof}"
        events.append(make_message(
            cluster_id="N", symbol="GLOBAL",
            event_type="GLOBAL_DISCOVERY",
            event_time_ms=asof, data_asof_ms=asof,
            market_type="aggregated", exchange="multi",
            features={
                "coverage": cov,
                "global": gdata if g["ok"] else None,
                "sources": sources,
                "pages": pages,
                "page_queue_next": st.get("next_page"),
                "markets_max_pages": gs.MARKETS_MAX_PAGES,
            },
            uncertainty=[
                "پوشش جاری = صف چرخشی سقف‌دار، نه رصد لحظه‌ای",
                "دارایی‌های خارج از صف این چرخه رصد نشده‌اند",
            ] + ([] if all(s.get("ok") for s in sources.values())
                 else ["یک یا چند منبع این چرخه پاسخ نداد — شمارش‌ها فقط "
                       "از منابع سالم است"]),
            evidence={"urls": [s.get("url") for s in
                               [g, nets] if s.get("url")]},
            task_id=task.get("task_id"), event_key=ev_key))

        events.append(make_message(
            cluster_id="N", symbol="BREADTH",
            event_type="BREADTH_WINDOW",
            event_time_ms=asof, data_asof_ms=asof,
            market_type="aggregated", exchange="multi",
            features={"breadth": breadth_docs, "top_movers": movers,
                      "note": "استیبل‌کوین‌ها و قیمت‌های کهنه از شمارش جهت "
                              "حذف برچسب می‌شوند، نه از فهرست دارایی‌ها"},
            uncertainty=["تغییرات ۱س/۷ر فقط برای ردیف‌های دارای فیلد منبع است"],
            evidence={"primary_source": "coingecko/coins-markets + "
                                        "geckoterminal/pools"},
            task_id=task.get("task_id"), event_key=ev_key))
        return events
