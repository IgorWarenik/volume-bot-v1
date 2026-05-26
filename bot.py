import asyncio
import aiohttp
import time
import logging
import json
import os
import config
import re
from telegram_notifier import send_telegram_message, send_signal
from keep_alive import keep_alive

DEDUP_FILE = "sent_alerts.json"

def load_sent_alerts() -> dict:
    """Загрузить историю отправленных алертов с диска."""
    if not os.path.exists(DEDUP_FILE):
        return {}
    try:
        with open(DEDUP_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_sent_alerts(data: dict):
    """Сохранить историю на диск."""
    try:
        with open(DEDUP_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logger.error(f"Ошибка сохранения дедупликации: {e}")

def cleanup_sent_alerts(data: dict) -> dict:
    """Удалить записи старше 2 таймфреймов, чтобы файл не разрастался."""
    try:
        timeframe_ms = int(config.TIMEFRAME) * 60 * 1000
        cutoff = int(time.time() * 1000) - 2 * timeframe_ms
        return {k: v for k, v in data.items() if v > cutoff}
    except Exception:
        return data

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

API_URL = "https://api.bytick.com"

async def fetch_tickers(session: aiohttp.ClientSession) -> list:
    """Получить список всех фьючерсов и отфильтровать по объему."""
    url = f"{API_URL}/v5/market/tickers"
    params = {"category": "linear"}
    
    try:
        async with session.get(url, params=params) as response:
            if response.status != 200:
                logger.error(f"Ошибка tickers: HTTP {response.status}")
                return []
            
            data = await response.json()
            if data.get("retCode") != 0:
                logger.error(f"Ошибка API tickers: {data.get('retMsg')}")
                return []
                
            tickers = data.get("result", {}).get("list", [])
            
            valid_symbols = []
            for t in tickers:
                symbol = t.get("symbol", "")
                if not symbol.endswith("USDT") or symbol in config.BLACKLIST:
                    continue
                    
                turnover24h = float(t.get("turnover24h", 0))
                if turnover24h >= config.MIN_TURNOVER_24H:
                    valid_symbols.append(symbol)
                    
            return valid_symbols
            
    except Exception as e:
        logger.error(f"Исключение при запросе tickers: {e}")
        return []


async def check_volume_spike(session: aiohttp.ClientSession, symbol: str) -> dict:
    """Проверить объем монеты за последние свечи."""
    # Запрашиваем N свечей + 1 (для текущей)
    limit = config.LOOKBACK_CANDLES + 1
    url = f"{API_URL}/v5/market/kline"
    params = {
        "category": "linear",
        "symbol": symbol,
        "interval": config.TIMEFRAME,
        "limit": limit
    }
    
    try:
        async with session.get(url, params=params) as response:
            if response.status != 200:
                return None
                
            data = await response.json()
            if data.get("retCode") != 0:
                return None
                
            # Bybit возвращает свечи от новых к старым (index 0 - самая новая)
            klines = data.get("result", {}).get("list", [])
            
            if len(klines) < limit:
                return None # Недостаточно истории
                
            # klines[0] - текущая минута (или только что закрывшаяся)
            # klines[1:] - история для расчета среднего
            
            current_kline = klines[0]
            current_volume = float(current_kline[4]) # index 4 is volume (base coin)
            # current_turnover = float(current_kline[5]) # index 5 is turnover (quote coin)
            
            history_klines = klines[1:]
            history_volumes = [float(k[4]) for k in history_klines]
            
            avg_volume = sum(history_volumes) / len(history_volumes)
            
            if avg_volume <= 0:
                return None
                
            ratio = current_volume / avg_volume
            
            if ratio >= config.VOLUME_MULTIPLIER:
                return {
                    "symbol": symbol,
                    "ratio": ratio,
                    "current_volume": current_volume,
                    "avg_volume": avg_volume,
                    "price": float(current_kline[4]) # Actually price is close (index 4) - wait, Bybit v5: 
                    # 0: startTime, 1: open, 2: high, 3: low, 4: close, 5: volume, 6: turnover
                    # Oh, let me fix indices!
                }
            return None
            
    except Exception as e:
        if config.VERBOSE:
            logger.debug(f"Ошибка {symbol}: {e}")
        return None

async def check_volume_spike_fixed(session: aiohttp.ClientSession, symbol: str) -> dict:
    """Исправленный индекс."""
    limit = config.LOOKBACK_CANDLES + 1
    url = f"{API_URL}/v5/market/kline"
    params = {
        "category": "linear",
        "symbol": symbol,
        "interval": config.TIMEFRAME,
        "limit": limit
    }
    
    try:
        async with session.get(url, params=params) as response:
            if response.status != 200:
                return None
            data = await response.json()
            if data.get("retCode") != 0:
                return None
                
            klines = data.get("result", {}).get("list", [])
            if len(klines) < limit:
                return None
                
            # Bybit Kline: [startTime, open, high, low, close, volume, turnover]
            current_kline = klines[0]
            current_close_price = float(current_kline[4])
            current_turnover = float(current_kline[6]) # Берем оборот в USDT (turnover), это лучше чем в монетах
            
            history_klines = klines[1:]
            history_turnovers = [float(k[6]) for k in history_klines]
            
            avg_turnover = sum(history_turnovers) / len(history_turnovers)
            
            if avg_turnover <= 0:
                return None
                
            ratio = current_turnover / avg_turnover
            
            if ratio >= config.VOLUME_MULTIPLIER:
                # Определяем направление свечи (зеленая или красная)
                is_green = float(current_kline[4]) >= float(current_kline[1])
                return {
                    "symbol": symbol,
                    "ratio": ratio,
                    "current_turnover": current_turnover,
                    "avg_turnover": avg_turnover,
                    "price": current_close_price,
                    "is_green": is_green,
                    "timestamp": int(current_kline[0])
                }
            return None
            
    except Exception as e:
        return None

# Глобальные переменные
IS_SCANNING = False
LAST_SCAN_TIME = 0.0
LAST_CYCLE_DURATION = 0.0
MONITORED_COINS = 0

def update_config_file(var_name: str, new_value):
    """Обновляет значение переменной в config.py, сохраняя комментарии."""
    try:
        with open("config.py", "r", encoding="utf-8") as f:
            content = f.read()
        
        val_str = str(new_value) if not isinstance(new_value, str) else f'"{new_value}"'
        # Ищем `VAR_NAME = VALUE` и заменяем только VALUE
        pattern = rf"^({var_name}\s*=\s*)[^\s#]+(.*)$"
        new_content = re.sub(pattern, rf"\g<1>{val_str}\g<2>", content, flags=re.MULTILINE)
        
        with open("config.py", "w", encoding="utf-8") as f:
            f.write(new_content)
    except Exception as e:
        logger.error(f"Ошибка сохранения {var_name} в config.py: {e}")

async def set_telegram_menu_commands(session: aiohttp.ClientSession, token: str):
    url = f"https://api.telegram.org/bot{token}/setMyCommands"
    commands = [
        {"command": "start", "description": "Запустить мониторинг"},
        {"command": "stop", "description": "Остановить сканирование"},
        {"command": "settings", "description": "Показать текущие настройки"},
        {"command": "help", "description": "Инструкция по настройкам"},
        {"command": "set_vol", "description": "Изменить множитель объема"},
        {"command": "set_can", "description": "Изменить кол-во свечей"},
        {"command": "set_int", "description": "Изменить частоту проверок"},
        {"command": "set_tf", "description": "Изменить таймфрейм свечей"}
    ]
    try:
        await session.post(url, json={"commands": commands})
    except Exception as e:
        logger.error(f"Ошибка установки меню команд: {e}")

async def poll_telegram(session: aiohttp.ClientSession):
    global IS_SCANNING
    offset = 0
    token = config.TELEGRAM_TOKEN
    
    if not token or token == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        logger.warning("Telegram Token не настроен. Команды отключены.")
        return
        
    await set_telegram_menu_commands(session, token)
        
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    
    while True:
        try:
            params = {"offset": offset, "timeout": 30}
            async with session.get(url, params=params, timeout=35) as response:
                if response.status == 200:
                    data = await response.json()
                    for update in data.get("result", []):
                        offset = update["update_id"] + 1
                        message = update.get("message", {})
                        text = message.get("text", "")
                        
                        if text == "/start":
                            IS_SCANNING = True
                            await send_telegram_message("✅ <b>Мониторинг запущен!</b>\nБот начал сканирование объемов.")
                            logger.info("Команда /start: мониторинг запущен.")
                        elif text == "/stop":
                            IS_SCANNING = False
                            await send_telegram_message("⏸️ <b>Мониторинг приостановлен.</b>\nДля возобновления напишите /start.")
                            logger.info("Команда /stop: мониторинг приостановлен.")
                        elif text in ["/check", "/status", "/settings", "/help"]:
                            status_text = "🟢 <b>Работает</b>" if IS_SCANNING else "🔴 <b>Остановлен</b>"
                            reply = (
                                f"📊 <b>Статус бота:</b> {status_text}\n"
                                f"⏱ Последний цикл: {LAST_CYCLE_DURATION:.2f} сек\n"
                                f"🪙 Мониторится монет: {MONITORED_COINS}\n\n"
                                f"⚙️ <b>Текущие настройки:</b>\n"
                                f"Множитель объема: <b>x{config.VOLUME_MULTIPLIER}</b>\n"
                                f"Кол-во свечей: <b>{config.LOOKBACK_CANDLES}</b>\n"
                                f"Таймфрейм: <b>{config.TIMEFRAME} мин</b>\n"
                                f"Интервал (сек): <b>{config.SCAN_INTERVAL_SEC}</b>\n\n"
                                f"🛠 <b>Как изменить настройки:</b>\n"
                                f"Отправьте команду и новое значение через пробел:\n"
                                f"🔹 <code>/set_vol 15.5</code> — изменить множитель объема\n"
                                f"🔹 <code>/set_can 30</code> — изменить количество свечей\n"
                                f"🔹 <code>/set_int 45</code> — изменить интервал опроса\n"
                                f"🔹 <code>/set_tf 60</code> — таймфрейм (1,3,5,15,30,60,120,240,360,720)"
                            )
                            await send_telegram_message(reply)
                        elif text.startswith("/set_vol"):
                            try:
                                val = float(text.split()[1])
                                config.VOLUME_MULTIPLIER = val
                                update_config_file("VOLUME_MULTIPLIER", val)
                                await send_telegram_message(f"✅ Множитель объема изменен и **сохранен** на: <b>x{val}</b>")
                                logger.info(f"Множитель объема изменен на {val}")
                            except:
                                await send_telegram_message("❌ Неверный формат. Используйте: `/set_vol 15.5`")
                        elif text.startswith("/set_can"):
                            try:
                                val = int(text.split()[1])
                                config.LOOKBACK_CANDLES = val
                                update_config_file("LOOKBACK_CANDLES", val)
                                await send_telegram_message(f"✅ Количество свечей изменено и **сохранено** на: <b>{val}</b>")
                                logger.info(f"Количество свечей изменено на {val}")
                            except:
                                await send_telegram_message("❌ Неверный формат. Используйте: `/set_can 30`")
                        elif text.startswith("/set_int"):
                            try:
                                val = int(text.split()[1])
                                config.SCAN_INTERVAL_SEC = val
                                update_config_file("SCAN_INTERVAL_SEC", val)
                                await send_telegram_message(f"✅ Интервал сканирования изменен и **сохранен** на: <b>{val} сек</b>")
                                logger.info(f"Интервал сканирования изменен на {val}")
                            except:
                                await send_telegram_message("❌ Неверный формат. Используйте: `/set_int 30`")
                        elif text.startswith("/set_tf"):
                            VALID_TIMEFRAMES = ["1", "3", "5", "15", "30", "60", "120", "240", "360", "720"]
                            try:
                                val = text.split()[1]
                                if val not in VALID_TIMEFRAMES:
                                    await send_telegram_message(
                                        f"❌ Недопустимый таймфрейм: <b>{val}</b>\n"
                                        f"Допустимые значения: <code>{', '.join(VALID_TIMEFRAMES)}</code>"
                                    )
                                else:
                                    config.TIMEFRAME = val
                                    update_config_file("TIMEFRAME", val)
                                    await send_telegram_message(
                                        f"✅ Таймфрейм изменен и сохранен на: <b>{val} мин</b>"
                                    )
                                    logger.info(f"Таймфрейм изменен на {val}")
                            except:
                                await send_telegram_message(
                                    f"❌ Неверный формат. Используйте: <code>/set_tf 60</code>\n"
                                    f"Допустимые значения: <code>{', '.join(VALID_TIMEFRAMES)}</code>"
                                )
                            
        except Exception as e:
            if config.VERBOSE:
                logger.error(f"Ошибка при получении обновлений Telegram: {e}")
            await asyncio.sleep(5)
            
        await asyncio.sleep(1)

async def main():
    logger.info("🚀 Запуск Volume Bot v1...")
    
    # Запуск сервера для UptimeRobot (нужно для бесплатного Replit)
    keep_alive()
    
    logger.info(f"Настройки: x{config.VOLUME_MULTIPLIER} объем за {config.LOOKBACK_CANDLES} минут.")
    
    global LAST_SCAN_TIME, LAST_CYCLE_DURATION, MONITORED_COINS, IS_SCANNING

    last_alert_time = load_sent_alerts()
    logger.info(f"Загружено {len(last_alert_time)} записей дедупликации.")

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
        # Запускаем опрос Telegram
        asyncio.create_task(poll_telegram(session))
        logger.info("Ожидание команды /start в Telegram...")
        
        while True:
            if not IS_SCANNING:
                await asyncio.sleep(1)
                continue
                
            start_time = time.time()
            LAST_SCAN_TIME = start_time
            
            symbols = await fetch_tickers(session)
            if not symbols:
                logger.warning("Не удалось получить список монет. Пауза 5с...")
                await asyncio.sleep(5)
                continue
                
            MONITORED_COINS = len(symbols)
            logger.info(f"🔄 Сканирование {MONITORED_COINS} монет...")
            
            # Запускаем запросы конкурентно (по всем монетам одновременно)
            tasks = [check_volume_spike_fixed(session, symbol) for symbol in symbols]
            results = await asyncio.gather(*tasks)
            
            spikes = [r for r in results if r is not None]
            
            # Очистка устаревших записей раз в цикл
            last_alert_time = cleanup_sent_alerts(last_alert_time)

            sent_any = False
            for spike in spikes:
                symbol = spike["symbol"]
                ts = spike["timestamp"]

                # Пропустить, если уже отправляли алерт для этой свечи
                if last_alert_time.get(symbol, 0) >= ts:
                    continue

                last_alert_time[symbol] = ts
                sent_any = True

                direction_emoji = "🟢 LONG" if spike["is_green"] else "🔴 SHORT"

                tv_link = f"https://www.tradingview.com/chart/?symbol=BYBIT:{symbol}.P"
                msg = (
                    f"⚠️ <b>АНОМАЛЬНЫЙ ОБЪЕМ</b> ⚠️\n\n"
                    f"💎 <b>{symbol}</b>\n"
                    f"📈 Рост объема: <b>{spike['ratio']:.1f}x</b>\n"
                    f"💲 Цена: {spike['price']}\n"
                    f"📊 Оборот свечи: {spike['current_turnover'] / 1000:.1f}k USDT\n"
                    f"📉 Средний оборот: {spike['avg_turnover'] / 1000:.1f}k USDT\n"
                    f"🧭 Направление: {direction_emoji}\n\n"
                    f"📉 <a href=\"{tv_link}\">График на TradingView</a>"
                )

                logger.info(f"🔥 Всплеск! {symbol} x{spike['ratio']:.1f}")
                await send_signal(msg)

            # Сохранить состояние дедупликации на диск после каждого цикла
            if sent_any:
                save_sent_alerts(last_alert_time)
                
            elapsed = time.time() - start_time
            LAST_CYCLE_DURATION = elapsed
            sleep_time = config.SCAN_INTERVAL_SEC - elapsed
            
            if sleep_time > 0:
                if config.VERBOSE:
                    logger.info(f"✅ Цикл завершен за {elapsed:.2f}с. Ждем {sleep_time:.2f}с...")
                await asyncio.sleep(sleep_time)
            else:
                logger.warning(f"⚠️ Цикл занял слишком много времени: {elapsed:.2f}с!")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем.")
