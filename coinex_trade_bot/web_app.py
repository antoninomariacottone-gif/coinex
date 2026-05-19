from __future__ import annotations

import logging
import secrets
from decimal import Decimal
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

from coinex_trade_bot.coinex_client import CoinExClient
from coinex_trade_bot.config import Settings, load_settings
from coinex_trade_bot.service import BotService
from coinex_trade_bot.state_store import StateStore
from coinex_trade_bot.telegram_listener import TelegramSignalListener


settings = load_settings(allow_missing_secrets=True)
logging.basicConfig(level=getattr(logging, settings.log_level, logging.INFO), format="%(asctime)s | %(levelname)s | %(message)s")

app = FastAPI(title="CoinEx Trade Bot", version="1.0.0")
security = HTTPBasic()
LOGGER = logging.getLogger("coinex_trade_bot.web")


def build_service() -> BotService:
    return BotService(settings, CoinExClient(settings), StateStore(settings.state_file))


service = build_service()
telegram_listener = TelegramSignalListener(settings, service)


class SignalRequest(BaseModel):
    signal_text: str
    leverage: int | None = None
    balance_pct: float | None = None


class CloseTradeRequest(BaseModel):
    trade_id: str


def require_auth(credentials: Annotated[HTTPBasicCredentials, Depends(security)]) -> str:
    valid_username = secrets.compare_digest(credentials.username, settings.dashboard_username)
    valid_password = secrets.compare_digest(credentials.password, settings.dashboard_password)
    if not (valid_username and valid_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@app.on_event("startup")
async def on_startup() -> None:
    await service.startup()
    await telegram_listener.start()


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def dashboard(_: Annotated[str, Depends(require_auth)]) -> str:
    config_warning = ""
    if not settings.access_id or not settings.secret_key:
        config_warning = "<div style='margin-bottom:12px;padding:12px 14px;border-radius:16px;background:#fff3cd;border:1px solid #f0d98a;'>Configurazione incompleta: aggiungi le chiavi CoinEx nelle variabili ambiente Railway prima di usare il bot live.</div>"
    return f"""<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CoinEx Trade Bot</title>
  <style>
    :root {{ color-scheme: light; --bg:#f2efe8; --panel:#fffaf2; --ink:#1e1c19; --accent:#0f766e; --danger:#b42318; --line:#d8d1c2; }}
    body {{ margin:0; font-family: Georgia, 'Times New Roman', serif; background: radial-gradient(circle at top, #fff9ef, var(--bg)); color:var(--ink); }}
    .wrap {{ max-width: 980px; margin: 0 auto; padding: 32px 18px 60px; }}
    .hero {{ display:grid; gap:12px; margin-bottom:24px; }}
    .hero h1 {{ margin:0; font-size: clamp(2rem, 5vw, 4rem); line-height: .95; }}
    .hero p {{ margin:0; max-width: 680px; }}
    .grid {{ display:grid; grid-template-columns: 1.4fr .9fr; gap:18px; }}
    .panel {{ background:var(--panel); border:1px solid var(--line); border-radius:24px; padding:18px; box-shadow:0 18px 40px rgba(0,0,0,.05); }}
    textarea {{ width:100%; min-height:280px; resize:vertical; border-radius:16px; border:1px solid var(--line); padding:14px; font:inherit; background:white; }}
    textarea::placeholder {{ color:#7f7667; opacity:1; }}
    button {{ border:0; border-radius:999px; padding:12px 18px; font:inherit; cursor:pointer; }}
    .primary {{ background:var(--accent); color:white; }}
    .ghost {{ background:white; color:var(--ink); border:1px solid var(--line); }}
    .danger {{ background:var(--danger); color:white; }}
    .actions {{ display:flex; gap:10px; flex-wrap:wrap; margin-top:12px; }}
    pre {{ white-space:pre-wrap; word-break:break-word; background:#fff; border:1px solid var(--line); padding:12px; border-radius:16px; }}
    #result {{ min-height: 160px; }}
    @media (max-width: 840px) {{ .grid {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <h1>CoinEx Trade Bot</h1>
      <p>Dashboard protetta per inviare segnali, vedere il saldo futures e lanciare un micro-trade reale di test su BTC.</p>
    </section>
    <section class="grid">
      <div class="panel">
        {config_warning}
        <h2>Nuovo segnale</h2>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px;">
          <label>Leva<br><input id="leverage" type="number" min="1" step="1" value="{settings.leverage}" style="width:100%;padding:10px;border-radius:14px;border:1px solid var(--line);"></label>
          <label>% saldo futures<br><input id="balancePct" type="number" min="0.1" max="100" step="0.1" value="{'' if settings.default_balance_pct is None else settings.default_balance_pct}" style="width:100%;padding:10px;border-radius:14px;border:1px solid var(--line);"></label>
        </div>
        <textarea id="signal" placeholder="🔴 TON – SHORT
➡️ Punto di ingresso: 1.8002
Obiettivi:
1.7816
1.7513
1.7205
1.6086
❌ Stop Loss: 1.8909
✅ Dopo il primo take profit, spostiamo lo stop loss sul punto di ingresso."></textarea>
        <div class="actions">
          <button class="primary" onclick="submitSignal()">Avvia trade</button>
          <button class="ghost" onclick="refreshStatus()">Aggiorna saldo</button>
          <button class="ghost" onclick="testConnection()">Test collegamento</button>
          <button class="danger" onclick="testTrade()">Test BTC reale</button>
        </div>
      </div>
      <div class="panel">
        <h2>Trade attivi</h2>
        <div id="activeTradesBlock">Caricamento...</div>
        <h2>Stato rapido</h2>
        <pre id="statusBlock">Caricamento...</pre>
        <h2>Saldo futures</h2>
        <pre id="balanceBlock">Caricamento...</pre>
        <h2>Statistiche paper</h2>
        <pre id="paperStatsBlock">Caricamento...</pre>
        <h2>Telegram</h2>
        <pre id="telegramBlock">Caricamento...</pre>
        <h2>Risposta</h2>
        <pre id="result">Pronto.</pre>
      </div>
    </section>
  </div>
  <script>
    function setResult(data) {{
      document.getElementById("result").textContent = JSON.stringify(data, null, 2);
    }}

    function renderTradeCard(trade) {{
      const targets = Array.isArray(trade.targets) ? trade.targets.join(", ") : "";
      const notes = Array.isArray(trade.notes) ? trade.notes.slice(-3).join("\\n") : "";
      return `
        <div style="background:#fff;border:1px solid var(--line);border-radius:18px;padding:12px;margin-bottom:12px;">
          <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start;">
            <div>
              <strong>${{trade.market}} ${{trade.side.toUpperCase()}} [${{(trade.execution_mode || 'live').toUpperCase()}}]</strong><br>
              <small>ID: ${{trade.trade_id}} | Stato: ${{trade.status}}</small>
            </div>
            <button class="danger" onclick="closeTrade('${{trade.trade_id}}')">Chiudi trade</button>
          </div>
          <pre style="margin-top:10px;">${{JSON.stringify({{
            entry_price: trade.entry_price,
            stop_loss: trade.stop_loss,
            break_even_price: trade.break_even_price,
            leverage: trade.leverage,
            balance_pct: trade.balance_pct,
            position_size: trade.position_size,
            remaining_size: trade.remaining_size,
            targets,
            completed_target_count: trade.completed_target_count,
            tp1_done: trade.tp1_done,
            break_even_moved: trade.break_even_moved,
            position_open: trade.position_open,
            realized_pnl_quote: trade.realized_pnl_quote,
            realized_r_multiple: trade.realized_r_multiple,
            source_label: trade.source_label
          }}, null, 2)}}</pre>
          <pre>${{notes || "Nessuna nota recente"}}</pre>
        </div>
      `;
    }}

    async function callApi(url, payload) {{
      try {{
        const response = await fetch(url, {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify(payload || {{}})
        }});
        const rawText = await response.text();
        let data;
        try {{
          data = rawText ? JSON.parse(rawText) : {{}};
        }} catch {{
          data = {{ raw: rawText }};
        }}
        if (!response.ok) {{
          const detail = data.detail || data.raw || rawText || "Unknown error";
          throw new Error(detail);
        }}
        setResult(data);
        return data;
      }} catch (error) {{
        document.getElementById("result").textContent = String(error);
        throw error;
      }}
    }}

    async function refreshStatus() {{
      const response = await fetch("/api/status");
      const rawText = await response.text();
      let data;
      try {{
        data = rawText ? JSON.parse(rawText) : {{}};
      }} catch {{
        throw new Error(rawText || "Invalid /api/status response");
      }}
      if (!response.ok) throw new Error(data.detail || rawText || "Status request failed");
      document.getElementById("statusBlock").textContent = JSON.stringify({{
        configured: data.configured,
        dry_run: data.dry_run,
        test_trade_enabled: data.test_trade_enabled,
        active_trade_count: (data.active_trades || []).length
      }}, null, 2);
      const activeTrades = data.active_trades || [];
      document.getElementById("activeTradesBlock").innerHTML = activeTrades.length
        ? activeTrades.map(renderTradeCard).join("")
        : "<pre>Nessun trade attivo</pre>";
      if (data.balance) {{
        document.getElementById("balanceBlock").textContent = JSON.stringify(data.balance, null, 2);
      }} else if (data.balance_error) {{
        document.getElementById("balanceBlock").textContent = data.balance_error;
      }} else {{
        document.getElementById("balanceBlock").textContent = "Saldo non disponibile";
      }}
      if (data.paper_stats) {{
        document.getElementById("paperStatsBlock").textContent = JSON.stringify(data.paper_stats, null, 2);
      }} else {{
        document.getElementById("paperStatsBlock").textContent = "Nessuna statistica paper disponibile";
      }}
      if (data.telegram) {{
        document.getElementById("telegramBlock").textContent = JSON.stringify(data.telegram, null, 2);
      }} else {{
        document.getElementById("telegramBlock").textContent = "Telegram non configurato";
      }}
      return data;
    }}

    async function submitSignal() {{
      const leverageValue = document.getElementById("leverage").value;
      const balancePctValue = document.getElementById("balancePct").value;
      await callApi("/api/signal", {{
        signal_text: document.getElementById("signal").value,
        leverage: leverageValue ? Number(leverageValue) : null,
        balance_pct: balancePctValue ? Number(balancePctValue) : null
      }});
    }}
    async function testConnection() {{
      await callApi("/api/test-connection", {{}});
      await refreshStatus();
    }}
    async function testTrade() {{
      if (!confirm("Il test BTC apre una posizione reale per pochi secondi e paga fee. Continuare?")) return;
      await callApi("/api/test-trade", {{}});
      await refreshStatus();
    }}
    async function closeTrade(tradeId) {{
      if (!confirm("Vuoi chiudere questo trade e cancellare i suoi TP/SL?")) return;
      await callApi("/api/close-trade", {{ trade_id: tradeId }});
      await refreshStatus();
    }}
    refreshStatus().catch((error) => {{
      document.getElementById("balanceBlock").textContent = error.message;
    }});
  </script>
</body>
</html>"""


@app.get("/api/status")
async def api_status(_: Annotated[str, Depends(require_auth)]) -> dict:
    return await service.get_dashboard_status()


@app.post("/api/signal")
async def api_signal(payload: SignalRequest, _: Annotated[str, Depends(require_auth)]) -> dict:
    try:
        balance_pct = None if payload.balance_pct is None else Decimal(str(payload.balance_pct))
        summary = await service.submit_signal(
            payload.signal_text,
            leverage=payload.leverage,
            balance_pct=balance_pct,
        )
        return {"ok": True, "summary": summary}
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("Signal submission failed")
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/test-connection")
async def api_test_connection(_: Annotated[str, Depends(require_auth)]) -> dict:
    try:
        result = await service.test_connection()
        return {"ok": True, "result": result}
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("Test connection failed")
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/test-trade")
async def api_test_trade(_: Annotated[str, Depends(require_auth)]) -> dict:
    try:
        result = await service.run_test_trade()
        return {"ok": True, "result": result}
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("Test trade failed")
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/close-trade")
async def api_close_trade(payload: CloseTradeRequest, _: Annotated[str, Depends(require_auth)]) -> dict:
    try:
        result = await service.close_trade(payload.trade_id)
        return {"ok": True, "result": result}
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("Close trade failed")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
