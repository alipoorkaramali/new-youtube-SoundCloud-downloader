FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# استفاده از Gunicorn با timeout 120 ثانیه
CMD gunicorn --bind 0.0.0.0:$PORT --timeout 120 listener:app
