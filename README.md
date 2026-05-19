# CoinEx Trade Bot

Bot Python per CoinEx Futures che:

- riceve un segnale testuale in stile Telegram
- imposta leva e margine isolato
- apre una posizione `LONG` o `SHORT`
- mantiene una sola posizione per ogni trade, con take profit multipli sulla stessa posizione
- crea fino a 4 take profit parziali con gli endpoint di posizione CoinEx
- imposta lo stop loss iniziale
- sposta lo stop a break-even dopo il primo take profit
- gira come servizio web 24/7 con dashboard protetta
- offre un micro-trade di test per verificare il collegamento reale con CoinEx
- supporta piu' trade attivi contemporaneamente su mercati/lati diversi
- puo' ascoltare automaticamente un canale Telegram e tradare solo i post-segnale
- puo' ascoltare canali Telegram separati in modalita' `live` e `paper`

## Perche' questo approccio

CoinEx Futures ha una gestione TP/SL particolare:

- i take profit e stop loss di posizione hanno endpoint dedicati
- da `18-Dec-2025` CoinEx supporta ordini TP/SL multipli sulla stessa posizione fino a 20
- esistono endpoint distinti per `set`, `modify` e `cancel` dei TP/SL di posizione

Per questo il bot non usa una scorciatoia con ordini generici OCO, ma la logica nativa dei `position TP/SL`.

## Sicurezza

- `DRY_RUN=true` di default: il bot calcola tutto ma non invia ordini
- usa lo `StateStore` locale in `runtime/active_trade.json`
- sposta lo stop a break-even di default solo dopo conferma del primo TP (`BREAK_EVEN_MODE=tp1_fill`)
- supporta segreti anche via file con `COINEX_ACCESS_ID_FILE` e `COINEX_SECRET_KEY_FILE`
- la dashboard usa `HTTP Basic Auth`

Prima di usare soldi reali:

1. prova con size minima
2. controlla che `VIRTUALUSDT` o il mercato scelto abbia `API trading` attivo
3. verifica i permessi API CoinEx: trading abilitato, withdrawal disabilitato
4. lascia whitelist IP attiva se possibile

## Installazione locale

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Compila `.env` con:

- `COINEX_ACCESS_ID`
- `COINEX_SECRET_KEY`
- `MARGIN_USDT` oppure `POSITION_SIZE_BASE`
- oppure `DEFAULT_BALANCE_PCT` per usare una percentuale del saldo futures disponibile
- `BOT_DASHBOARD_PASSWORD`

## Avvio come servizio web

```powershell
uvicorn coinex_trade_bot.web_app:app --host 0.0.0.0 --port 8000
```

Poi apri:

```text
http://localhost:8000
```

La dashboard permette di:

- incollare un segnale e avviare il trade
- scegliere la leva del singolo trade
- scegliere la percentuale di saldo futures da usare
- vedere l'elenco dei trade attivi
- chiudere un trade con un pulsante
- fare un `test collegamento` senza aprire posizioni
- fare un `micro-trade test` che apre e chiude subito una posizione reale

## Deploy 24/7 con Docker

Per un VPS Linux:

```bash
docker compose up -d --build
```

Scelte consigliate:

- VPS con IP fisso e firewall
- reverse proxy HTTPS davanti al container
- `.env` fuori dal repo, permessi stretti
- `runtime/` persistente per riprendere il trade dopo riavvio

## Deploy 24/7 con Railway

Railway e' adatto a questo bot perche':

- supporta servizi persistenti sempre attivi
- accetta deploy da directory locale con `railway up`
- usa `railway.toml` per healthcheck e restart policy

Passi:

```powershell
railway login
railway init
railway up
```

Dopo il primo deploy:

- imposta le variabili ambiente dalla dashboard Railway
- verifica che il servizio risponda su `/healthz`
- lascia `DRY_RUN=true` finche' non completi i test reali

## Collegamento Telegram

Per leggere automaticamente i post di un canale Telegram e tradare solo i segnali:

1. crea `TELEGRAM_API_ID` e `TELEGRAM_API_HASH` su [my.telegram.org](https://my.telegram.org)
2. genera una sessione con:

```powershell
$env:TELEGRAM_API_ID="..."
$env:TELEGRAM_API_HASH="..."
py scripts\generate_telegram_session.py
```

3. salva su Railway:

```env
TELEGRAM_ENABLED=true
TELEGRAM_API_ID=...
TELEGRAM_API_HASH=...
TELEGRAM_SESSION_STRING=...
TELEGRAM_SOURCE_CHATS=@nome_canale_1,@nome_canale_2
```

Opzionali:

```env
TELEGRAM_BALANCE_PCT=7
TELEGRAM_LEVERAGE=20
```

Il listener Telegram:

- ignora i messaggi generici del canale
- accetta solo post con struttura da segnale completa
- passa il segnale al motore del bot
- rispetta il vincolo di un trade attivo per `market + side`

Per tenere un secondo canale solo in prova, senza ordini reali:

```env
TELEGRAM_PAPER_SOURCE_CHATS=@nuovo_canale
TELEGRAM_PAPER_BALANCE_PCT=5
TELEGRAM_PAPER_LEVERAGE=10
```

I trade `paper`:

- non inviano ordini a CoinEx
- usano comunque i prezzi live via WebSocket per simulare entry, TP e stop
- spostano lo stop a break-even dopo il primo target
- mostrano nel pannello `realized_pnl_quote` e `realized_r_multiple`

## Uso segnale

Metti il segnale in `signal.txt`, per esempio:

```text
🔴 TON – SHORT
➡️ Punto di ingresso: 1.8002
Obiettivi:
1.7816
1.7513
1.7205
1.6086
❌ Stop Loss: 1.8909
✅ Dopo il primo take profit, spostiamo lo stop loss sul punto di ingresso.
```

Esegui:

```powershell
python -m coinex_trade_bot.main --signal-file signal.txt
```

Oppure:

```powershell
python -m coinex_trade_bot.main --signal-text "🔴 TON - SHORT
Punto di ingresso: 1.8002
Obiettivi:
1.7816
1.7513
1.7205
1.6086
Stop Loss: 1.8909"
```

## Modalita' test

`/api/test-connection` verifica:

- autenticazione firmata
- lettura dati futures
- compatibilita' del mercato test

`/api/test-trade` invece:

1. imposta la leva
2. apre una micro-posizione `market`
3. aspetta `TEST_HOLD_SECONDS`
4. la chiude via endpoint ufficiale `POST /futures/close-position`

Per abilitarlo:

```env
TEST_TRADE_ENABLED=true
TEST_MARKET=BTCUSDT
TEST_MARGIN_USDT=5
TEST_HOLD_SECONDS=2
```

Attenzione: il micro-trade usa soldi veri e paga commissioni.

## Note importanti

- con `ENTRY_ORDER_TYPE=limit` l'entry viene messa al prezzo del segnale
- con `ENTRY_ORDER_TYPE=market` il bot entra subito a mercato
- il calcolo size da `MARGIN_USDT` e' `margin * leverage / entry_price`
- il calcolo size da `% saldo` e' `available_futures_balance * percentuale * leverage / entry_price`
- il bot divide la size in parti uguali sui target e corregge l'ultima per i decimali residui
- il bot consente piu' trade attivi insieme, ma solo uno per `market + side`, per allinearsi al modello di posizione CoinEx
- se scegli `BREAK_EVEN_MODE=price_touch`, il break-even usa il feed WebSocket pubblico `state.update`
- se il processo riparte e trova `runtime/active_trade.json`, prova a riprendere il monitoraggio

## Fonti ufficiali usate

- [CoinEx API Introduction](https://docs.coinex.com/api/v2/)
- [CoinEx Authentication](https://docs.coinex.com/api/v2/authorization)
- [CoinEx Futures Market Status](https://docs.coinex.com/api/v2/futures/market/http/list-market)
- [CoinEx Adjust Position Leverage](https://docs.coinex.com/api/v2/futures/position/http/adjust-position-leverage)
- [CoinEx Set Position Stop-Loss](https://docs.coinex.com/api/v2/futures/position/http/set-position-stop-loss)
- [CoinEx Set Position Take-Profit](https://docs.coinex.com/api/v2/futures/position/http/set-position-take-profit)
- [CoinEx Modify Position Stop-Loss](https://docs.coinex.com/api/v2/futures/position/http/modify-position-stop-loss)
- [CoinEx Modify Position Take-Profit](https://docs.coinex.com/api/v2/futures/position/http/modify-position-take-profit)
- [CoinEx User Position Subscription](https://docs.coinex.com/api/v2/futures/position/ws/user-position)
- [CoinEx User Transaction Subscription](https://docs.coinex.com/api/v2/futures/deal/ws/user-deals)
- [CoinEx Changelog](https://docs.coinex.com/api/v2/changelog)
