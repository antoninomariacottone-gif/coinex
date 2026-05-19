from __future__ import annotations

import gzip
import hashlib
import hmac
import json
import time
from decimal import Decimal, ROUND_DOWN
from typing import Any
from urllib.parse import urlencode

import requests
import websockets

from coinex_trade_bot.config import Settings
from coinex_trade_bot.models import MarketInfo


class CoinExClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
            }
        )

    def _timestamp(self) -> str:
        return str(int(time.time() * 1000))

    def _sign_http(self, method: str, request_path: str, body: str, timestamp: str) -> str:
        prepared = f"{method.upper()}{request_path}{body}{timestamp}"
        return hmac.new(
            self.settings.secret_key.encode("latin-1"),
            msg=prepared.encode("latin-1"),
            digestmod=hashlib.sha256,
        ).hexdigest().lower()

    def _headers(self, signed_str: str, timestamp: str) -> dict[str, str]:
        return {
            "X-COINEX-KEY": self.settings.access_id,
            "X-COINEX-SIGN": signed_str,
            "X-COINEX-TIMESTAMP": timestamp,
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        }

    def _request(self, method: str, path: str, params: dict[str, Any] | None = None, payload: dict[str, Any] | None = None) -> Any:
        params = params or {}
        payload = payload or {}
        url = f"{self.settings.http_base_url}{path}"
        timestamp = self._timestamp()

        if method.upper() == "GET":
            query = urlencode({k: v for k, v in params.items() if v is not None})
            request_path = f"/v2{path}"
            if query:
                request_path = f"{request_path}?{query}"
            signed = self._sign_http("GET", request_path, "", timestamp)
            response = self.session.get(url, params=params, headers=self._headers(signed, timestamp), timeout=15)
        else:
            body = json.dumps(payload, separators=(",", ":"))
            request_path = f"/v2{path}"
            signed = self._sign_http(method, request_path, body, timestamp)
            response = self.session.request(method.upper(), url, data=body, headers=self._headers(signed, timestamp), timeout=15)

        if not response.ok:
            body = response.text.strip()
            raise RuntimeError(f"CoinEx HTTP error on {path}: status={response.status_code}, body={body}")
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(f"CoinEx returned non-JSON on {path}: status={response.status_code}, body={response.text}") from exc
        if data.get("code") != 0:
            raise RuntimeError(f"CoinEx API error on {path}: {data}")
        return data["data"]

    def get_market_info(self, market: str) -> MarketInfo:
        data = self._request("GET", "/futures/market", params={"market": market})
        if not data:
            raise ValueError(f"Market {market} not found on CoinEx futures")
        info = data[0]
        return MarketInfo(
            market=info["market"],
            min_amount=Decimal(info["min_amount"]),
            tick_size=Decimal(info["tick_size"]),
            base_precision=int(info["base_ccy_precision"]),
            quote_precision=int(info["quote_ccy_precision"]),
            leverage_options=[int(value) for value in info["leverage"]],
            is_api_trading_available=bool(info["is_api_trading_available"]),
        )

    def get_futures_balance(self) -> Any:
        return self._request("GET", "/assets/futures/balance")

    def get_futures_ticker(self, market: str) -> dict[str, Any]:
        data = self._request("GET", "/futures/ticker", params={"market": market})
        if not data:
            raise ValueError(f"Ticker for {market} not found on CoinEx futures")
        return data[0]

    def adjust_leverage(self, market: str, leverage: int | None = None) -> Any:
        return self._request(
            "POST",
            "/futures/adjust-position-leverage",
            payload={
                "market": market,
                "market_type": self.settings.market_type,
                "margin_mode": self.settings.margin_mode,
                "leverage": leverage or self.settings.leverage,
            },
        )

    def place_entry_order(
        self,
        market: str,
        side: str,
        amount: Decimal,
        price: Decimal | None,
        order_type_override: str | None = None,
    ) -> Any:
        order_type = order_type_override or self.settings.entry_order_type
        payload: dict[str, Any] = {
            "market": market,
            "market_type": self.settings.market_type,
            "side": "buy" if side == "long" else "sell",
            "type": order_type,
            "amount": format(amount, "f"),
            "client_id": f"tv_entry_{int(time.time())}",
        }
        if order_type == "limit":
            if price is None:
                raise ValueError("Limit entry requires a price")
            payload["price"] = format(price, "f")
        return self._request("POST", "/futures/order", payload=payload)

    def close_position(self, market: str, order_type: str = "market", amount: Decimal | None = None, price: Decimal | None = None) -> Any:
        payload: dict[str, Any] = {
            "market": market,
            "market_type": self.settings.market_type,
            "type": order_type,
            "client_id": f"tv_close_{int(time.time())}",
        }
        if amount is not None:
            payload["amount"] = format(amount, "f")
        if order_type == "limit":
            if price is None:
                raise ValueError("Limit close requires a price")
            payload["price"] = format(price, "f")
        return self._request("POST", "/futures/close-position", payload=payload)

    def get_pending_orders(self, market: str) -> list[dict[str, Any]]:
        return self._request(
            "GET",
            "/futures/pending-order",
            params={"market": market, "market_type": self.settings.market_type, "page": 1, "limit": 100},
        )

    def cancel_order(self, market: str, order_id: int) -> Any:
        return self._request(
            "POST",
            "/futures/cancel-order",
            payload={"market": market, "market_type": self.settings.market_type, "order_id": order_id},
        )

    def get_pending_position(self, market: str) -> list[dict[str, Any]]:
        data = self._request(
            "GET",
            "/futures/pending-position",
            params={"market": market, "market_type": self.settings.market_type},
        )
        return data

    def set_position_stop_loss(self, market: str, price: Decimal, amount: Decimal | None = None) -> Any:
        payload: dict[str, Any] = {
            "market": market,
            "market_type": self.settings.market_type,
            "stop_loss_type": self.settings.trigger_price_type,
            "stop_loss_price": format(price, "f"),
        }
        if amount is not None:
            payload["stop_loss_amount"] = format(amount, "f")
        return self._request("POST", "/futures/set-position-stop-loss", payload=payload)

    def modify_position_stop_loss(self, market: str, stop_loss_id: int, price: Decimal) -> Any:
        return self._request(
            "POST",
            "/futures/modify-position-stop-loss",
            payload={
                "market": market,
                "market_type": self.settings.market_type,
                "stop_loss_id": stop_loss_id,
                "stop_loss_price": format(price, "f"),
            },
        )

    def cancel_position_stop_loss(self, market: str, stop_loss_id: int | None = None) -> Any:
        payload: dict[str, Any] = {
            "market": market,
            "market_type": self.settings.market_type,
        }
        if stop_loss_id is not None:
            payload["stop_loss_id"] = stop_loss_id
        return self._request("POST", "/futures/cancel-position-stop-loss", payload=payload)

    def set_position_take_profit(self, market: str, price: Decimal, amount: Decimal | None = None) -> Any:
        payload: dict[str, Any] = {
            "market": market,
            "market_type": self.settings.market_type,
            "take_profit_type": self.settings.trigger_price_type,
            "take_profit_price": format(price, "f"),
        }
        if amount is not None:
            payload["take_profit_amount"] = format(amount, "f")
        return self._request("POST", "/futures/set-position-take-profit", payload=payload)

    def cancel_position_take_profit(self, market: str, take_profit_id: int | None = None) -> Any:
        payload: dict[str, Any] = {
            "market": market,
            "market_type": self.settings.market_type,
        }
        if take_profit_id is not None:
            payload["take_profit_id"] = take_profit_id
        return self._request("POST", "/futures/cancel-position-take-profit", payload=payload)

    def quantize_price(self, value: Decimal, tick_size: Decimal) -> Decimal:
        if tick_size == 0:
            return value
        steps = (value / tick_size).to_integral_value(rounding=ROUND_DOWN)
        return steps * tick_size

    def quantize_amount(self, value: Decimal, precision: int) -> Decimal:
        quantum = Decimal("1").scaleb(-precision)
        return value.quantize(quantum, rounding=ROUND_DOWN)

    async def ws_connect(self):
        return await websockets.connect(self.settings.ws_futures_url, compression=None, ping_interval=None)

    async def ws_auth(self, conn) -> None:
        timestamp = int(time.time() * 1000)
        signed_str = hmac.new(
            self.settings.secret_key.encode("latin-1"),
            msg=str(timestamp).encode("latin-1"),
            digestmod=hashlib.sha256,
        ).hexdigest().lower()
        await conn.send(
            json.dumps(
                {
                    "method": "server.sign",
                    "params": {
                        "access_id": self.settings.access_id,
                        "signed_str": signed_str,
                        "timestamp": timestamp,
                    },
                    "id": 1,
                }
            )
        )
        message = await self.ws_recv_json(conn)
        if message.get("code") != 0:
            raise RuntimeError(f"CoinEx WS auth failed: {message}")

    async def ws_ping(self, conn) -> None:
        while True:
            await conn.send(json.dumps({"method": "server.ping", "params": {}, "id": 999}))
            await time_async_sleep(3)

    async def ws_recv_json(self, conn) -> dict[str, Any]:
        message = await conn.recv()
        if isinstance(message, bytes):
            message = gzip.decompress(message).decode("utf-8")
        return json.loads(message)


async def time_async_sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)
