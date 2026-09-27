# תמונת בסיס של Playwright – כוללת Chromium וכל תלויות המערכת
FROM mcr.microsoft.com/playwright/python:v1.62.0-noble

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install chromium

COPY . .

# תיקיית פלט זמנית לקבצי PDF
RUN mkdir -p /app/output

CMD ["python", "bot.py"]
