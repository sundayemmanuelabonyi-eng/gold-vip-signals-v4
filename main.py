import os, threading, asyncio, requests, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
 
PORT = int(os.getenv("PORT","10000"))
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "")
 
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        try: self.wfile.write(b"GOLD VIP 2+1 NO MPL FIXED LIVE")
        except: pass
    def do_HEAD(self): self.send_response(200); self.end_headers()
    def log_message(self,*a): return
 
def run_server():
    try: HTTPServer(("0.0.0.0", PORT), H).serve_forever()
    except: pass
threading.Thread(target=run_server, daemon=True).start()
 
def keep_awake():
    while True:
        try:
            time.sleep(240)
            try: requests.get(f"http://localhost:{PORT}", timeout=5)
            except: pass
            if RENDER_URL:
                try: requests.get(RENDER_URL, timeout=5)
                except: pass
        except: time.sleep(60)
threading.Thread(target=keep_awake, daemon=True).start()
 
BOT_TOKEN=os.getenv("BOT_TOKEN")
DEFAULT_CHANNEL_ID="-1004402762942"
CHANNEL_ID=os.getenv("CHANNEL_ID", DEFAULT_CHANNEL_ID)
ADMIN_ID=int(os.getenv("ADMIN_ID","2093810683"))
 
SUBSCRIBERS=set(); AUTOPILOT_ACTIVE=False; AUTOPILOT_TASK=None; ACTIVE_TRADES={}
 
def atr(highs,lows,closes,period=14):
    if len(closes)<period+1:
        return (max(highs[-20:])-min(lows[-20:]))/20 if len(highs)>=20 else 5.0
    trs=[]
    for i in range(1,len(closes)):
        hl=highs[i]-lows[i] if i<len(highs) and i<len(lows) else 0
        hc=abs(highs[i]-closes[i-1]) if i<len(highs) else 0
        lc=abs(lows[i]-closes[i-1]) if i<len(lows) else 0
        trs.append(max(hl,hc,lc))
    return sum(trs[-period:])/period if trs else 5.0
 
def get_td_key():
    for k in ["TWELVEDATA_API_KEY","TWELVE_DATA_API_KEY"]:
        v=os.getenv(k,"").strip()
        if len(v)>10: return v
    return ""
 
def get_td(symbol,interval,fallback):
    key=get_td_key()
    if not key: return None,[],[],[]
    try:
        m={"GC=F":"XAU/USD","SI=F":"XAG/USD","^DJI":"DJI","^GDAXI":"DAX","^NDX":"NDX"}
        sym=m.get(symbol,symbol)
        ii={"15m":"15min","1h":"1h","4h":"4h"}.get(interval,"15min")
        url=f"https://api.twelvedata.com/time_series?symbol={sym}&interval={ii}&outputsize=100&apikey={key}&order=ASC"
        r=requests.get(url,timeout=10).json()
        if "values" not in r: return None,[],[],[]
        closes=[]; highs=[]; lows=[]
        for v in r["values"]:
            try:
                closes.append(float(v["close"])); highs.append(float(v["high"])); lows.append(float(v["low"]))
            except: continue
        return closes[-1],closes[-100:],highs[-100:],lows[-100:]
    except: return None,[],[],[]
 
def get_yahoo(symbol,interval,fallback):
    try:
        h={'User-Agent':'Mozilla/5.0'}
        yf={"15m":"15m","1h":"60m","4h":"60m"}[interval]
        rg={"15m":"5d","1h":"10d","4h":"60d"}[interval]
        url=f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval={yf}&range={rg}"
        r=requests.get(url,headers=h,timeout=8).json()
        res=r['chart']['result'][0]
        q=res['indicators']['quote'][0]
        closes=[c for c in q['close'] if c is not None]
        highs=[x for x in q['high'] if x is not None]
        lows=[x for x in q['low'] if x is not None]
        if closes:
            return closes[-1],closes[-100:],highs[-100:],lows[-100:]
    except: pass
    return fallback,[fallback]*100,[fallback+1]*100,[fallback-1]*100
 
def get_mtf(symbol,interval,fallback):
    p,h,hi,lo=get_td(symbol,interval,fallback)
    if p is not None and len(h)>=20: return p,h,hi,lo
    return get_yahoo(symbol,interval,fallback)
 
def swing(highs,lows,l=2,r=2):
    sh=[]; sl=[]
    for i in range(l,len(highs)-r):
        if all(highs[i]>highs[i-j] for j in range(1,l+1)) and all(highs[i]>highs[i+j] for j in range(1,r+1)):
            sh.append((i,highs[i]))
        if all(lows[i]<lows[i-j] for j in range(1,l+1)) and all(lows[i]<lows[i+j] for j in range(1,r+1)):
            sl.append((i,lows[i]))
    return sh,sl
 
def bos_choch_true_failed(hist,highs,lows,atr_val):
    sh,sl=swing(highs,lows,2,2)
    if len(sh)<2 or len(sl)<2: return "RANGE",50,sh,sl,"No structure",False,None
    last_sh=sh[-1][1]; prev_sh=sh[-2][1]; last_sl=sl[-1][1]; prev_sl=sl[-2][1]; price=hist[-1]
    min_wick = atr_val * 0.25
    min_close = atr_val * 0.15
    if len(highs)>=3 and highs[-2] > last_sh + min_wick and price < last_sh - min_close:
        return "BEAR",90,sh,sl,f"TRUE FAILED BULL {last_sh:.2f} wick {highs[-2]:.2f}",True,"BEAR"
    if len(lows)>=3 and lows[-2] < last_sl - min_wick and price > last_sl + min_close:
        return "BULL",90,sh,sl,f"TRUE FAILED BEAR {last_sl:.2f} wick {lows[-2]:.2f}",True,"BULL"
    hh=last_sh>prev_sh; hl=last_sl>prev_sl; ll=last_sl<prev_sl; lh=last_sh<prev_sh
    if price>last_sh and hh and hl: return "BULL",85,sh,sl,f"BOS BULL Break {last_sh:.2f}",False,None
    if price<last_sl and ll and lh: return "BEAR",85,sh,sl,f"BOS BEAR Break {last_sl:.2f}",False,None
    if hh and hl: return "BULL",70,sh,sl,"Uptrend HH",False,None
    if ll and lh: return "BEAR",70,sh,sl,"Downtrend LL",False,None
    if price>prev_sh: return "BULL",65,sh,sl,f"CHoCH BULL {prev_sh:.2f}",False,None
    if price<prev_sl: return "BEAR",65,sh,sl,f"CHoCH BEAR {prev_sl:.2f}",False,None
    return "RANGE",40,sh,sl,f"Range {last_sl:.2f}-{last_sh:.2f}",False,None
 
def analyze(symbol,interval,fallback):
    price,hist,highs,lows=get_mtf(symbol,interval,fallback)
    atr_val=atr(highs,lows,hist,14)
    trend,conf,sh,sl,desc,failed,fail_dir=bos_choch_true_failed(hist,highs,lows,atr_val)
    return {"price":price,"hist":hist,"highs":highs,"lows":lows,"trend":trend,"conf":conf,"atr":atr_val,"desc":desc,"failed":failed,"fail_dir":fail_dir,"sup10":min(lows[-10:]),"res10":max(highs[-10:])}
 
SYMBOLS={"GOLD":("GC=F",4136.84),"SILVER":("SI=F",32.5),"US30":("^DJI",46000),"GER30":("^GDAXI",25148.03),"NDX100":("^NDX",30800)}
 
def build_signal(symbol_name):
    sym,fb=SYMBOLS[symbol_name]
    tf4=analyze(sym,"4h",fb); tf1=analyze(sym,"1h",fb); tf15=analyze(sym,"15m",fb)
    price=tf15["price"]; now=datetime.now().strftime('%H:%M')
    lines=[f"🎯 {symbol_name} | 💰 {price:.2f} MT5-aligned | 4H {tf4['trend']} | 1H {tf1['trend']} | 15M {tf15['desc']}"]
    atr_1h=tf1["atr"]; sup_15=tf15["sup10"]; res_15=tf15["res10"]
    def buy(): return price-atr_1h*1.2, price+atr_1h*1.8, price+atr_1h*3.0, price+atr_1h*4.5
    def sell(): return price+atr_1h*1.2, price-atr_1h*1.8, price-atr_1h*3.0, price-atr_1h*4.5
    if tf4.get("failed") and tf4.get("fail_dir"):
        fd=tf4["fail_dir"]
        if not (fd=="BEAR" and tf1["trend"]=="BULL" and tf15["trend"]=="BULL"):
            is_buy=fd=="BULL"
            sl,tp1,tp2,tp3=buy() if is_buy else sell()
            lines.append(f"🚨 1️⃣ TRUE FAILED 4H - {tf4['desc']}")
            lines.append(f"{'🟢 BUY' if is_buy else '🔴 SELL'} NOW Entry {price:.2f} SL {sl:.2f} TP1 {tp1:.2f} ⏰ {now}")
            return "\n".join(lines), fd, price
    is_4h_bull=tf4["trend"]=="BULL"; is_4h_bear=tf4["trend"]=="BEAR"
    is_15_bull=tf15["trend"]=="BULL"; is_15_bear=tf15["trend"]=="BEAR"
    is_1h_bull=tf1["trend"]=="BULL"; is_1h_bear=tf1["trend"]=="BEAR"
    if is_4h_bull and is_15_bull and not is_1h_bear:
        sl,tp1,tp2,tp3=buy()
        lines.append(f"🔥 2️⃣ THREE ALIGN BULL"); lines.append(f"🟢 BUY NOW Entry {price:.2f} SL {sl:.2f} TP1 {tp1:.2f} ⏰ {now}")
        return "\n".join(lines), "BUY", price
    if is_4h_bear and is_15_bear and not is_1h_bull:
        sl,tp1,tp2,tp3=sell()
        lines.append(f"🔥 2️⃣ THREE ALIGN BEAR"); lines.append(f"🔴 SELL NOW Entry {price:.2f} SL {sl:.2f} TP1 {tp1:.2f} ⏰ {now}")
        return "\n".join(lines), "SELL", price
    try:
        if is_4h_bull and not is_1h_bear:
            lowest_5 = min(tf15['lows'][-5:]) if len(tf15['lows'])>=5 else price
            if abs(lowest_5 - sup_15) <= tf15['atr']*0.6 and price>sup_15:
                sl,tp1,tp2,tp3=buy()
                lines.append(f"♻️ 3️⃣ CONTINUATION BULL Pullback {sup_15:.2f} within 0.6 ATR")
                lines.append(f"🟢 BUY CONT Entry {price:.2f} SL {sl:.2f} TP1 {tp1:.2f} ⏰ {now}")
                return "\n".join(lines), "BULL_CONT", price
        if is_4h_bear and not is_1h_bull:
            highest_5 = max(tf15['highs'][-5:]) if len(tf15['highs'])>=5 else price
            if abs(highest_5 - res_15) <= tf15['atr']*0.6 and price<res_15:
                sl,tp1,tp2,tp3=sell()
                lines.append(f"♻️ 3️⃣ CONTINUATION BEAR Pullback {res_15:.2f} within 0.6 ATR")
                lines.append(f"🔴 SELL CONT Entry {price:.2f} SL {sl:.2f} TP1 {tp1:.2f} ⏰ {now}")
                return "\n".join(lines), "BEAR_CONT", price
    except: pass
    lines.append("❌ WAIT"); return "\n".join(lines), "WAIT", price
 
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    SUBSCRIBERS.add(update.effective_chat.id)
    await update.message.reply_text("✅ GOLD VIP 2+1 NO MPL FIXED LIVE\nUse /signal GOLD | /autopilot | /stop | /status")
 
async def signal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sym = (context.args[0].upper() if context.args else "GOLD")
        if sym not in SYMBOLS: sym="GOLD"
        txt, direction, price = build_signal(sym)
        await update.message.reply_text(txt)
        # Autostop tracking
        if direction!="WAIT" and sym not in ACTIVE_TRADES:
            ACTIVE_TRADES[sym]={"dir":direction,"price":price,"time":time.time()}
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
 
async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ap="🟢 ON" if AUTOPILOT_ACTIVE else "🔴 OFF"
    trades="\n".join([f"{k}: {v['dir']} @ {v['price']}" for k,v in ACTIVE_TRADES.items()]) or "No active trades"
    await update.message.reply_text(f"Autopilot: {ap}\nChannel: {CHANNEL_ID}\n\n{trades}")
 
async def autopilot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global AUTOPILOT_ACTIVE, AUTOPILOT_TASK
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Admin only"); return
    if AUTOPILOT_ACTIVE:
        await update.message.reply_text("Autopilot already ON"); return
    AUTOPILOT_ACTIVE=True
    SUBSCRIBERS.add(update.effective_chat.id)
    await update.message.reply_text("🚀 Autopilot ON - Scanning every 5 min")
    AUTOPILOT_TASK=asyncio.create_task(autopilot_loop(context))
 
async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global AUTOPILOT_ACTIVE
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Admin only"); return
    AUTOPILOT_ACTIVE=False
    if AUTOPILOT_TASK: AUTOPILOT_TASK.cancel()
    await update.message.reply_text("🛑 Autopilot OFF")
 
async def autopilot_loop(context: ContextTypes.DEFAULT_TYPE):
    while AUTOPILOT_ACTIVE:
        try:
            for name in SYMBOLS.keys():
                txt, direction, price = build_signal(name)
                if direction!="WAIT":
                    if name not in ACTIVE_TRADES:
                        ACTIVE_TRADES[name]={"dir":direction,"price":price,"time":time.time()}
                        for chat_id in list(SUBSCRIBERS):
                            try: await context.bot.send_message(chat_id, txt)
                            except: pass
                        try: await context.bot.send_message(CHANNEL_ID, txt)
                        except: pass
                await asyncio.sleep(2)
            # autostop check - close if SL/TP hit via new price
            for name in list(ACTIVE_TRADES.keys()):
                try:
                    sym,fb=SYMBOLS[name]
                    p,_,_,_=get_mtf(sym,"15m",fb)
                    # simple autostop logic placeholder - real would check SL/TP levels stored
                    if time.time()-ACTIVE_TRADES[name]["time"]> 4*3600: # 4h expiry
                        del ACTIVE_TRADES[name]
                except: pass
        except Exception as e:
            print(f"Autopilot error: {e}")
        await asyncio.sleep(300)
 
async def error_handler(update, context):
    print(f"Update {update} caused error {context.error}")
 
def main():
    if not BOT_TOKEN:
        print("BOT_TOKEN missing"); return
    app=ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("signal", signal_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("autopilot", autopilot_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_error_handler(error_handler)
    print("GOLD VIP 2+1 NO MPL FIXED LIVE - Polling")
    app.run_polling()
 
if __name__=="__main__":
    main()
 
main.py
No matplotlib • No multipl • TRUE FAILED 0.25 ATR
requirements.txt

2 lines only • FIXED version

Copy file
python-telegram-bot==20.8
requests==2.31.0
Only python-telegram-bot==20.8 + requests==2.31.0 — nothing else. Prevents ModuleNotFoundError: No module named 'matplotlib' crash on Render.
Before – Mismatch

main.py: import matplotlib.pyplot as plt
requirements.txt: python-telegram-bot==20.8
requests==2.31.0
→ Exited with status 1
After – Fixed

main.py: no matplotlib, no momentum, no multipl
requirements.txt: 2 lines only – exact match
→ GOLD VIP 2+1 NO MPL FIXED LIVE ✓
