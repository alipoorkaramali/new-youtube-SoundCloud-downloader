import os
import sys
import json
import csv
import requests
import time
from urllib.parse import urlparse, unquote
from apify_client import ApifyClient

# تنظیم توکن
APIFY_TOKEN = os.environ.get('APIFY_TOKEN') or os.environ.get('APIFY_API_TOKEN', '')
if not APIFY_TOKEN:
    print("❌ APIFY_TOKEN is empty! Make sure the secret is set correctly.")
    sys.exit(1)

CHANNEL = os.environ.get('CHANNEL', 'durov').lstrip('@')
LIMIT = int(os.environ.get('POST_LIMIT', '10'))
START_ID = int(os.environ.get('START_ID', '0'))

ACTOR_ID = "thescrapelab/Apify-Telegram-Scraper"

BASE_DIR = os.path.join("Download", "telegram_downloads", CHANNEL)
MEDIA_DIR = os.path.join(BASE_DIR, "media")
os.makedirs(MEDIA_DIR, exist_ok=True)


def download_file(url, save_path):
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

    # روش پیشنهادی و ساده Apify (start + wait)
    run = client.actor(ACTOR_ID).call(
        run_input=run_input,
        timeout_secs=300   # اینجا timeout کار می‌کند
    )

    if run is None or run.get('status') != 'SUCCEEDED':
        print("❌ Run failed or did not finish in time!")
        print(f"Run status: {run.get('status') if run else 'None'}")
        sys.exit(1)

    dataset_id = run['defaultDatasetId']
    print(f"✅ Run succeeded. Dataset: {dataset_id}")

    dataset = client.dataset(dataset_id)
    items = list(dataset.iterate_items())

    # دانلود رسانه‌ها
    downloaded_count = 0
    for item in items:
        msg_id = item.get('Id', 'unknown')
        media_list = item.get('media', [])
        if not media_list and item.get('MediaUrl'):
            media_list = [{
                'mediaType': item.get('MediaType', 'unknown'),
                'url': item['MediaUrl']
            }]

        for idx, media in enumerate(media_list):
            url = media.get('url')
            if not url:
                continue

            # تشخیص پسوند فایل
            ext = 'unknown'
            parsed = urlparse(url)
            path = unquote(parsed.path)
            if '.' in path.split('/')[-1]:
                ext = path.split('/')[-1].split('.')[-1].split('?')[0][:10]
            else:
                mtype = media.get('mediaType', '').lower()
                if 'photo' in mtype or 'image' in mtype:
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

            print(f"⬇️ Downloading: {filename} from {url[:80]}...")
            if download_file(url, filepath):
                print(f"   ✅ Done")
                downloaded_count += 1
            else:
                print(f"   ❌ Failed")

    # ذخیره JSON و CSV
    with open(os.path.join(BASE_DIR, 'posts.json'), 'w', encoding='utf-8') as f:
        json.dump(items, f, indent=2, ensure_ascii=False)

    if items:
        with open(os.path.join(BASE_DIR, 'posts.csv'), 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=items[0].keys())
            writer.writeheader()
            writer.writerows(items)

    print(f"\n🎉 Finished! {len(items)} posts | {downloaded_count} media files saved in '{BASE_DIR}'")
    if items:
        last = items[-1]
        print(f"🔗 Latest: ID {last.get('Id')} | Date: {last.get('Date')} | URL: {last.get('Url')}")


if __name__ == "__main__":
    main()
