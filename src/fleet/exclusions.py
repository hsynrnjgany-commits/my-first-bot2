# MARI — exclusions: فهرست استثنای نمادهای نامعتبر منبع — تصمیم ثبت‌شدهٔ مالک
# MODE: READ ONLY | PAPER ONLY | NO LIVE ORDERS
#
# خاستگاه: تصمیم رییس (2026-10-25) — حذف GRAMUSDT از چرخه‌های آینده.
# شواهد: Toobit برای GRAMUSDT در واکشی آرشیو M3 و بازپخش ag2 همیشه
# HTTP400 «Invalid Symbols» داد (worklog Task 87)؛ نماد در منبع زندهٔ
# توبیت معتبر نیست. هیچ بازنویسیِ دادهٔ تاریخی انجام نمی‌شود — رکوردهای
# گذشته سند می‌مانند؛ فقط انتخاب آینده فیلتر می‌شود.
# این ماژول خالص و قطعی است: بدون شبکه، بدون ساعت، بدون نوشتن فایل.

EXCLUSIONS_METHOD = "exclusions/denylist_v1"

# شواهد لایت‌برات‌شده — هر ورودی باید دلیل و منبع دلیل داشته باشد
UNAVAILABLE_SYMBOLS = {
    "GRAMUSDT": {
        "reason": "EXCHANGE_INVALID_SYMBOL",
        "evidence": "toobit HTTP400 Invalid Symbols — M3 archive fetch + ag2 replay (Task 87)",
        "decision": "OWNER_ORDER_REMOVE_2026-10-25",
    },
}


def filter_symbols(symbols: list, *, source: str = "toobit") -> dict:
    """فیلتر نمادهای کشف‌شده بر فهرست استثنا — خالص، قطعی، حافظهٔ ترتیب.
    خروجی: {"kept": [...], "excluded": [...], "n_in", "n_kept"} — فقط گزارش."""
    kept, excluded = [], []
    for s in symbols:
        info = UNAVAILABLE_SYMBOLS.get(s)
        if info is None:
            kept.append(s)
        else:
            excluded.append(dict(symbol=s, source=source,
                                 method=EXCLUSIONS_METHOD, **info))
    return {"method": EXCLUSIONS_METHOD, "n_in": len(symbols),
            "n_kept": len(kept), "kept": kept, "excluded": excluded}
