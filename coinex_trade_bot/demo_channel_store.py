from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from coinex_trade_bot.models import DemoChannelConfig


class DemoChannelStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read_all(self) -> dict:
        if not self.path.exists():
            return {"channels": []}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "channels" in data:
            return data
        if isinstance(data, list):
            return {"channels": data}
        return {"channels": []}

    def _write_all(self, payload: dict) -> None:
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def list_all(self) -> list[DemoChannelConfig]:
        return [DemoChannelConfig(**item) for item in self._read_all()["channels"]]

    def list_enabled(self) -> list[DemoChannelConfig]:
        return [item for item in self.list_all() if item.enabled]

    def load(self, channel_id: str) -> DemoChannelConfig | None:
        for channel in self.list_all():
            if channel.channel_id == channel_id:
                return channel
        return None

    def save(self, channel: DemoChannelConfig) -> DemoChannelConfig:
        payload = self._read_all()
        channels = [item for item in payload["channels"] if item.get("channel_id") != channel.channel_id]
        channels.append(asdict(channel))
        self._write_all({"channels": channels})
        return channel

    def create(self, name: str, telegram_ref: str, balance_pct: str, leverage: int, enabled: bool = True) -> DemoChannelConfig:
        now = int(time.time() * 1000)
        channel = DemoChannelConfig(
            channel_id=uuid4().hex[:12],
            name=name,
            telegram_ref=telegram_ref.strip(),
            balance_pct=balance_pct,
            leverage=leverage,
            enabled=enabled,
            created_at=now,
            updated_at=now,
        )
        return self.save(channel)

    def update(
        self,
        channel_id: str,
        *,
        name: str | None = None,
        telegram_ref: str | None = None,
        balance_pct: str | None = None,
        leverage: int | None = None,
        enabled: bool | None = None,
    ) -> DemoChannelConfig:
        channel = self.load(channel_id)
        if channel is None:
            raise RuntimeError(f"Demo channel {channel_id} not found")
        if name is not None:
            channel.name = name
        if telegram_ref is not None:
            channel.telegram_ref = telegram_ref.strip()
        if balance_pct is not None:
            channel.balance_pct = balance_pct
        if leverage is not None:
            channel.leverage = leverage
        if enabled is not None:
            channel.enabled = enabled
        channel.updated_at = int(time.time() * 1000)
        return self.save(channel)

    def delete(self, channel_id: str) -> None:
        payload = self._read_all()
        channels = [item for item in payload["channels"] if item.get("channel_id") != channel_id]
        self._write_all({"channels": channels})

