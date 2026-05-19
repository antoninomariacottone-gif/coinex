# Deploy su RunSite

## 1. Metti il progetto in un repository Git

RunSite deploya da Git o da immagine Docker. Per questo bot, il percorso piu' semplice e' Git + Dockerfile.

Se il progetto non e' ancora in un repo:

```powershell
cd "C:\Users\michi\Documents\Codex\2026-05-08\voglio-creare-questo-bot-l-obiettivo-2"
git init
git add .
git commit -m "Prepare CoinEx bot for RunSite deploy"
```

Poi crea un repository su GitHub e collega il remote:

```powershell
git remote add origin https://github.com/<tuo-user>/<tuo-repo>.git
git branch -M main
git push -u origin main
```

## 2. Crea il servizio su RunSite

Nel dashboard RunSite:

1. `New project`
2. `New service`
3. `Web Service`
4. collega GitHub
5. scegli questo repository
6. branch: `main`

Questo progetto ha gia' un `Dockerfile`, quindi RunSite usera' quello.

## 3. Configurazione deploy

Valori consigliati:

- Build source: `Dockerfile`
- Port: `8080`
- Auto deploy: `on`

Nota: il container legge `PORT`, quindi su RunSite va bene anche il default `8080`.

## 4. Variabili ambiente da copiare

Minime per il bot live:

```env
COINEX_ACCESS_ID=...
COINEX_SECRET_KEY=...
BOT_DASHBOARD_USERNAME=admin
BOT_DASHBOARD_PASSWORD=...
DRY_RUN=false
COINEX_LEVERAGE=20
DEFAULT_BALANCE_PCT=5
ENTRY_ORDER_TYPE=market
COINEX_MARGIN_MODE=isolated
COINEX_TRIGGER_PRICE_TYPE=latest_price
TEST_TRADE_ENABLED=true
TEST_MARKET=BTCUSDT
TEST_HOLD_SECONDS=2
FUTURES_QUOTE_CCY=USDT
```

Se vuoi anche Telegram:

```env
TELEGRAM_ENABLED=true
TELEGRAM_API_ID=...
TELEGRAM_API_HASH=...
TELEGRAM_SESSION_STRING=...
TELEGRAM_SOURCE_CHATS=@StefanoSegnali
TELEGRAM_BALANCE_PCT=...
TELEGRAM_LEVERAGE=...
TELEGRAM_PAPER_SOURCE_CHATS=@nuovo_canale
TELEGRAM_PAPER_BALANCE_PCT=...
TELEGRAM_PAPER_LEVERAGE=...
```

## 5. Primo controllo

Quando il deploy termina:

1. apri `https://<nome-servizio>.runsite.app/healthz`
2. verifica che risponda `{"status":"ok"}`
3. entra nella dashboard
4. usa `Test collegamento`
5. solo dopo prova un micro-trade o un segnale reale

## 6. Nota importante

RunSite free dichiara di tenere calde le app attive e di sospenderle solo dopo 14 giorni senza richieste.
Per un bot di live trading, resta comunque meno collaudato di un VPS tradizionale.
