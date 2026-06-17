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

# اجرای Webhook Receiver (مسیر درست)
CMD ["python", ".github/scripts/listener.py"]
