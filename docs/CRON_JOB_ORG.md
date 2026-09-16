# اتصال به cron-job.org

## روش پیشنهادی: Import from cURL

1. یک **GitHub PAT** بساز (دسترسی `repo` یا Actions + Contents همین مخزن).
2. برو به https://console.cron-job.org/dashboard → **Create cronjob**.
3. گزینه **Import from cURL** را بزن.
4. این دستور را paste کن (فقط `YOUR_GITHUB_TOKEN` را عوض کن):

```bash
curl -X POST "https://api.github.com/repos/alipoorkaramali/new-youtube-SoundCloud-downloader/dispatches" \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer YOUR_GITHUB_TOKEN" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  -H "Content-Type: application/json" \
  -d '{"event_type":"telegram-news-hourly","client_payload":{"source":"cron-job.org"}}'
```

همان فایل آماده: [`docs/cron-job-org-import.curl`](./cron-job-org-import.curl)

5. بعد از import:
   - **Title:** مثلاً `Telegram news hourly`
   - **Schedule:** هر ۱ ساعت (`0 * * * *`)
   - **Enable** کن و یک‌بار **Run now** بزن

اگر پاسخ API برابر **204** بود، تریگر موفق است و باید run در تب Actions مخزن دیده شود.

---

## انواع event

| event_type | معنی |
|------------|------|
| `telegram-news-hourly` | اجرای ساعتی همه کانال‌های `channel_list` |
| `telegram-news-scrape` | همان رفتار |

هر دو: حالت متنی (بدون مدیا)، ذخیره در repository، ادامه از `last_post_id`.

---

## افزودن کانال جدید

### فقط اضافه به لیست (بدون اسکرپ)

Actions → **Scrape Telegram & Save Archive** → Run workflow  
فیلد **`add_only_channels`:** مثلاً `manoto,voa,dw_persian`

### اسکرپ یک کانال جدید

فیلد **`channel`** را پر کن؛ اگر در لیست نبود خودکار اضافه می‌شود.

### ویرایش مستقیم

`State/telegram_news_state.json` → `channel_list`

---

## نکات امنیتی

- توکن را فقط در cron-job.org بگذار؛ داخل git commit نکن.
- اگر توکن لو رفت، فوراً revoke کن.
- `schedule` داخلی گیت‌هاب فقط روی default branch کار می‌کند؛ cron-job.org برای تریگر پایدارتر است.
