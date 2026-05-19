from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal

from telethon import TelegramClient, events
from telethon.sessions import StringSession

from coinex_trade_bot.config import Settings
from coinex_trade_bot.parser import looks_like_trade_signal
from coinex_trade_bot.service import BotService


LOGGER = logging.getLogger("coinex_trade_bot.telegram")


class TelegramSignalListener:
    def __init__(self, settings: Settings, bot_service: BotService):
        self.settings = settings
        self.bot_service = bot_service
        self.started_at = datetime.now(timezone.utc)
        self.client: TelegramClient | None = None
        self._run_task: asyncio.Task | None = None

    @property
    def configured(self) -> bool:
        return (
            self.settings.telegram_enabled
            and self.settings.telegram_api_id is not None
            and bool(self.settings.telegram_api_hash)
            and bool(self.settings.telegram_session_string)
            and bool(self.settings.telegram_source_chats or self.settings.telegram_paper_source_chats)
        )

    async def start(self) -> None:
        if not self.settings.telegram_enabled:
            LOGGER.info("Telegram listener disabled")
            return
        if not self.configured:
            LOGGER.warning("Telegram listener enabled but not fully configured")
            return

        self.client = TelegramClient(
            StringSession(self.settings.telegram_session_string),
            self.settings.telegram_api_id,
            self.settings.telegram_api_hash,
        )
        await self.client.connect()

        async def _process_event(event, execution_mode: str, leverage: int | None, balance_pct: Decimal | None) -> None:  # noqa: ANN001
            message = event.message
            if getattr(message, "reply_to", None) is not None:
                LOGGER.info("Ignored Telegram message %s: reply/comment to another post", event.id)
                return
            if getattr(message, "fwd_from", None) is not None:
                LOGGER.info("Ignored Telegram message %s: forwarded message", event.id)
                return

            text = event.raw_text or ""
            if not text.strip():
                return
            if not looks_like_trade_signal(text):
                LOGGER.info("Ignored Telegram post %s: not a trade signal", event.id)
                return

            message_dt = event.message.date
            if message_dt.tzinfo is None:
                message_dt = message_dt.replace(tzinfo=timezone.utc)
            if message_dt < self.started_at:
                LOGGER.info("Ignored old Telegram trade signal %s on startup", event.id)
                return

            try:
                source_label = getattr(event.chat, "username", None) or getattr(event.chat, "title", None) or str(event.chat_id)
                summary = await self.bot_service.submit_signal(
                    text,
                    leverage=leverage,
                    balance_pct=balance_pct,
                    execution_mode=execution_mode,
                    source_label=source_label,
                )
                LOGGER.info(
                    "Telegram %s signal accepted from %s message %s: %s",
                    execution_mode,
                    event.chat_id,
                    event.id,
                    summary,
                )
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception(
                    "Telegram %s signal processing failed for chat %s message %s: %s",
                    execution_mode,
                    event.chat_id,
                    event.id,
                    exc,
                )

        if self.settings.telegram_source_chats:
            @self.client.on(events.NewMessage(chats=self.settings.telegram_source_chats))
            async def _handle_live_message(event) -> None:  # noqa: ANN001
                await _process_event(
                    event,
                    execution_mode="live",
                    leverage=self.settings.telegram_leverage,
                    balance_pct=self.settings.telegram_balance_pct,
                )

        if self.settings.telegram_paper_source_chats:
            @self.client.on(events.NewMessage(chats=self.settings.telegram_paper_source_chats))
            async def _handle_paper_message(event) -> None:  # noqa: ANN001
                await _process_event(
                    event,
                    execution_mode="paper",
                    leverage=self.settings.telegram_paper_leverage,
                    balance_pct=self.settings.telegram_paper_balance_pct,
                )

        self._run_task = asyncio.create_task(self.client.run_until_disconnected())
        LOGGER.info(
            "Telegram listener started. Live chats: %s | Paper chats: %s",
            ", ".join(self.settings.telegram_source_chats) or "-",
            ", ".join(self.settings.telegram_paper_source_chats) or "-",
        )

    async def stop(self) -> None:
        if self.client is not None:
            await self.client.disconnect()
        if self._run_task and not self._run_task.done():
            self._run_task.cancel()

    def get_status(self) -> dict[str, object]:
        return {
            "enabled": self.settings.telegram_enabled,
            "configured": self.configured,
            "source_chats": self.settings.telegram_source_chats,
            "paper_source_chats": self.settings.telegram_paper_source_chats,
            "connected": bool(self.client and self.client.is_connected()),
            "balance_pct_override": None if self.settings.telegram_balance_pct is None else format(self.settings.telegram_balance_pct, "f"),
            "leverage_override": self.settings.telegram_leverage,
            "paper_balance_pct_override": None if self.settings.telegram_paper_balance_pct is None else format(self.settings.telegram_paper_balance_pct, "f"),
            "paper_leverage_override": self.settings.telegram_paper_leverage,
        }
