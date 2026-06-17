FROM python:3.10-slim

WORKDIR /app

# نصب وابستگی‌های سیستمی (اختیاری)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# کپی فایل‌های مورد نیاز
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# کپی کل پروژه
COPY . .

# نصب yt-dlp (اگر نیاز است که worker مستقیماً دانلود کند، ولی الان از GitHub Actions استفاده می‌کند، لذا اختیاری است)
RUN pip install yt-dlp

# دستور اجرا (worker اصلی)
CMD ["python", ".github/scripts/check_and_trigger.py"]
