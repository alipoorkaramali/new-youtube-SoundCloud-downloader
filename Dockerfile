FROM python:3.11-slim

WORKDIR /app

# نصب ابزارهای لازم
RUN apt-get update && apt-get install -y \
    git \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# کپی و نصب dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# کپی بقیه فایل‌ها
COPY . .

# مجوز اجرا
RUN chmod -R 755 . 2>/dev/null || true

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# دستور پیش‌فرض (بعدا تغییر می‌دیم)
CMD ["echo", "Railway deployment ready. Configure your start command."]