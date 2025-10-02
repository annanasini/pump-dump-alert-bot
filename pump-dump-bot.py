# pump_dump_alert_bot.py
import asyncio
import json
import time
from collections import deque, defaultdict

import aiohttp
import numpy as np
from telegram import Bot

# ----------------- Настройки -----------------
TELEGRAM_TOKEN = "ВАШ_TELEGRAM_BOT_TOKEN"
CHAT_ID = "ВАШ_CHAT_ID_ИЛИ_ЮЗЕР_ID"  # куда слать уведомления
SYMBOLS = ["btcusdt", "ethusdt", "solusdt"]  # маленькими буквами (binance stream)
VOLUME_WINDOW_MINUTES = 10  # окно для среднего объема
ALERT_MULTIPLIER = 6.0  # порог: если объем в минуту больше этого множителя от среднего -> ворнинг
MIN_TRADE_VOLUME = 0.001  # для фильтрации мелких сделок (в единицах токена; настройте индивидуально)
DEBOUNCE_SECONDS = 120  # не спамить: для одного символа не больше 1 алерта за N секунд
# ---------------------------------------------

bot = Bot(token=TELEGRAM_TOKEN)

# храним историю объёмов по минутам для каждого символа
volume_history = defaultdict(lambda: deque(maxlen=VOLUME_WINDOW_MINUTES))
last_alert_time = defaultdict(lambda: 0)

async def send_telegram(text: str):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=text)
    except Exception as e:
        print("Telegram send error:", e)

def minute_bucket(ts):
    return int(ts // 60)

async def handle_trade(symbol, trade):
    """
    trade: dict from binance e.g. includes 'q' - quoteQty, 'p' - price, 'q' sometimes is quantity?
    We'll use 'q' or 'v' depending on stream; adjust as needed.
    """
    # For aggTrade stream fields: p (price), q (quantity), T (timestamp)
    price = float(trade.get("p", 0))
    qty = float(trade.get("q", 0))
    ts = int(trade.get("T", time.time() * 1000)) / 1000.0
    # filter tiny trades
    if qty < MIN_TRADE_VOLUME:
        return

    cur_min = minute_bucket(ts)
    # ensure volume_history has an entry for current minute
    if not volume_history[symbol] or volume_history[symbol][-1][0] != cur_min:
        # append new minute bucket: (minute, volume)
        volume_history[symbol].append((cur_min, qty))
    else:
        # add to existing last minute
        m, v = volume_history[symbol].pop()
        volume_history[symbol].append((m, v + qty))

    # compute average over available windows (skip current minute to avoid lookahead)
    vols = [v for (m, v) in list(volume_history[symbol])[:-1]]  # exclude current minute
    if len(vols) < 3:
        return  # ещё мало данных

    avg = float(np.mean(vols))
    cur_vol = volume_history[symbol][-1][1]
    multiplier = cur_vol / (avg + 1e-9)

    # price move detection could be added here (compare to last price)
    if multiplier >= ALERT_MULTIPLIER:
        now = time.time()
        if now - last_alert_time[symbol] > DEBOUNCE_SECONDS:
            last_alert_time[symbol] = now
            msg = (f"⚠️ Всплеск объёма для {symbol.upper()}!\n"
                   f"Текущий минутный объём: {cur_vol:.6f}\n"
                   f"Средний за {len(vols)} мин: {avg:.6f} (x{multiplier:.2f})\n"
                   f"Цена: {price}\n"
                   f"Время: {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(ts))} UTC\n\n"
                   "Это оповещение о риске — возможно памп/дамп. Проверьте orderbook и соцсети.")
            await send_telegram(msg)
            print("Alert sent:", msg)

async def binance_aggtrade_listener(symbol):
    stream = f"wss://stream.binance.com:9443/ws/{symbol}@aggTrade"
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(stream, timeout=30) as ws:
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            await handle_trade(symbol, data)
                        elif msg.type == aiohttp.WSMsgType.CLOSED:
                            break
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            break
        except Exception as e:
            print(f"WS error for {symbol}: {e}. Reconnecting in 3s...")
            await asyncio.sleep(3)

async def main():
    tasks = []
    for s in SYMBOLS:
        tasks.append(asyncio.create_task(binance_aggtrade_listener(s)))
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
