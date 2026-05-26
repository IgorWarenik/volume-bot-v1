import aiohttp
import asyncio
import config
import logging

logger = logging.getLogger(__name__)

async def _send_message(chat_id: str, message: str):
    """Внутренняя функция отправки сообщения в указанный чат."""
    token = config.TELEGRAM_TOKEN

    if not token or token == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        logger.warning("Telegram Token не настроен. Сообщение не отправлено.")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.post(url, json=payload) as response:
                if response.status != 200:
                    text = await response.text()
                    logger.error(f"Ошибка отправки в {chat_id}: {response.status} {text}")
    except Exception as e:
        logger.error(f"Исключение при отправке в {chat_id}: {e}")


async def send_telegram_message(message: str):
    """Отправить сообщение в личный чат (ответы на команды, статус)."""
    await _send_message(config.TELEGRAM_CHAT_ID, message)


async def send_signal(message: str):
    """Опубликовать торговый сигнал в канал."""
    await _send_message(config.TELEGRAM_CHANNEL_ID, message)


if __name__ == "__main__":
    asyncio.run(send_signal("🔔 <b>Тестовый сигнал</b> от Volume Bot v1"))
