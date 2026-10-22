# ROLLBACK — روش بازگشت به نسخهٔ قبلی (MARI — WORLD MARKET CORE)

تاریخ آخرین به‌روزرسانی: ۲۰۲۶-۱۰-۲۳ · وضعیت قفل: `READ ONLY | PAPER ONLY | NO LIVE ORDERS`

این سند دقیقاً می‌گوید بعد از هر تغییر، چطور به «آخرین وضعیت سالم» برگردیم — روی کاغذ و با فرمان‌های قابل کپی. هیچ مرحله‌ای به خروجی مدل یا حافظهٔ جلسه وابسته نیست؛ همه‌چیز از فایل‌های روی دیسک بازسازی می‌شود.

---

## ۰) نقشهٔ چهار لایهٔ حفاظت (چه چیزی کجاست)

| لایه | محل | محتوا | در برابر بازسازی سندباکس |
|------|-----|-------|--------------------------|
| L1 | مخزن ناوگان `repos/my-first-bot2` (git، شاخهٔ `main`) | کد کامل ناوگان + اسنپ‌شات دفتر `data/fleet/*` + workflows + همین سند | ✅ زنده می‌ماند (بخشی از سندباکس track شده) |
| L2 | git سندباکس `/home/z/my-project` | داشبورد Next.js + API + کتابخانهٔ تلگرام + آزمون‌ها + اشاره‌گر مخزن | ✅ زنده می‌ماند |
| L3 | `download/mari-fleet-bundle-20261023.bundle` (+ `mari-history-bot2-2026-10-22.bundle`، `mari-clean-backup-2026-10-22.zip`) | تاریخچهٔ کامل مخزن ناوگان در یک فایل مستقل قابل دانلود | ✅ زنده می‌ماند (فایل track شده) |
| L4 | `/tmp/my-project/data/telegram-config.json` (chmod 600) | کپی کانفیگ ربات (توکن + chatIds) | ⚠️ نیمه‌تضمینی — اگر سندباکس و /tmp همزمان بمیرند، توکن باید یک بار دیگر از BotFather توسط کاربر فرستاده شود |

---

## ۱) بازسازی کامل ناوگان از صفر (مرگ کل سندباکس)

```bash
# ۱. ساخت مخزن از باندل مستقل (تاریخچه کامل، بدون نیاز به GitHub)
git clone /home/z/my-project/download/mari-fleet-bundle-20261023.bundle /tmp/restore/my-first-bot2
cd /tmp/restore/my-first-bot2
git checkout main

# ۲. صحت‌سنجی: تعداد رویدادها + وضعیت + آزمون‌ها
python3 -m pytest tests/ -q                 # انتظار: 164 passed (یا بیشتر)
wc -l data/fleet/events.jsonl               # انتظار: صدها رویداد
python3 -c "import json;d=json.load(open('data/fleet/status.json'));print(d)"
cat data/fleet/test-run.json                # انتظار: passed=true

# ۳. کپی به محل استاندارد سندباکس
mkdir -p /home/z/my-project/repos
cp -r /tmp/restore/my-first-bot2 /home/z/my-project/repos/
```

## ۲) بازگشت ناوگان به یک نسخهٔ قبلیِ مشخص (وقتی نسخهٔ جدید خراب است)

```bash
cd /home/z/my-project/repos/my-first-bot2

# فهرست نقاط سالم شناخته‌شده:
git log --oneline -15
#   7925b89 ← موتور داوری ۴وضعیتی + خوشهٔ N (آخرین)
#   6d2699d ← ناوگان v2 (پیش از خوشه‌های I و K) — شاخهٔ پشتیبان: backup/pre-ik-20261023
#   8d08a27 ← ناوگان v3 (I+K)
#   6385695 ← اسنپ‌شات دفتر ۴۹۴ رویدادی

# بازگشت موقت برای آزمایش (بدون از دست دادن تاریخچه):
git checkout 6d2699d                        # یا: git checkout backup/pre-ik-20261023
python3 -m pytest tests/ -q                 # صحت‌سنجی روی نسخهٔ قدیمی

# بازگشت دائمی main به نقطهٔ سالم (تاریخچه حفظ می‌شود — rewrite ممنوع):
git checkout main
git revert --no-commit <hash_کامیت_خراب>..main   # یا فقط: git revert <hash>
python3 -m pytest tests/ -q                 # گیت: هیچ کامیتی بدون پاسِ ۱۶۴+
```

## ۳) بازگشت داشبورد سندباکس به نسخهٔ قبلی

```bash
cd /home/z/my-project
git log --oneline -10                       # نسخه‌های شناخته‌شده:
#   5aba626 ← تب ۱۰ «کشف جهانی» + /api/fleet/global
#   81979ab ← آخرین auto-commit
git revert <hash_کامیت_خراب>                # برگشت تمیز، بدون force
npx tsc --noEmit && npx eslint . && npx next build   # گیت سه‌گانه پیش از انتشار
```

## ۴) بازگردانی ربات تلگرام (@mari_market2026_bot)

```bash
# حالت الف — لایهٔ L4 زنده است (بازسازی خودکار):
cp /tmp/my-project/data/telegram-config.json /home/z/my-project/data/
chmod 600 /home/z/my-project/data/telegram-config.json
# poller حداکثر ۶۰ ثانیه بعد خودش وصل می‌شود؛ بررسی:
curl -s http://localhost:3000/api/telegram/status | head -c 300
# انتظار: "configured":true , "lastOk":true

# حالت ب — هیچ کپی نیست: کاربر توکن تازهٔ BotFather را یک بار در چت می‌فرستد؛
# توکن با chmod 600 در data/telegram-config.json نوشته می‌شود (هرگز وارد git نمی‌شود)
# سپس همان بررسی وضعیت بالا.
```

## ۵) چک‌لیست سلامت بعد از هر بازگشت (هیچ مرحله‌ای بدون مدرک «کامل» نیست)

1. `python3 -m pytest tests/ -q` در مخزن ناوگان → ۱۶۴+ passed
2. `bun scripts/test-paper-stats.ts` (۵۵) + `test-telegram-commands.ts` (۱۹) + `test-snapshot-html.ts` (۱۸) + `test-dna-breadth.ts` + `test-daily-snapshot-wiring.ts` (۱۱) + `test-discovery-daily-wiring.ts` (۳۰) → صفر شکست
3. `npx tsc --noEmit && npx eslint . && npx next build` در سندباکس → صفر خطا
4. `curl -s http://localhost:3000/api/fleet/global | head -c 400` → قیف ۴ مرحله‌ای با اعداد واقعی
5. `curl -s http://localhost:3000/api/telegram/status` → configured=true، lastOk=true
6. بنر قفل در داشبورد و ربات: `READ ONLY | PAPER ONLY | NO LIVE ORDERS` — اگر نبود، انتشار را متوقف کن
7. دفتر رویدادها یکتا: `python3 -c "import json;ids=[json.loads(l)['event_key'] for l in open('data/fleet/events.jsonl') if l.strip()];print(len(ids),len(set(ids)))"` → دو عدد باید برابر باشند

## ۶) قواعد طلایی

- هیچ‌گاه `git push --force` یا rewrite تاریخچه انجام نشود — فقط کامیت‌های جلو رونده.
- توکن ربات هرگز وارد git نمی‌شود (gitignore عمدی است؛ فقط L4 جانبی است).
- قبل از هر تغییر ساختاری، یک باندل تازه بساز: `git bundle create download/mari-fleet-bundle-<تاریخ>.bundle --all` و نسخهٔ قبلی را نگه دار.
- «کد نوشته‌شده» ≠ «آزمون پاس» ≠ «کامیت‌شده» ≠ «منتشرشده» — در گزارش‌ها این چهار مرحله جدا اعلام شوند.
