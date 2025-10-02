import os
import asyncio
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import requests

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Настройки мониторинга
PRICE_THRESHOLD_PERCENT = 3      # Порог изменения цены (%)
VOLUME_THRESHOLD_PERCENT = 50    # Порог изменения объёма (%)
CHECK_INTERVAL = 60               # Проверка каждые 60 секунд
MIN_VOLUME_USDT = 50000           # Минимальный объём для отслеживания (USDT)

previous_data = {}

# Команды бота
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Бот запущен и отслеживает значительные пампы/дампы на Binance ✅"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Бот мониторит криптовалюту на Binance и присылает уведомления при резких изменениях цены и объёма.\n"
        "Используйте /start для запуска."
    )

# Получаем все торговые пары с USDT
def fetch_all_symbols():
    url = "https://api.binance.com/api/v3/ticker/24hr"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        coins = []
        for d in data:
            if 'symbol' in d and d['symbol'].endswith("USDT"):
                coins.append(d['symbol'])
        return coins
    except Exception as e:
        print("Ошибка при получении монет:", e)
        return []

# Получаем цену и объём конкретной монеты
def fetch_price_volume(symbol):
    url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}"
    try:
        data = requests.get(url, timeout=5).json()
        price = float(data['lastPrice'])
        volume = float(data['quoteVolume'])
        return price, volume
    except:
        return None, None

# Мониторинг цен и объёмов
async def monitor():
    bot = Bot(token=TELEGRAM_TOKEN)
    global previous_data

    coins = fetch_all_symbols()
    if not coins:
        print("⚠️ Не удалось получить список монет с Binance. Проверьте соединение или API.")
        return
    print(f"Отслеживаем {len(coins)} монет на Binance...")

    while True:
        for coin in coins:
            price, volume = fetch_price_volume(coin)
            if price is None or volume is None:
                continue
            if volume < MIN_VOLUME_USDT:
                continue  # пропускаем мелкие объёмы

            if coin in previous_data:
                old_price, old_volume = previous_data[coin]

                # Проверка резкого изменения цены
                price_change = ((price - old_price) / old_price) * 100
                if abs(price_change) >= PRICE_THRESHOLD_PERCENT:
                    direction = "📈 Памп" if price_change > 0 else "📉 Дамп"
                    await bot.send_message(
                        chat_id=CHAT_ID,
                        text=f"{direction}: {coin} изменилась на {price_change:.2f}%\nСейчас: {price:.2f}$"
                    )

                # Проверка резкого изменения объёма
                volume_change = ((volume - old_volume) / old_volume) * 100
                if abs(volume_change) >= VOLUME_THRESHOLD_PERCENT:
                    await bot.send_message(
                        chat_id=CHAT_ID,
                        text=f"💥 Резкое изменение объёма: {coin} объём изменился на {volume_change:.2f}%\nСейчас: {volume:.2f} USDT"
                    )

            previous_data[coin] = (price, volume)

        await asyncio.sleep(CHECK_INTERVAL)

# Запуск бота
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))

    # Запуск мониторинга параллельно
    app.job_queue.run_repeating(lambda ctx: asyncio.create_task(monitor()), interval=CHECK_INTERVAL, first=5)

    print("Бот запущен и ждёт команд...")
    app.run_polling()
