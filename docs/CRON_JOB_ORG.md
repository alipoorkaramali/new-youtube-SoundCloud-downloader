# اتصال به cron-job.org

این ورک‌فلو علاوه بر `schedule` داخلی گیت‌هاب، با **`repository_dispatch`** از بیرون هم قابل تریگر است — مناسب برای [cron-job.org](https://console.cron-job.org/dashboard).

## چرا cron-job.org؟

- `schedule` گیت‌هاب فقط روی **default branch** اجرا می‌شود و گاهی تأخیر دارد.
- با cron-job.org می‌توانی روی برنچ `test` (یا هر برنچ) و با زمان‌بندی دقیق‌تر تریگر بزنی.

## پیش‌نیاز

1. یک **Personal Access Token (classic)** یا fine-grained با دسترسی:
   - `repo` (یا حداقل Contents + Actions برای این مخزن)
2. توکن را فقط در cron-job.org ذخیره کن؛ داخل مخزن commit نکن.

## ساخت Job در cron-job.org

1. برو به: https://console.cron-job.org/dashboard  
2. **Create cronjob**
3. تنظیمات پیشنهادی:

| فیلد | مقدار |
|------|--------|
| **Title** | `Telegram news hourly` |
| **URL** | `https://api.github.com/repos/alipoorkaramali/new-youtube-SoundCloud-downloader/dispatches` |
| **Schedule** | هر ۱ ساعت (مثلاً `0 * * * *`) |
| **Request method** | `POST` |
| **Request timeout** | 30s+ |

4. **Request headers:**

```
Accept: application/vnd.github+json
Authorization: Bearer YOUR_GITHUB_TOKEN
Content-Type: application/json
X-GitHub-Api-Version: 2022-11-28
```

5. **Request body:**

```json
{
  "event_type": "telegram-news-hourly",
  "client_payload": {
    "source": "cron-job.org"
  }
}
```

6. ذخیره و یک‌بار **Run now** برای تست.

### انواع event پشتیبانی‌شده

- `telegram-news-hourly`
- `telegram-news-scrape`

هر دو مثل اجرای ساعتی عمل می‌کنند: همه کانال‌های `channel_list`، حالت متنی، ذخیره در repository.

## افزودن کانال جدید

### روش ۱ — فقط اضافه به لیست (بدون اسکرپ)

Actions → **Scrape Telegram & Save Archive** → Run workflow:

- فیلد **`add_only_channels`**: مثلاً `manoto,voa,dw_persian`
- بقیه را رها کن

### روش ۲ — اسکرپ دستی یک کانال جدید

- **`channel`**: نام کانال (بدون `@`)
- اگر در لیست نبود **خودکار** به `State/telegram_news_state.json` اضافه می‌شود و اسکرپ شروع می‌شود.

### روش ۳ — ویرایش مستقیم state

فایل: `State/telegram_news_state.json`

```json
{
  "channel_list": ["IranintlTv", "bbcpersian", "CHANNEL_NEW"],
  "channels": {
    "CHANNEL_NEW": { "last_post_id": "" }
  }
}
```

## تست سریع با curl

```bash
curl -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer YOUR_GITHUB_TOKEN" \
  -H "Content-Type: application/json" \
  https://api.github.com/repos/alipoorkaramali/new-youtube-SoundCloud-downloader/dispatches \
  -d '{"event_type":"telegram-news-hourly","client_payload":{"source":"manual-test"}}'
```

اگر پاسخ `204 No Content` بود، تریگر موفق بوده است.
