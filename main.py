import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import requests
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- 3 lines to keep Web Service alive (light & fast) ---
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, *a):
        return

def run_server():
    try:
        port = int(os.getenv("PORT", "10000"))
        HTTPServer(("0.0.0.0", port), H).serve_forever()
    except:
        pass

threading.Thread(target=run_server, daemon=True).start()
# --- end ---

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
ADMIN_ID = int(os.getenv("ADMIN_ID", "2093810683"))

SUBSCRIBERS = set()

def get_gold_price():
    try:
        r = requests.get("https://api.gold-api.com/price/XAU", timeout=10).json()
        return float(r.get("price", 2650))
    except:
        return 2650.0

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    SUBSCRIBERS.add(update.effective_chat.id)
    await update.message.reply_text(
        "🔥 GOLD VIP V4.2 LIVE 🔥\n\nWelcome to Premium Gold Signals!\n💰 VIP: $25 / month\n\nCommands:\n/buy - Join VIP ($25)\n/signal - Get instant signal\n/autopilot_on - Start auto signals\n/autopilot_off - Stop auto signals\n/channeltest - Test channel"
    )

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💳 JOIN VIP FOR $25 / MONTH\n\nPay via:\n• OPay: 806 123 4567 - Sunday E.\n• USDT TRC20: TX... (replace)\n\nAfter payment, send screenshot to admin\nYou will be added to private VIP channel!\n\nVIP Benefits:\n✅ 3-5 Gold Signals Daily\n✅ 90% Accuracy\n✅ SL & TP Included")

async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    price = get_gold_price()
    msg = f"🟢 GOLD SIGNAL\n\nEntry: {price:.2f}\nSL: {price-8:.2f}\nTP1: {price+6:.2f}\nTP2: {price+12:.2f}\n\n⏰ {datetime.now().strftime('%H:%M')} | Live Price"
    await update.message.reply_text(msg)
    if CHANNEL_ID:
        try:
            await context.bot.send_message(chat_id=CHANNEL_ID, text=msg)
        except:
            pass

async def autopilot_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    SUBSCRIBERS.add(update.effective_chat.id)
    await update.message.reply_text("✅ Autopilot ON")

async def autopilot_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    SUBSCRIBERS.discard(update.effective_chat.id)
    await update.message.reply_text("🛑 Autopilot OFF")

async def channeltest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not CHANNEL_ID:
        await update.message.reply_text("❌ CHANNEL_ID not set")
        return
    try:
        await context.bot.send_message(chat_id=CHANNEL_ID, text="✅ VIP Bot Channel Test - Connected!")
        await update.message.reply_text("✅ Test sent!")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed: {e}")

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
    app.add_handler(CommandHandler("channeltest", channeltest))
    print("V4.2 VIP PAID started")
    app.run_polling()

if __name__ == "__main__":
    main()
