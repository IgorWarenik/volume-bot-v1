"""
Volume Bot v1 - Настройки (Шаблон)
"""

# Настройки Telegram
TELEGRAM_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN_HERE"  # Замените на токен от BotFather
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID_HERE"           # Замените на ваш Chat ID

# Настройки стратегии
VOLUME_MULTIPLIER = 10.0      # Сигнал, если объем в X раз больше среднего
LOOKBACK_CANDLES = 20         # За сколько предыдущих свечей считать средний объем (без учета текущей)
TIMEFRAME = "1"               # Таймфрейм (1 минута)
SCAN_INTERVAL_SEC = 60        # Как часто опрашивать биржу (раз в минуту)

# Фильтры монет
MIN_TURNOVER_24H = 1_000_000  # Минимальный суточный оборот в $ (отсеиваем неликвид)

# Черный список (монеты, которые бот будет игнорировать)
BLACKLIST = [
    "BTCUSDT", "ETHUSDT", "USDCUSDT", "USDTUSDT" 
]

# Логирование
VERBOSE = True
