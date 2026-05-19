FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY coinex_trade_bot ./coinex_trade_bot
COPY README.md .

RUN mkdir -p /app/runtime

EXPOSE 8080

CMD ["/bin/sh", "-c", "uvicorn coinex_trade_bot.web_app:app --host 0.0.0.0 --port ${PORT:-8080}"]
