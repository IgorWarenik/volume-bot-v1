import aiohttp
import asyncio
import config
import logging

logger = logging.getLogger(__name__)

async def send_telegram_message(message: str):
    """Отправка сообщения в Telegram асинхронно."""
    token = config.TELEGRAM_TOKEN
    chat_id = config.TELEGRAM_CHAT_ID
    
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
                    logger.error(f"Ошибка отправки Telegram: {response.status} {text}")
    except Exception as e:
        logger.error(f"Исключение при отправке Telegram: {e}")

if __name__ == "__main__":
    # Для теста
    asyncio.run(send_telegram_message("🔔 <b>Тестовое сообщение</b> от Volume Bot v1"))
