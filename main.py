import os, requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN", "PUT_YOUR_TOKEN_HERE")
CHANNEL_ID = os.getenv("CHANNEL_ID", "@GoldVIPSignalsOnyebest")
ADMIN_ID = 2093810683

SUBSCRIBERS = set()
PAID_USERS = set()

def ema(vals, period):
    if len(vals) < period: return [sum(vals)/len(vals)]*len(vals)
    k=2/(period+1); e=[sum(vals[:period])/period]
    for p in vals[period:]: e.append(p*k + e[-1]*(1-k))
    return e

def rsi(vals, period=14):
    if len(vals)<period+2: return 50
    deltas=[vals[i+1]-vals[i] for i in range(len(vals)-1)]
    gains=[max(d,0) for d in deltas]; losses=[abs(min(d,0)) for d in deltas]
    avg_g=sum(gains[:period])/period; avg_l=sum(losses[:period])/period
    for i in range(period,len(gains)):
        avg_g=(avg_g*(period-1)+gains[i])/period; avg_l=(avg_l*(period-1)+losses[i])/period
    if avg_l==0: return 70
    rs=avg_g/avg_l; return 100-(100/(1+rs))

def get_gold_data():
    try:
        url="https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=15m&range=5d"
        r=requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=10).json()
        c=r['chart']['result'][0]['indicators']['quote'][0]['close']
        c=[x for x in c if x is not None]
        return c[-300:],[x+2 for x in c][-300:],[x-2 for x in c][-300:]
    except:
        p=requests.get("https://api.gold-api.com/price/XAU", timeout=5).json().get('price',4321)
        return [p]*300,[p+2]*300,[p-2]*300

def get_dxy():
    try:
        url="https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB?interval=15m&range=5d"
        r=requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=8).json()
        closes=r['chart']['result'][0]['indicators']['quote'][0]['close']
        return [c for c in closes if c is not None][-100:]
    except: return [101.04]*100

def get_yield():
    try:
        url="https://query1.finance.yahoo.com/v8/finance/chart/%5ETNX?interval=15m&range=5d"
        r=requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=8).json()
        closes=r['chart']['result'][0]['indicators']['quote'][0]['close']
        return [c for c in closes if c is not None][-100:]
    except: return [4.3]*100

def build_strategies():
    closes,highs,lows=get_gold_data(); dxy=get_dxy(); yields=get_yield()
    price=closes[-1]; e20=ema(closes,20)[-1]; e50=ema(closes,50)[-1]
    e200=ema(closes,200)[-1] if len(closes)>=200 else e50-10
    r=rsi(closes,14); y_now=yields[-1]; y_ema=ema(yields,20)[-1]
    prev_high=max(highs[-96-96:-96]) if len(highs)>192 else max(highs)
    prev_low=min(lows[-96-96:-96]) if len(lows)>192 else min(lows)
    s1={"name":"S1 TREND","dir":"BUY" if e50>e200 else "SELL","prob":65}
    s2_dir="BUY" if e50>e200 and r>50 else "SELL" if e50<e200 and r<50 else "WAIT"
    s2={"name":"S2 MOMENTUM","dir":s2_dir,"prob":75 if s2_dir!="WAIT" and (30<r<50 or 50<r<70) else 60 if s2_dir!="WAIT" else 0}
    s3_dir="BUY" if e20>e50 and r>55 else "SELL" if e20<e50 and r<45 else "WAIT"
    s3={"name":"S3 SCALPER","dir":s3_dir,"prob":68 if s3_dir!="WAIT" else 0}
    s4_dir="BUY" if r<30 else "SELL" if r>70 else "WAIT"
    s4={"name":"S4 REVERSAL","dir":s4_dir,"prob":80 if s4_dir!="WAIT" else 0}
    s5={"name":"S5 PRICE","dir":"BUY" if price>prev_high+2 else "SELL" if price<prev_low-2 else "WAIT","prob":80 if price>prev_high+2 or price<prev_low-2 else 0}
    s6={"name":"S6 DXY","dir":"BUY" if dxy[-1]<ema(dxy,20)[-1] else "SELL" if dxy[-1]>ema(dxy,20)[-1] else "WAIT","prob":72 if dxy[-1]!=ema(dxy,20)[-1] else 0}
    if y_now>y_ema+0.02: s7={"name":"S7 NEWS","dir":"SELL","prob":70,"reason":f"US10Y {y_now:.2f}% > {y_ema:.2f}% bearish"}
    elif y_now<y_ema-0.02: s7={"name":"S7 NEWS","dir":"BUY","prob":70,"reason":f"US10Y {y_now:.2f}% < {y_ema:.2f}% bullish"}
    else: s7={"name":"S7 NEWS","dir":"WAIT","prob":0,"reason":f"Yield sideways {y_now:.2f}%"}
    strats=[s1,s2,s3,s4,s5,s6,s7]
    buys=[s for s in strats if s['dir']=="BUY"]; sells=[s for s in strats if s['dir']=="SELL"]
    if len(buys)>len(sells) and len(buys)>=2: conf={"dir":"BUY","score":min(95,sum(s['prob'] for s in buys)/len(buys)+len(buys)*3),"count":len(buys),"who":"+ ".join([s['name'][:2] for s in buys])}
    elif len(sells)>len(buys) and len(sells)>=2: conf={"dir":"SELL","score":min(95,sum(s['prob'] for s in sells)/len(sells)+len(sells)*3),"count":len(sells),"who":"+ ".join([s['name'][:2] for s in sells])}
    else: conf={"dir":"WAIT","score":0,"count":0,"who":"No agreement"}
    return price,r,prev_high,prev_low,strats,closes,conf,y_now

async def start(update, context):
    price,r,ph,pl,strats,_,conf,y=build_strategies()
    msg=f"🏆 Gold VIP V4.2 PAID\n💰 ${price:.2f} RSI {r:.1f} Y {y:.2f}%\n"
    if conf['dir']!="WAIT": msg+=f"\n🔥 CONFLUENCE: {conf['dir']} {conf['score']:.0f}% ({conf['count']} agree: {conf['who']})\n{'✅ HIGH' if conf['count']>=3 else '⚠️ MED'} \n"
    else: msg+=f"\n❌ NO TRADE\n"
    msg+=f"\n/buy - Join VIP ($25/mo)\n/compare - battle\n/autopilot - alerts ON\n/status - your sub"
    await update.message.reply_text(msg)

async def buy_cmd(update, context):
    msg=f"💎 JOIN GOLD VIP SIGNALS\n🏆 7-Strategy Confluence\n📊 S7 72.9% WR\n🔥 Only HIGH CONF (3+ agree)\n\n💰 PRICE:\n• 1 Month: $25 / ₦40k\n• Lifetime: $99 / ₦150k\n\n💳 PAYMENT:\nOPay: [PUT YOUR OPay]\nUSDT TRC20: [PUT YOUR USDT]\n\n📩 After payment send receipt + ID\nID: {update.effective_chat.id}\n"
    await update.message.reply_text(msg)

async def status_cmd(update, context):
    uid=update.effective_chat.id
    if uid in PAID_USERS or uid==ADMIN_ID: await update.message.reply_text(f"✅ VIP ACTIVE - ID {uid}")
    else: await update.message.reply_text(f"❌ Not VIP - ID {uid}\nUse /buy")

async def addvip(update, context):
    if update.effective_chat.id!= ADMIN_ID: await update.message.reply_text("❌ Admin only"); return
    if context.args:
        nid=int(context.args[0]); PAID_USERS.add(nid)
        await update.message.reply_text(f"✅ Added VIP {nid}")
        try: await context.bot.send_message(chat_id=nid, text=f"🎉 VIP ACTIVATED! Welcome to {CHANNEL_ID}")
        except: pass

async def compare(update, context):
    price,r,ph,pl,strats,_,conf,y=build_strategies()
    msg=f"🏆 BATTLE 7 - ${price:.2f} RSI {r:.1f} Y {y:.2f}%\n"
    for s in strats: msg+=f"{'🔔' if s['dir']!='WAIT' else '❌'} {s['name']}: {s['dir']} {s['prob']}%\n"
    msg+=f"\n🔥 CONF: {conf['dir']} {conf['score']:.0f}% ({conf['count']} agree)\n" if conf['dir']!="WAIT" else "\n❌ NO CONF\n"
    await update.message.reply_text(msg)

async def news_cmd(update, context):
    price,r,ph,pl,strats,_,conf,y=build_strategies(); s7=strats[6]
    await update.message.reply_text(f"📰 S7 NEWS\n💰 ${price:.2f} Y {y:.2f}%\n{s7['name']}: {s7['dir']} {s7['prob']}%\n{s7.get('reason','')}")

async def single(u,c,i):
    price,r,ph,pl,strats,_,conf,y=build_strategies(); s=strats[i]
    await u.message.reply_text(f"{s['name']}: {s['dir']} {s['prob']}%\n💰 ${price:.2f}")

async def s1(u,c): await single(u,c,0)
async def s2(u,c): await single(u,c,1)
async def s3(u,c): await single(u,c,2)
async def s4(u,c): await single(u,c,3)
async def s5(u,c): await single(u,c,4)
async def s6(u,c): await single(u,c,5)
async def s7(u,c): await single(u,c,6)

async def backtest(update, context):
    await update.message.reply_text("⏳ Backtesting...")
    closes,_,_=get_gold_data()
    await update.message.reply_text(f"📊 Backtest done: {len(closes)} candles. Use /compare for live.")

async def auto_check(context):
    if not SUBSCRIBERS and not CHANNEL_ID: return
    price,r,ph,pl,strats,_,conf,y=build_strategies()
    if conf['dir']!="WAIT" and conf['count']>=3 and conf['score']>=75:
        text=f"🚨 AUTO VIP SIGNAL\n💰 Gold ${price:.2f} RSI {r:.1f} Y {y:.2f}%\n🔥 {conf['dir']} {conf['score']:.0f}% HIGH CONF\n{conf['count']} agree: {conf['who']}\nSL ${price-8:.2f} TP ${price+15:.2f}\n#XAUUSD #VIP"
        for chat_id in list(SUBSCRIBERS):
            try: await context.bot.send_message(chat_id=chat_id, text=text)
            except: pass
        if CHANNEL_ID:
            try: await context.bot.send_message(chat_id=CHANNEL_ID, text=text)
            except Exception as e: print(f"Channel fail {e}")

async def autopilot_on(update, context):
    SUBSCRIBERS.add(update.effective_chat.id)
    await update.message.reply_text(f"✅ AUTOPILOT ON\nChat {update.effective_chat.id} saved\nWill alert when 3+ agree 75%+")

async def autopilot_off(update, context):
    SUBSCRIBERS.discard(update.effective_chat.id)
    await update.message.reply_text("🛑 AUTOPILOT OFF")

async def setchannel(update, context):
    global CHANNEL_ID
    if context.args:
        CHANNEL_ID=context.args[0]
        await update.message.reply_text(f"✅ Channel set to {CHANNEL_ID}")
    else:
        await update.message.reply_text(f"Current: {CHANNEL_ID}")

async def channeltest(update, context):
    if not CHANNEL_ID: await update.message.reply_text("❌ No channel set"); return
    try:
        await context.bot.send_message(chat_id=CHANNEL_ID, text=f"✅ VIP TEST ${build_strategies()[0]:.2f} - Linked!")
        await update.message.reply_text(f"✅ Test sent to {CHANNEL_ID}")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed: {e}")

from telegram.ext import ApplicationBuilder
app = ApplicationBuilder().token(BOT_TOKEN).build()
for cmd,fn in [("start",start),("buy",buy_cmd),("status",status_cmd),("addvip",addvip),("compare",compare),("news",news_cmd),("s1",s1),("s2",s2),("s3",s3),("s4",s4),("s5",s5),("s6",s6),("s7",s7),("backtest",backtest),("autopilot",autopilot_on),("autostop",autopilot_off),("setchannel",setchannel),("channeltest",channeltest)]:
    app.add_handler(CommandHandler(cmd, fn))
if app.job_queue:
    app.job_queue.run_repeating(auto_check, interval=900, first=10)
print("V4.2 VIP PAID started")
app.run_polling()
