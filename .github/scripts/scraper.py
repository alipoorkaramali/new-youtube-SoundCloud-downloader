import os
import sys
import json
import csv
import requests
import time
from urllib.parse import urlparse, unquote
from apify_client import ApifyClient

# دریافت از متغیرهای محیطی (Secrets + ورودی‌های workflow)
APIFY_TOKEN = os.environ['APIFY_TOKEN']
CHANNEL = os.environ.get('CHANNEL', 'durov').lstrip('@')
LIMIT = int(os.environ.get('POST_LIMIT', '10'))
START_ID = int(os.environ.get('START_ID', '0'))

ACTOR_ID = "thescrapelab/Apify-Telegram-Scraper"

# مسیر ذخیره‌سازی مطابق خواسته‌ی شما
BASE_DIR = os.path.join("Download", "telegram_downloads", CHANNEL)
MEDIA_DIR = os.path.join(BASE_DIR, "media")
os.makedirs(MEDIA_DIR, exist_ok=True)


def download_file(url, save_path):
    """دانلود فایل با ۳ بار تلاش در صورت خطا"""
    for attempt in range(3):
        try:
            r = requests.get(url, stream=True, timeout=30)
            if r.status_code == 200:
                with open(save_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
                return True
        except Exception as e:
            print(f"⚠️ Download error (attempt {attempt+1}): {e}")
            time.sleep(2)
    return False


def main():
    client = ApifyClient(APIFY_TOKEN)

    run_input = {
        "channels": [{
            "channelName": CHANNEL,
            "startId": START_ID,
            "limit": LIMIT
        }]
    }

    print(f"🚀 Scraping @{CHANNEL} | Limit: {LIMIT} | Start ID: {START_ID}")
    run = client.actor(ACTOR_ID).call(run_input=run_input, timeout_secs=300)

    if not run or run.get('status') != 'SUCCEEDED':
        print("❌ Run failed!")
        sys.exit(1)

    dataset_id = run['defaultDatasetId']
    print(f"✅ Run succeeded. Dataset: {dataset_id}")

    # دریافت همهٔ آیتم‌ها (پست‌ها)
    dataset = client.dataset(dataset_id)
    items = list(dataset.iterate_items())

    # دانلود رسانه‌ها (عکس، ویدئو و ...)
    for item in items:
        msg_id = item.get('Id', 'unknown')

        # خروجی Actor جدید: فیلد 'media' یک لیست است
        media_list = item.get('media', [])
        if not media_list:
            # سازگاری با خروجی‌های قدیمی‌تر
            if item.get('MediaUrl'):
                media_list = [{
                    'mediaType': item.get('MediaType', 'unknown'),
                    'url': item['MediaUrl']
                }]
            elif item.get('MediaType') and item.get('MediaType') != 'text':
                # نوع رسانه هست اما لینک دانلود در دسترس نیست
                pass

        for idx, media in enumerate(media_list):
            url = media.get('url')
            if not url:
                continue

            # تعیین پسوند فایل
            ext = 'unknown'
            parsed = urlparse(url)
            path = unquote(parsed.path)
            if '.' in path.split('/')[-1]:
                ext = path.split('/')[-1].split('.')[-1].split('?')[0][:10]
            else:
                mtype = media.get('mediaType', '')
                if 'photo' in mtype:
                    ext = 'jpg'
                elif 'video' in mtype:
                    ext = 'mp4'
                elif 'audio' in mtype:
                    ext = 'mp3'
                else:
                    ext = 'file'

            filename = f"post_{msg_id}_{idx}.{ext}"
            filepath = os.path.join(MEDIA_DIR, filename)

            if os.path.exists(filepath):
                print(f"📁 Skipped existing: {filename}")
                continue

            print(f"⬇️ Downloading: {filename}")
            if download_file(url, filepath):
                print(f"   ✅ Done")
            else:
                print(f"   ❌ Failed to download {url}")

    # ذخیره‌ی فایل‌های JSON و CSV
    posts_json_path = os.path.join(BASE_DIR, 'posts.json')
    posts_csv_path = os.path.join(BASE_DIR, 'posts.csv')

    with open(posts_json_path, 'w', encoding='utf-8') as f:
        json.dump(items, f, indent=2, ensure_ascii=False)

    if items:
        with open(posts_csv_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=items[0].keys())
            writer.writeheader()
            writer.writerows(items)

    print(f"\n📊 {len(items)} posts, media saved in '{BASE_DIR}'")
    if items:
        last = items[-1]
        print(f"🔗 Latest ID: {last.get('Id')} | Date: {last.get('Date')} | URL: {last.get('Url')}")

if __name__ == "__main__":
    main()
