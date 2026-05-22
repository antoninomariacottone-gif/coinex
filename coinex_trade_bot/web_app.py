from __future__ import annotations

import json
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
from coinex_trade_bot.demo_channel_store import DemoChannelStore
from coinex_trade_bot.service import BotService
from coinex_trade_bot.state_store import StateStore
from coinex_trade_bot.telegram_listener import TelegramSignalListener


settings = load_settings(allow_missing_secrets=True)
logging.basicConfig(level=getattr(logging, settings.log_level, logging.INFO), format="%(asctime)s | %(levelname)s | %(message)s")

app = FastAPI(title="CoinEx Trade Bot", version="1.0.0")
security = HTTPBasic()
LOGGER = logging.getLogger("coinex_trade_bot.web")


def build_service() -> BotService:
    return BotService(
        settings,
        CoinExClient(settings),
        StateStore(settings.state_file),
        DemoChannelStore(settings.demo_channels_file),
    )


service = build_service()
telegram_listener = TelegramSignalListener(settings, service)


class SignalRequest(BaseModel):
    signal_text: str
    leverage: int | None = None
    balance_pct: float | None = None


class CloseTradeRequest(BaseModel):
    trade_id: str


class DemoChannelRequest(BaseModel):
    name: str
    telegram_ref: str
    balance_pct: float
    leverage: int
    enabled: bool = True


class DemoChannelUpdateRequest(BaseModel):
    name: str | None = None
    telegram_ref: str | None = None
    balance_pct: float | None = None
    leverage: int | None = None
    enabled: bool | None = None


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


def _main_dashboard_html() -> str:
    config_warning = ""
    if not settings.access_id or not settings.secret_key:
        config_warning = "<div style='margin-bottom:12px;padding:12px 14px;border-radius:16px;background:#fff3cd;border:1px solid #f0d98a;'>Configurazione incompleta: aggiungi le chiavi CoinEx prima di usare il bot live.</div>"
    return f"""<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CoinEx Trade Bot</title>
  <style>
    :root {{ color-scheme: light; --bg:#f2efe8; --panel:#fffaf2; --ink:#1e1c19; --accent:#0f766e; --danger:#b42318; --line:#d8d1c2; }}
    body {{ margin:0; font-family: Georgia, 'Times New Roman', serif; background: radial-gradient(circle at top, #fff9ef, var(--bg)); color:var(--ink); }}
    .wrap {{ max-width: 1280px; margin: 0 auto; padding: 32px 18px 60px; }}
    .hero {{ display:grid; gap:12px; margin-bottom:24px; }}
    .hero h1 {{ margin:0; font-size: clamp(2rem, 5vw, 4rem); line-height: .95; }}
    .hero p {{ margin:0; max-width: 780px; }}
    .grid {{ display:grid; grid-template-columns: 1.2fr .8fr; gap:18px; }}
    .stack {{ display:grid; gap:18px; }}
    .panel {{ background:var(--panel); border:1px solid var(--line); border-radius:24px; padding:18px; box-shadow:0 18px 40px rgba(0,0,0,.05); }}
    textarea, input {{ width:100%; border-radius:16px; border:1px solid var(--line); padding:12px; font:inherit; background:white; box-sizing:border-box; }}
    textarea {{ min-height:220px; resize:vertical; }}
    textarea::placeholder {{ color:#7f7667; opacity:1; }}
    button, a.btn {{ border:0; border-radius:999px; padding:12px 18px; font:inherit; cursor:pointer; text-decoration:none; display:inline-block; }}
    .primary {{ background:var(--accent); color:white; }}
    .ghost {{ background:white; color:var(--ink); border:1px solid var(--line); }}
    .danger {{ background:var(--danger); color:white; }}
    .actions {{ display:flex; gap:10px; flex-wrap:wrap; margin-top:12px; }}
    pre {{ white-space:pre-wrap; word-break:break-word; background:#fff; border:1px solid var(--line); padding:12px; border-radius:16px; }}
    .cards {{ display:grid; gap:12px; }}
    #result {{ min-height: 160px; }}
    @media (max-width: 960px) {{ .grid {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <h1>CoinEx Trade Bot</h1>
      <p>Live trading separato dal demo trading. I canali demo si gestiscono dal pannello, lavorano a percentuale e hanno una pagina dedicata ciascuno.</p>
    </section>
    <section class="grid">
      <div class="stack">
        <div class="panel">
          {config_warning}
          <h2>Live Trading</h2>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px;">
            <label>Leva live<br><input id="leverage" type="number" min="1" step="1" value="{settings.leverage}"></label>
            <label>% saldo live<br><input id="balancePct" type="number" min="0.1" max="100" step="0.1" value="{'' if settings.default_balance_pct is None else settings.default_balance_pct}"></label>
          </div>
          <textarea id="signal" placeholder="🔴 ONDO – LONG
➡️Punto di ingresso: 0.4073
Obiettivi:
0.4115
0.4192
0.4267
0.4517
❌ Stop Loss: 0.3868"></textarea>
          <div class="actions">
            <button class="primary" onclick="submitSignal()">Avvia trade live</button>
            <button class="ghost" onclick="refreshStatus()">Aggiorna saldo</button>
            <button class="ghost" onclick="testConnection()">Test collegamento</button>
            <button class="danger" onclick="testTrade()">Test BTC reale</button>
          </div>
        </div>

        <div class="panel">
          <h2>Canali Demo</h2>
          <p style="margin-top:0;">Aggiungi qui i canali demo. Ogni canale usa sempre la sua percentuale di saldo e la sua leva, senza toccare le variabili ambiente.</p>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
            <label>Nome canale<br><input id="demoChannelName" placeholder="Ninjas Demo"></label>
            <label>Telegram ref<br><input id="demoChannelRef" placeholder="@cryptoninjas_trading_ann"></label>
            <label>% saldo demo<br><input id="demoChannelPct" type="number" min="0.1" max="100" step="0.1" value="7"></label>
            <label>Leva demo<br><input id="demoChannelLev" type="number" min="1" step="1" value="20"></label>
          </div>
          <div class="actions">
            <button class="primary" onclick="createDemoChannel()">Aggiungi canale demo</button>
          </div>
          <div id="demoChannelsList" class="cards" style="margin-top:12px;">Caricamento...</div>
        </div>

        <div class="panel">
          <h2>Demo Manuale</h2>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px;">
            <label>Leva demo manuale<br><input id="demoLeverage" type="number" min="1" step="1" value="20"></label>
            <label>% saldo demo manuale<br><input id="demoBalancePct" type="number" min="0.1" max="100" step="0.1" value="7"></label>
          </div>
          <textarea id="demoSignal" placeholder="📊 #TIA/USDT

🟢 POSITION: LONG
💰 ENTRY RANGE
➤ 0.435 - 0.41
🎯 PROFIT TARGETS
➊ 0.445
➋ 0.46
➌ 0.49
🛑 STOP LOSS
➤ 0.385"></textarea>
          <div class="actions">
            <button class="primary" onclick="submitDemoSignal()">Avvia demo manuale</button>
          </div>
        </div>
      </div>

      <div class="panel">
        <h2>Trade attivi</h2>
        <div id="activeTradesBlock">Caricamento...</div>
        <h2>Stato rapido</h2>
        <pre id="statusBlock">Caricamento...</pre>
        <h2>Saldo futures</h2>
        <pre id="balanceBlock">Caricamento...</pre>
        <h2>Statistiche demo</h2>
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
      const notes = Array.isArray(trade.notes) ? trade.notes.slice(-4).join("\\n") : "";
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
            signal_entry_price: trade.signal_entry_price,
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
        </div>`;
    }}

    function renderDemoChannelCard(channel) {{
      const stats = channel.stats || {{}};
      return `
        <div style="background:#fff;border:1px solid var(--line);border-radius:18px;padding:12px;">
          <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start;">
            <div>
              <strong>${{channel.name}}</strong><br>
              <small>${{channel.telegram_ref}} | ${{channel.enabled ? 'attivo' : 'pausato'}}</small>
            </div>
            <a class="btn ghost" href="/demo/channels/${{channel.channel_id}}">Apri pagina</a>
          </div>
          <pre style="margin-top:10px;">${{JSON.stringify({{
            balance_pct: channel.balance_pct,
            leverage: channel.leverage,
            trade_count: stats.trade_count || 0,
            win_rate_pct: stats.win_rate_pct || "0.00",
            realized_pnl_quote: stats.realized_pnl_quote || "0"
          }}, null, 2)}}</pre>
        </div>`;
    }}

    async function callApi(url, method, payload) {{
      const response = await fetch(url, {{
        method: method || "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: payload ? JSON.stringify(payload) : undefined
      }});
      const rawText = await response.text();
      let data;
      try {{
        data = rawText ? JSON.parse(rawText) : {{}};
      }} catch {{
        data = {{ raw: rawText }};
      }}
      if (!response.ok) {{
        throw new Error(data.detail || data.raw || rawText || "Unknown error");
      }}
      setResult(data);
      return data;
    }}

    async function refreshStatus() {{
      const response = await fetch("/api/status");
      const data = await response.json();
      document.getElementById("statusBlock").textContent = JSON.stringify({{
        configured: data.configured,
        dry_run: data.dry_run,
        test_trade_enabled: data.test_trade_enabled,
        active_trade_count: (data.active_trades || []).length,
        paper_trade_count: data.paper_stats ? data.paper_stats.paper_trade_count : 0
      }}, null, 2);
      document.getElementById("activeTradesBlock").innerHTML = (data.active_trades || []).length
        ? data.active_trades.map(renderTradeCard).join("")
        : "<pre>Nessun trade attivo</pre>";
      document.getElementById("balanceBlock").textContent = data.balance
        ? JSON.stringify(data.balance, null, 2)
        : (data.balance_error || "Saldo non disponibile");
      document.getElementById("paperStatsBlock").textContent = data.paper_stats
        ? JSON.stringify(data.paper_stats, null, 2)
        : "Nessuna statistica demo disponibile";
      document.getElementById("telegramBlock").textContent = data.telegram
        ? JSON.stringify(data.telegram, null, 2)
        : "Telegram non configurato";
      document.getElementById("demoChannelsList").innerHTML = (data.demo_channels || []).length
        ? data.demo_channels.map(renderDemoChannelCard).join("")
        : "<pre>Nessun canale demo configurato</pre>";
      return data;
    }}

    async function submitSignal() {{
      await callApi("/api/signal", "POST", {{
        signal_text: document.getElementById("signal").value,
        leverage: Number(document.getElementById("leverage").value) || null,
        balance_pct: Number(document.getElementById("balancePct").value) || null
      }});
      await refreshStatus();
    }}

    async function submitDemoSignal() {{
      await callApi("/api/demo-signal", "POST", {{
        signal_text: document.getElementById("demoSignal").value,
        leverage: Number(document.getElementById("demoLeverage").value) || null,
        balance_pct: Number(document.getElementById("demoBalancePct").value) || null
      }});
      await refreshStatus();
    }}

    async function createDemoChannel() {{
      await callApi("/api/demo-channels", "POST", {{
        name: document.getElementById("demoChannelName").value,
        telegram_ref: document.getElementById("demoChannelRef").value,
        balance_pct: Number(document.getElementById("demoChannelPct").value),
        leverage: Number(document.getElementById("demoChannelLev").value),
        enabled: true
      }});
      await refreshStatus();
    }}

    async function testConnection() {{
      await callApi("/api/test-connection", "POST", {{}});
      await refreshStatus();
    }}

    async function testTrade() {{
      if (!confirm("Il test BTC apre una posizione reale per pochi secondi e paga fee. Continuare?")) return;
      await callApi("/api/test-trade", "POST", {{}});
      await refreshStatus();
    }}

    async function closeTrade(tradeId) {{
      if (!confirm("Vuoi chiudere questo trade e cancellare i suoi TP/SL?")) return;
      await callApi("/api/close-trade", "POST", {{ trade_id: tradeId }});
      await refreshStatus();
    }}

    refreshStatus().catch((error) => {{
      document.getElementById("result").textContent = String(error);
    }});
  </script>
</body>
</html>"""


def _demo_channel_page_html(channel_data: dict) -> str:
    channel = channel_data["channel"]
    stats_json = json.dumps(channel_data["stats"], indent=2)
    trades_json = json.dumps(channel_data["trades"], indent=2)
    return f"""<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{channel.name} Demo</title>
  <style>
    body {{ margin:0; font-family: Georgia, 'Times New Roman', serif; background:#f2efe8; color:#1e1c19; }}
    .wrap {{ max-width: 980px; margin: 0 auto; padding: 28px 18px 50px; }}
    .panel {{ background:#fffaf2; border:1px solid #d8d1c2; border-radius:24px; padding:18px; margin-bottom:18px; }}
    input {{ width:100%; border-radius:16px; border:1px solid #d8d1c2; padding:12px; font:inherit; box-sizing:border-box; }}
    button, a {{ border-radius:999px; padding:12px 18px; font:inherit; text-decoration:none; }}
    button {{ border:0; cursor:pointer; background:#0f766e; color:#fff; }}
    a {{ border:1px solid #d8d1c2; color:#1e1c19; display:inline-block; }}
    pre {{ white-space:pre-wrap; word-break:break-word; background:#fff; border:1px solid #d8d1c2; padding:12px; border-radius:16px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="panel">
      <a href="/">Torna alla dashboard</a>
      <h1>{channel.name}</h1>
      <p>{channel.telegram_ref}</p>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;">
        <label>% saldo demo<br><input id="balancePct" type="number" step="0.1" value="{channel.balance_pct}"></label>
        <label>Leva demo<br><input id="leverage" type="number" step="1" value="{channel.leverage}"></label>
        <label>Attivo<br><input id="enabled" type="text" value="{str(channel.enabled).lower()}"></label>
      </div>
      <div style="margin-top:12px;">
        <button onclick="saveChannel()">Salva</button>
      </div>
    </div>
    <div class="panel">
      <h2>Statistiche</h2>
      <pre id="stats">{stats_json}</pre>
    </div>
    <div class="panel">
      <h2>Trade di questo canale</h2>
      <pre id="trades">{trades_json}</pre>
    </div>
  </div>
  <script>
    async function saveChannel() {{
      const response = await fetch("/api/demo-channels/{channel.channel_id}", {{
        method: "PATCH",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{
          balance_pct: Number(document.getElementById("balancePct").value),
          leverage: Number(document.getElementById("leverage").value),
          enabled: document.getElementById("enabled").value.toLowerCase() === "true"
        }})
      }});
      if (!response.ok) {{
        const data = await response.text();
        alert(data);
        return;
      }}
      location.reload();
    }}
  </script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def dashboard(_: Annotated[str, Depends(require_auth)]) -> str:
    return _main_dashboard_html()


@app.get("/demo/channels/{channel_id}", response_class=HTMLResponse)
async def demo_channel_page(channel_id: str, _: Annotated[str, Depends(require_auth)]) -> str:
    try:
        return _demo_channel_page_html(service.get_demo_channel_page(channel_id))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/status")
async def api_status(_: Annotated[str, Depends(require_auth)]) -> dict:
    return await service.get_dashboard_status()


@app.post("/api/signal")
async def api_signal(payload: SignalRequest, _: Annotated[str, Depends(require_auth)]) -> dict:
    try:
        balance_pct = None if payload.balance_pct is None else Decimal(str(payload.balance_pct))
        summary = await service.submit_signal(payload.signal_text, leverage=payload.leverage, balance_pct=balance_pct)
        return {"ok": True, "summary": summary}
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("Signal submission failed")
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/demo-signal")
async def api_demo_signal(payload: SignalRequest, _: Annotated[str, Depends(require_auth)]) -> dict:
    try:
        balance_pct = None if payload.balance_pct is None else Decimal(str(payload.balance_pct))
        summary = await service.submit_signal(
            payload.signal_text,
            leverage=payload.leverage,
            balance_pct=balance_pct,
            execution_mode="paper",
            source_label="manual-demo",
        )
        return {"ok": True, "summary": summary}
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("Demo signal submission failed")
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/demo-channels")
async def api_create_demo_channel(payload: DemoChannelRequest, _: Annotated[str, Depends(require_auth)]) -> dict:
    try:
        channel = service.create_demo_channel(
            name=payload.name,
            telegram_ref=payload.telegram_ref,
            balance_pct=Decimal(str(payload.balance_pct)),
            leverage=payload.leverage,
        )
        return {"ok": True, "channel": channel.__dict__}
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("Create demo channel failed")
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/demo-channels/{channel_id}")
async def api_update_demo_channel(channel_id: str, payload: DemoChannelUpdateRequest, _: Annotated[str, Depends(require_auth)]) -> dict:
    try:
        channel = service.update_demo_channel(
            channel_id,
            name=payload.name,
            telegram_ref=payload.telegram_ref,
            balance_pct=None if payload.balance_pct is None else Decimal(str(payload.balance_pct)),
            leverage=payload.leverage,
            enabled=payload.enabled,
        )
        return {"ok": True, "channel": channel.__dict__}
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("Update demo channel failed")
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/demo-channels/{channel_id}")
async def api_delete_demo_channel(channel_id: str, _: Annotated[str, Depends(require_auth)]) -> dict:
    try:
        service.delete_demo_channel(channel_id)
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("Delete demo channel failed")
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
