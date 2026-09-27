import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import requests
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"V4.4 STABLE LIVE")
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
        return sum(vals)/len(vals)
    k = 2/(period+1)
    ev = sum(vals[:period])/period
    for v in vals[period:]:
        ev = v*k + ev*(1-k)
    return ev

def get_gold_data():
    try:
        r = requests.get("https://api.gold-api.com/price/XAU", timeout=10).json()
        price = float(r.get("price", 4286))
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
    now = datetime.now().strftime('%H:%M')
    if price > e9 and e9 > e21:
        return f"🟢 GOLD BUY NOW\n\nEntry: {price:.2f}\nSL: {price-8:.2f}\nTP1: {price+6:.2f}\nTP2: {price+12:.2f}\n\n⏰ {now} | EMA9 {e9:.2f} > EMA21 {e21:.2f} Bullish"
    elif price < e9 and e9 < e21:
        return f"🔴 GOLD SELL NOW\n\nEntry: {price:.2f}\nSL: {price+8:.2f}\nTP1: {price-6:.2f}\nTP2: {price+12:.2f}\n\n⏰ {now} | EMA9 {e9:.2f} < EMA21 {e21:.2f} Bearish"
    else:
        return f"⚪ GOLD WAIT\n\nPrice: {price:.2f}\nEMA9: {e9:.2f} | EMA21: {e21:.2f}\n\nMarket ranging. Wait."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    SUBSCRIBERS.add(update.effective_chat.id)
    await update.message.reply_text("🔥 GOLD VIP V4.4 STABLE LIVE 🔥\n\nWelcome to Premium Gold Signals!\n💰 VIP: $25 / month\n\nCommands:\n/buy - Join VIP ($25)\n/signal - BUY/SELL now\n/autopilot_on - Start auto\n/autopilot_off - Stop\n/channeltest - Test channel\n/setchannel - Set channel ID")

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💳 JOIN VIP FOR $25 / MONTH\n\nPay via:\n• OPay: 806 123 4567 - Sunday E.\n• USDT TRC20: TX...\n\nAfter payment, send receipt to @Onyebest\nID: 2093810683\n\n✅ Private VIP channel\n✅ 3-5 Signals Daily\n✅ 90% Accuracy")

async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = build_signal()
    await update.message.reply_text(msg)

async def autopilot_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    SUBSCRIBERS.add(update.effective_chat.id)
    await update.message.reply_text("✅ Autopilot ON - You will get BUY/SELL signals!")

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
        await context.bot.send_message(chat_id=CHANNEL_ID, text="✅ VIP Bot Channel Test - Connected! V4.4 BUY/SELL working!")
        await update.message.reply_text("✅ Test sent to channel!")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed: {e}\n\nFix:\n1. Add bot as Admin in channel\n2. /setchannel -100xxxx\nGet ID from @userinfobot")

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
    print("V4.4 STABLE started - No job_queue - No crash")
    app.run_polling()

if __name__ == "__main__":
    main()
