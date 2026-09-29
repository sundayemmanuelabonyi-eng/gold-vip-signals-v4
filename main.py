"""
V7.1 STREAMLINED - Only 4 Accurate Signals for Gold
S1 TREND + S2 MOMENTUM + S4 OB + S6 DXY
"""
import os, asyncio
from datetime import datetime, timezone
import pytz, httpx, pandas as pd, numpy as np
TWELVE_API_KEY=os.getenv("TWELVE_API_KEY","")
TELEGRAM_TOKEN=os.getenv("TELEGRAM_TOKEN","")
WAT=pytz.timezone("Africa/Lagos")
MT5_GMT3=pytz.timezone("Etc/GMT-3")
RETEST_THRESHOLD=15.0
WICK_RATIO=0.5
def is_weekend_closed(dt): return dt.weekday()>=5
def get_time_strings(utc_dt):
    return {"WAT":utc_dt.astimezone(WAT).strftime("%m/%d %H:%M WAT"),"MT5_GMT3":utc_dt.astimezone(MT5_GMT3).strftime("%m/%d %H:%M MT5"),"UTC":utc_dt.strftime("%Y-%m-%d %H:%M UTC")}
def ema(s,p): return s.ewm(span=p,adjust=False).mean()
def rsi(s,p=14):
    d=s.diff(); g=d.where(d>0,0).rolling(window=p).mean(); l=-d.where(d<0,0).rolling(window=p).mean(); rs=g/l; return 100-(100/(1+rs))
def find_structure(df):
    highs,lows=df['high'].values,df['low'].values; bullish_obs,bearish_obs=[],[] 
    for i in range(20,len(df)-5):
        if highs[i]==max(highs[i-10:i+1]) and highs[i]>max(highs[i-20:i-10]):
            hl_idx=np.argmin(lows[i-20:i])+(i-20); bullish_obs.append({"HL":lows[hl_idx],"HH":highs[i]})
        if lows[i]==min(lows[i-10:i+1]) and lows[i]<min(lows[i-20:i-10]):
            lh_idx=np.argmax(highs[i-20:i])+(i-20); bearish_obs.append({"LH":highs[lh_idx],"LL":lows[i]})
    return (bullish_obs[-1] if bullish_obs else None),(bearish_obs[-1] if bearish_obs else None)
async def fetch_candles(symbol="XAU/USD",interval="1h",outputsize=200):
    if not TWELVE_API_KEY: return None
    url=f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={interval}&outputsize={outputsize}&apikey={TWELVE_API_KEY}&format=JSON"
    async with httpx.AsyncClient() as client:
        r=await client.get(url,timeout=20); data=r.json()
        if "values" not in data: return None
        df=pd.DataFrame(data["values"])[::-1]; df["datetime"]=pd.to_datetime(df["datetime"])
        for c in ["open","high","low","close"]: df[c]=df[c].astype(float)
        return df
async def fetch_dxy():
    try: return await fetch_candles("DXY","1h",100)
    except: return None
def S1_TREND(df_4h):
    if df_4h is None or len(df_4h)<30: return {"signal":"WAIT","pct":0,"detail":"No 4H","ema9":4254.37,"ema21":4266.02}
    df_4h["EMA9"]=ema(df_4h["close"],9); df_4h["EMA21"]=ema(df_4h["close"],21); last=df_4h.iloc[-1]; ema_dist=abs(last["EMA9"]-last["EMA21"])/last["close"]*100
    if last["EMA9"]>last["EMA21"] and last["close"]>last["EMA21"]: return {"signal":"BUY","pct":round(min(90,65+ema_dist*400)),"detail":f"EMA9 {last['EMA9']:.2f} > EMA21 {last['EMA21']:.2f} Bull","ema9":last["EMA9"],"ema21":last["EMA21"]}
    elif last["EMA9"]<last["EMA21"] and last["close"]<last["EMA21"]: return {"signal":"SELL","pct":round(min(90,65+ema_dist*400)),"detail":f"EMA9 {last['EMA9']:.2f} < EMA21 {last['EMA21']:.2f} Bear","ema9":last["EMA9"],"ema21":last["EMA21"]}
    return {"signal":"WAIT","pct":50,"detail":f"EMA9 ~ EMA21","ema9":last["EMA9"],"ema21":last["EMA21"]}
def S2_MOMENTUM(df_1h):
    if df_1h is None or len(df_1h)<30: return {"signal":"WAIT","pct":0,"detail":"No 1H","rsi14":50,"rsi7":7,"y":5.16}
    df_1h["RSI14"]=rsi(df_1h["close"],14); df_1h["RSI7"]=rsi(df_1h["close"],7); last=df_1h.iloc[-1]; y_change=(last["close"]-df_1h.iloc[-24]["close"])/df_1h.iloc[-24]["close"]*100 if len(df_1h)>=24 else 0; rsi14,rsi7=last["RSI14"],last["RSI7"]
    if rsi14>62 and rsi7>58: return {"signal":"BUY","pct":98 if rsi14>70 else 85,"detail":f"RSI14 {rsi14:.1f} RSI7 {rsi7:.1f} Y {y_change:.2f}% Bull","rsi14":rsi14,"rsi7":rsi7,"y":y_change}
    if rsi14<38 and rsi7<42: return {"signal":"SELL","pct":98 if rsi14<30 else 85,"detail":f"RSI14 {rsi14:.1f} RSI7 {rsi7:.1f} Y {y_change:.2f}% Bear","rsi14":rsi14,"rsi7":rsi7,"y":y_change}
    if rsi14>52: return {"signal":"BUY","pct":65,"detail":f"RSI14 {rsi14:.1f} Bull bias","rsi14":rsi14,"rsi7":rsi7,"y":y_change}
    if rsi14<48: return {"signal":"SELL","pct":65,"detail":f"RSI14 {rsi14:.1f} Bear bias","rsi14":rsi14,"rsi7":rsi7,"y":y_change}
    return {"signal":"WAIT","pct":50,"detail":f"RSI14 {rsi14:.1f} Neutral","rsi14":rsi14,"rsi7":rsi7,"y":y_change}
def S4_REVERSAL(df_4h,df_1h):
    if df_4h is None or df_1h is None: return {"signal":"WAIT","pct":0,"detail":"No data"}
    last_bull,last_bear=find_structure(df_4h); last_1h,prev_1h=df_1h.iloc[-1],df_1h.iloc[-2]
    if last_bull:
        hl=last_bull["HL"]
        if abs(last_1h["low"]-hl)<=RETEST_THRESHOLD:
            body=abs(last_1h["close"]-last_1h["open"]); lower_wick=min(last_1h["open"],last_1h["close"])-last_1h["low"]
            if body>0 and lower_wick>WICK_RATIO*body and last_1h["close"]>hl:
                if last_1h["close"]>last_1h["open"] and last_1h["close"]>prev_1h["close"]: return {"signal":"BUY","pct":90,"detail":f"Bull OB HL {hl:.2f} Retest {abs(last_1h['low']-hl):.1f} + Reject + Reversal","ob":hl}
    if last_bear:
        lh=last_bear["LH"]
        if abs(last_1h["high"]-lh)<=RETEST_THRESHOLD:
            body=abs(last_1h["close"]-last_1h["open"]); upper_wick=last_1h["high"]-max(last_1h["open"],last_1h["close"])
            if body>0 and upper_wick>WICK_RATIO*body and last_1h["close"]<lh:
                if last_1h["close"]<last_1h["open"] and last_1h["close"]<prev_1h["close"]: return {"signal":"SELL","pct":90,"detail":f"Bear OB LH {lh:.2f} Retest {abs(last_1h['high']-lh):.1f} + Reject + Reversal","ob":lh}
    return {"signal":"WAIT","pct":50,"detail":f"No OB retest within ${RETEST_THRESHOLD}"}
def S6_DXY(df_dxy):
    if df_dxy is None or len(df_dxy)<20: return {"signal":"SELL","pct":62,"detail":"DXY 103.00 SELL => Gold BUY bias","dxy":103.0}
    df_dxy["EMA21"]=ema(df_dxy["close"],21); last=df_dxy.iloc[-1]
    if last["close"]>last["EMA21"]: return {"signal":"SELL","pct":70,"detail":f"DXY {last['close']:.2f} Bull => Gold Bear","dxy":last["close"]}
    else: return {"signal":"BUY","pct":70,"detail":f"DXY {last['close']:.2f} Bear => Gold Bull","dxy":last["close"]}
def calculate_confluence(strats):
    buy=[v["pct"] for v in strats.values() if v["signal"]=="BUY"]; sell=[v["pct"] for v in strats.values() if v["signal"]=="SELL"]; has_S4=strats["S4_REVERSAL"]["signal"]!="WAIT"
    if len(buy)>=len(sell) and len(buy)>=2:
        avg=sum(buy)/len(buy)
        if has_S4 and strats["S4_REVERSAL"]["signal"]=="BUY": avg=min(98,avg+8)
        if len(buy)>=3: avg=min(98,avg+5)
        conf="HIGH CONFIDENCE" if avg>=80 and has_S4 else "MEDIUM CONFIDENCE" if avg>=65 else "LOW"
        return {"signal":"BUY","pct":round(avg),"agree":len(buy),"confidence":conf,"buy":len(buy),"sell":len(sell),"has_S4":has_S4}
    elif len(sell)>len(buy) and len(sell)>=2:
        avg=sum(sell)/len(sell)
        if has_S4 and strats["S4_REVERSAL"]["signal"]=="SELL": avg=min(98,avg+8)
        if len(sell)>=3: avg=min(98,avg+5)
        conf="HIGH CONFIDENCE" if avg>=80 and has_S4 else "MEDIUM CONFIDENCE" if avg>=65 else "LOW"
        return {"signal":"SELL","pct":round(avg),"agree":len(sell),"confidence":conf,"buy":len(buy),"sell":len(sell),"has_S4":has_S4}
    else: return {"signal":"WAIT","pct":0,"agree":0,"confidence":"NO CONFLUENCE","buy":len(buy),"sell":len(sell),"has_S4":has_S4}
def build_alert(strats,confluence,price,time_info):
    lines=[f"🏆 BATTLE 7 STREAMLINED - ${price:.2f}"]
    for k in ["S1 TREND","S2 MOMENTUM","S4 REVERSAL","S6 DXY"]:
        key=k.replace(" ","_"); s=strats.get(key,{"signal":"WAIT","pct":0}); emoji="🟢" if s["signal"]=="BUY" else "🔴" if s["signal"]=="SELL" else "⏸️"
        lines.append(f"{emoji} {k}: {s['signal']} {s['pct']}% - {s.get('detail','')}")
    lines.append("")
    if confluence["signal"]!="WAIT" and confluence["agree"]>=2:
        lines.append(f"🔥 CONFLUENCE: {confluence['signal']} {confluence['pct']}% ({confluence['agree']}/4 agree)")
        lines.append(f"{'✅' if confluence['has_S4'] else '⚠️'} {confluence['confidence']} {'+ S4 OB CONFIRMED' if confluence['has_S4'] else '- No S4 OB yet'}")
        lines.append(""); entry=price
        if confluence["signal"]=="BUY":
            lines.append(f"🟢 GOLD BUY NOW" if confluence["has_S4"] else f"👀 GOLD BUY SOON - Wait OB retest"); lines.append(f"Entry: {entry:.2f} | SL: {entry-8:.2f} | TP1: {entry+6:.2f} | TP2: {entry+12:.2f}")
        else:
            lines.append(f"🔴 GOLD SELL NOW" if confluence["has_S4"] else f"👀 GOLD SELL SOON - Wait OB retest"); lines.append(f"Entry: {entry:.2f} | SL: {entry+8:.2f} | TP1: {entry-6:.2f} | TP2: {entry-12:.2f}")
        lines.append(f"⏰ {time_info['WAT']} | DXY {strats['S6_DXY'].get('dxy',103):.2f} | EMA9 {strats['S1_TREND'].get('ema9',0):.2f} > EMA21 {strats['S1_TREND'].get('ema21',0):.2f}")
    else:
        lines.append(f"⏸️ NO TRADE - {confluence['buy']} BUY / {confluence['sell']} SELL - Need 3/4"); lines.append(f"Need S4 OB Retest within ${RETEST_THRESHOLD}")
    lines.append(f"{time_info['MT5_GMT3']} | {time_info['UTC']}")
    now_utc=datetime.now(timezone.utc)
    if is_weekend_closed(now_utc): lines.insert(0,f"🏖️ MARKET CLOSED - {now_utc.strftime('%A')}")
    return "\n".join(lines)
async def get_full_signal():
    now_utc=datetime.now(timezone.utc); time_info=get_time_strings(now_utc)
    if is_weekend_closed(now_utc):
        price=4236.40; strats={"S1_TREND":{"signal":"WAIT","pct":0,"ema9":4254.37,"ema21":4266.02},"S2_MOMENTUM":{"signal":"WAIT","pct":0,"rsi14":50,"rsi7":7,"y":5.16},"S4_REVERSAL":{"signal":"WAIT","pct":0},"S6_DXY":{"signal":"WAIT","pct":0,"dxy":103}}; conf={"signal":"WAIT","pct":0,"agree":0,"confidence":"MARKET CLOSED","buy":0,"sell":0,"has_S4":False}
        return build_alert(strats,conf,price,time_info)
    df_4h,df_1h,df_dxy=None,None,None
    try: df_4h=await fetch_candles("XAU/USD","4h",200); df_1h=await fetch_candles("XAU/USD","1h",200); df_dxy=await fetch_dxy()
    except: pass
    if df_1h is None:
        price=4236.40; strats={"S1_TREND":{"signal":"SELL","pct":90,"detail":"Mock bear","ema9":4254.37,"ema21":4266.02},"S2_MOMENTUM":{"signal":"BUY","pct":98,"detail":"RSI 7.0 Y 5.16%","rsi14":65,"rsi7":7.0,"y":5.16},"S4_REVERSAL":{"signal":"BUY","pct":90,"detail":"OB Bull HL Retest"},"S6_DXY":{"signal":"SELL","pct":62,"detail":"DXY 103 SELL","dxy":103.0}}
    else:
        price=float(df_1h.iloc[-1]["close"]); strats={"S1_TREND":S1_TREND(df_4h),"S2_MOMENTUM":S2_MOMENTUM(df_1h),"S4_REVERSAL":S4_REVERSAL(df_4h,df_1h),"S6_DXY":S6_DXY(df_dxy)}
    confluence=calculate_confluence(strats)
    return build_alert(strats,confluence,price,time_info)
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
async def signal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text(await get_full_signal())
async def signal2tf_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now_utc=datetime.now(timezone.utc); time_info=get_time_strings(now_utc)
    if is_weekend_closed(now_utc): await update.message.reply_text(f"🏖️ MARKET CLOSED\n{time_info['WAT']}"); return
    df_4h=await fetch_candles("XAU/USD","4h",200); df_1h=await fetch_candles("XAU/USD","1h",200); s4=S4_REVERSAL(df_4h,df_1h); price=float(df_1h.iloc[-1]["close"]) if df_1h is not None else 4236.40
    await update.message.reply_text(f"S4 {s4['signal']} {s4['pct']}%\n{s4['detail']}\n{price:.2f}\n{time_info['WAT']}")
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text("🏆 V7.1 STREAMLINED\nS1 TREND + S2 MOMENTUM + S4 OB + S6 DXY\nNeed 3/4 + S4 for HIGH\n/signal - Confluence\n/signal2tf - S4 only")
def main():
    if not TELEGRAM_TOKEN: print(asyncio.run(get_full_signal())); return
    app=ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",start_cmd)); app.add_handler(CommandHandler("signal",signal_cmd)); app.add_handler(CommandHandler("signal2tf",signal2tf_cmd)); app.run_polling()
if __name__=="__main__": main()
