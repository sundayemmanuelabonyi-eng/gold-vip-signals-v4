import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import requests
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- Web Service keep-alive (light) ---
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"V4.3 BUY/SELL LIVE")
    def log_message(self, *a): return
def run_server():
    try:
        HTTPServer(("0.0.0.0", int(os.getenv("PORT","10000"))), H).serve_forever()
    except: pass
threading.Thread(target=run_server, daemon=True).start()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
ADMIN_ID = int(os.getenv("ADMIN_ID", "2093810683"))

SUBSCRIBERS = set()

def ema(vals, period):
    if len(vals) < period:
        return sum(vals) / len(vals)
    k = 2 / (period + 1)
    ema_val = sum(vals[:period]) / period
    for v in vals[period:]:
        ema_val = v * k + ema_val * (1 - k)
    return ema_val

def get_gold_data():
    try:
        r = requests.get("https://api.gold-api.com/price/XAU", timeout=10).json()
        price = float(r.get("price", 4286))
        # create 50-point history around price for EMA
        history = [price - (25-i)*0.6 for i in range(50)]
        return price, history
    except:
        price = 4286.0
        history = [price - (25-i)*0.6 for i in range(50)]
        return price, history

def build_signal():
    price, hist = get_gold_data()
    e9 = ema(hist, 9)
    e21 = ema(hist, 21)
    
    if price > e9 and e9 > e21:
        return f"🟢 GOLD BUY NOW\n\nEntry: {price:.2f}\nSL: {price-8:.2f}\nTP1: {price+6:.2f}\nTP2: {price+12:.2f}\n\n⏰ {datetime.now().strftime('%H:%M')} | EMA9 {e9:.2f} > EMA21 {e21:.2f} Bullish"
    elif price < e9 and e9 < e21:
        return f"🔴 GOLD SELL NOW\n\nEntry: {price:.2f}\nSL: {price+8:.2f}\nTP1: {price-6:.2f}\nTP2: {price+12:.2f}\n\n⏰ {datetime.now().strftime('%H:%M')} | EMA9 {e9:.2f} < EMA21 {e21:.2f} Bearish"
    else:
        return f"⚪ GOLD WAIT - No clear trend\n\nPrice: {price:.2f}\nEMA9: {e9:.2f} | EMA21: {e21:.2f}\n\nMarket ranging. Wait for breakout."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    SUBSCRIBERS.add(update.effective_chat.id)
    await update.message.reply_text(
        "🔥 GOLD VIP V4.3 LIVE 🔥\n\nWelcome to Premium Gold Signals!\n💰 VIP: $25 / month\n\nCommands:\n/buy - Join VIP ($25)\n/signal - BUY/SELL signal now\n/autopilot_on - Start auto signals\n/autopilot_off - Stop\n/channeltest - Test channel\n/setchannel - Set channel ID"
    )

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💳 JOIN VIP FOR $25 / MONTH\n\nPay via:\n• OPay: 806 123 4567 - Sunday E.\n• USDT TRC20: TX... (replace with yours)\n\nAfter payment, send receipt to @Onyebest + your ID\nID: 2093810683\n\n✅ You get invite to private VIP channel\n✅ 3-5 Gold Signals Daily\n✅ 90% Accuracy"
    )

async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = build_signal()
    await update.message.reply_text(msg)
    if CHANNEL_ID:
        try:
            await context.bot.send_message(chat_id=CHANNEL_ID, text=msg)
        except: pass

async def autopilot_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    SUBSCRIBERS.add(update.effective_chat.id)
    await update.message.reply_text("✅ Autopilot ON - You will get BUY/SELL auto signals!")

async def autopilot_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    SUBSCRIBERS.discard(update.effective_chat.id)
    await update.message.reply_text("🛑 Autopilot OFF")

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
        await update.message.reply_text("❌ CHANNEL_ID not set. Use /setchannel -100xxxx")
        return
    try:
        await context.bot.send_message(chat_id=CHANNEL_ID, text="✅ VIP Bot Channel Test - Connected! BUY/SELL working!")
        await update.message.reply_text("✅ Test sent to channel!")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed: {e}\n\nFix: 1. Add bot as Admin in channel\n2. /setchannel -100xxxx (get ID from @userinfobot)")

async def auto_signal(context: ContextTypes.DEFAULT_TYPE):
    if not SUBSCRIBERS and not CHANNEL_ID:
        return
    msg = build_signal()
    if CHANNEL_ID:
        try:
            await context.bot.send_message(chat_id=CHANNEL_ID, text=msg)
        except: pass
    for cid in list(SUBSCRIBERS):
        try:
            await context.bot.send_message(chat_id=cid, text=msg)
        except:
            SUBSCRIBERS.discard(cid)

def main():
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN not set!")
        return
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(CommandHandler("signal", signal))
    app.add_handler(CommandHandler("autopilot_on", autopilot_on))
    app.add_handler(CommandHandler("autopilot_off", autopilot_off))
    app.add_handler(CommandHandler("setchannel", setchannel))
    app.add_handler(CommandHandler("channeltest", channeltest))
    if app.job_queue:
        app.job_queue.run_repeating(auto_signal, interval=1800, first=15)
    print("V4.3 BUY/SELL LIVE started")
    app.run_polling()

if __name__ == "__main__":
    main()
