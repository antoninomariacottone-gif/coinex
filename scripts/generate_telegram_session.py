from __future__ import annotations

import asyncio
import os

from telethon import TelegramClient
from telethon.sessions import StringSession


async def main() -> None:
    api_id = int(os.environ["TELEGRAM_API_ID"])
    api_hash = os.environ["TELEGRAM_API_HASH"]

    async with TelegramClient(StringSession(), api_id, api_hash) as client:
        print("Login Telegram richiesto. Segui le istruzioni nel terminale.")
        session_string = client.session.save()
        print("\nTELEGRAM_SESSION_STRING=\n")
        print(session_string)


if __name__ == "__main__":
    asyncio.run(main())
