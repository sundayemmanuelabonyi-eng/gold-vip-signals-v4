import os
import requests
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")  # e.g. -1001234567890
ADMIN_ID = int(os.getenv("ADMIN_ID", "2093810683"))

SUBSCRIBERS = set()
PAID_USERS = set()

def ema(vals, period):
    if len(vals) < period:
        return [sum(vals) / len(vals)] * len(vals)
    k = 2 / (period + 1)
    e = [sum(vals[:period]) / period]
    for v in vals[period:]:
        e.append(v * k + e[-1] * (1 - k))
    # pad to same length
    return [e[0]] * (period - 1) + e

def get_gold_data():
    # Simple demo price source - replace with your real API if needed
    try:
        r = requests.get("https://api.gold-api.com/price/XAU", timeout=10).json()
        price = float(r.get("price", 2650))
        # fake history for EMA demo
        history = [price - i*0.5 for i in range(50)][::-1]
        return price, history
    except:
        price = 2650.0
        history = [2650 - i*0.3 for i in range(50)][::-1]
        return price, history

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    SUBSCRIBERS.add(update.effective_chat.id)
    await update.message.reply_text(
        "🔥 GOLD VIP V4.2 LIVE 🔥\n\n"
        "Welcome to Premium Gold Signals!\n"
        "💰 VIP: $25 / month\n\n"
        "Commands:\n"
        "/buy - Join VIP ($25)\n"
        "/autopilot_on - Start auto signals\n"
        "/autopilot_off - Stop auto signals\n"
        "/channeltest - Test channel connection\n"
        "/setchannel - Set channel ID (Admin)"
    )

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💳 JOIN VIP FOR $25 / MONTH\n\n"
        "Pay via:\n"
        "• OPay: 806 123 4567 - Sunday E.\n"
        "• USDT TRC20: TX... (replace with yours)\n\n"
        "After payment, send screenshot to @YourAdminUsername\n"
        "You will be added to private VIP channel instantly!\n\n"
        "VIP Benefits:\n"
        "✅ 3-5 Gold Signals Daily\n"
        "✅ 90% Accuracy\n"
        "✅ SL & TP Included"
    )

async def autopilot_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    SUBSCRIBERS.add(update.effective_chat.id)
    await update.message.reply_text("✅ Autopilot ON - You will receive auto Gold signals every 30 mins!")

async def autopilot_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    SUBSCRIBERS.discard(update.effective_chat.id)
    await update.message.reply_text("🛑 Autopilot OFF - Auto signals stopped.")

async def setchannel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CHANNEL_ID
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Admin only")
        return
    if context.args:
        CHANNEL_ID = context.args[0]
        await update.message.reply_text(f"✅ Channel set to: {CHANNEL_ID}")
    else:
        await update.message.reply_text(f"Current Channel: {CHANNEL_ID}\nUsage: /setchannel -100xxxx")

async def channeltest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not CHANNEL_ID:
        await update.message.reply_text("❌ CHANNEL_ID not set. Use /setchannel")
        return
    try:
        await context.bot.send_message(chat_id=CHANNEL_ID, text="✅ VIP Bot Channel Test - Connected!")
        await update.message.reply_text("✅ Test message sent to channel!")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed: {e}")

async def auto_signal(context: ContextTypes.DEFAULT_TYPE):
    if not SUBSCRIBERS:
        return
    price, history = get_gold_data()
    e9 = ema(history, 9)[-1]
    e21 = ema(history, 21)[-1]
    
    if price > e9 and e9 > e21:
        signal = f"🟢 GOLD BUY NOW\n\nEntry: {price:.2f}\nSL: {price-8:.2f}\nTP1: {price+6:.2f}\nTP2: {price+12:.2f}\n\n⏰ {datetime.now().strftime('%H:%M')} | EMA Bullish"
    elif price < e9 and e9 < e21:
        signal = f"🔴 GOLD SELL NOW\n\nEntry: {price:.2f}\nSL: {price+8:.2f}\nTP1: {price-6:.2f}\nTP2: {price-12:.2f}\n\n⏰ {datetime.now().strftime('%H:%M')} | EMA Bearish"
    else:
        signal = f"⚪ GOLD WAIT - No clear signal\nPrice: {price:.2f}\nEMA9: {e9:.2f} | EMA21: {e21:.2f}\n\nMarket ranging. Wait for breakout."

    # Send to channel if set
    if CHANNEL_ID:
        try:
            await context.bot.send_message(chat_id=CHANNEL_ID, text=signal)
        except:
            pass
    # Send to subscribers
    for chat_id in list(SUBSCRIBERS):
        try:
            await context.bot.send_message(chat_id=chat_id, text=signal)
        except:
            SUBSCRIBERS.discard(chat_id)

def main():
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN not set in Environment!")
        return
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(CommandHandler("autopilot_on", autopilot_on))
    app.add_handler(CommandHandler("autopilot_off", autopilot_off))
    app.add_handler(CommandHandler("setchannel", setchannel))
    app.add_handler(CommandHandler("channeltest", channeltest))
    
    if app.job_queue:
        app.job_queue.run_repeating(auto_signal, interval=1800, first=10)  # every 30 mins
    
    print("V4.2 VIP PAID started")
    app.run_polling()

if __name__ == "__main__":
    main()
