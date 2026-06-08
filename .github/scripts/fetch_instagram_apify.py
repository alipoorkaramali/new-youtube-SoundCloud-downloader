import os
import json
from apify_client import ApifyClient
from datetime import datetime

def main():
    username = os.environ.get('TARGET_USERNAME')
    post_count_str = os.environ.get('POST_COUNT', '5')
    output_file = os.environ.get('OUTPUT_FILE', 'instagram_posts.json')

    # دریافت دو توکن از Secrets
    token1 = os.environ.get('APIFY_API_TOKEN')
    token2 = os.environ.get('APIFY_API_TOKEN_2')

    if not token1:
        print("❌ APIFY_API_TOKEN is not set")
        exit(1)

    # فایل شمارنده برای انتخاب گردشی
    counter_file = "token_counter.txt"
    counter = 0
    if os.path.exists(counter_file):
        with open(counter_file, 'r') as f:
            try:
                counter = int(f.read().strip())
            except:
                counter = 0

    # انتخاب توکن: اگر توکن دوم وجود داشته باشد، به صورت یک در میان
    if token2:
        if counter % 2 == 0:
            token = token1
            account = 1
        else:
            token = token2
            account = 2
        # افزایش شمارنده برای دفعه بعد
        with open(counter_file, 'w') as f:
            f.write(str(counter + 1))
        print(f"🔄 Using account #{account} (Round Robin)")
    else:
        token = token1
        print("ℹ️ Only one token available")

    # تبدیل تعداد پست به عدد
    try:
        post_count = int(post_count_str)
        if post_count not in [5, 10, 15, 20]:
            post_count = 5
    except:
        post_count = 5

    print(f"🔍 Fetching {post_count} posts from @{username}...")

    try:
        client = ApifyClient(token)
        actor_id = "khadinakbar/instagram-posts-scraper"

        run_input = {
            "instagramUsernames": [username],
            "maxPostsPerTarget": post_count,
            "includeRecentComments": True,
            "proxyConfiguration": {
                "useApifyProxy": True,
                "apifyProxyGroups": ["RESIDENTIAL"]
            }
        }

        run = client.actor(actor_id).call(run_input=run_input)
        print(f"✅ Actor run successful: {run['id']}")

        posts = []
        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            posts.append(item)
            if len(posts) >= post_count:
                break

        result = {
            'target_username': username,
            'requested_posts': post_count,
            'fetched_posts': len(posts),
            'fetched_at': datetime.now().isoformat(),
            'recent_posts': posts
        }

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        print(f"✅ Saved {len(posts)} posts to {output_file}")

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        exit(1)

if __name__ == '__main__':
    main()
