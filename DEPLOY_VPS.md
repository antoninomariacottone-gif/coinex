# Deploy VPS 24/7

Per un bot CoinEx sempre acceso, la scelta corretta e' un VPS Linux con Docker, non Vercel da solo.

## Perche' non Vercel per il worker

Secondo la documentazione ufficiale Vercel:

- le Functions vengono invocate per richiesta e poi possono scalare a zero
- il knowledge base su WebSocket non propone socket persistenti sulle Functions, ma provider realtime esterni
- i cron job possono partire doppi e richiedono lock/idempotenza

Fonti:

- [Vercel Functions](https://vercel.com/docs/functions)
- [WebSocket support KB](https://vercel.com/kb/guide/do-vercel-serverless-functions-support-websocket-connections)
- [Managing Cron Jobs](https://vercel.com/docs/cron-jobs/manage-cron-jobs)

## Setup consigliato

- Ubuntu 24.04 LTS
- Docker Engine + Docker Compose plugin
- firewall aperto solo su `22`, `80`, `443`
- reverse proxy HTTPS davanti all'app
- API key CoinEx con trading attivo e withdrawal disattivato
- whitelist IP verso l'IP del VPS se CoinEx la supporta sul tuo account

## Installazione

```bash
sudo mkdir -p /opt/coinex-trade-bot
sudo chown $USER:$USER /opt/coinex-trade-bot
cd /opt/coinex-trade-bot
```

Copia qui:

- `Dockerfile`
- `docker-compose.yml`
- `requirements.txt`
- cartella `coinex_trade_bot/`
- `.env`
- cartella `runtime/`

Avvia:

```bash
docker compose up -d --build
```

Controlla:

```bash
docker compose ps
docker compose logs -f
curl http://127.0.0.1:8000/healthz
```

## Avvio automatico al boot

```bash
sudo cp deploy/coinex-trade-bot.service /etc/systemd/system/coinex-trade-bot.service
sudo systemctl daemon-reload
sudo systemctl enable coinex-trade-bot
sudo systemctl start coinex-trade-bot
```

## Hardening minimo

- `.env` con permessi `600`
- dashboard dietro HTTPS
- password lunga per `BOT_DASHBOARD_PASSWORD`
- meglio usare `COINEX_ACCESS_ID_FILE` e `COINEX_SECRET_KEY_FILE`
- tieni `TEST_TRADE_ENABLED=false` salvo test espliciti
