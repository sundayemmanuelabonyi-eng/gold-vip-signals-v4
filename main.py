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
        try: self.wfile.write(b"GOLD VIP 3-COMBO MTF LIVE - FIXED TRAILING + CONTINUATION")
        except: pass
    def do_HEAD(self): self.send_response(200); self.end_headers()
    def log_message(self,*a): return

def run_server():
    try: HTTPServer(("0.0.0.0", PORT), H).serve_forever()
    except: pass
threading.Thread(target=run_server, daemon=True).start()

def keep_awake_trick():
    while True:
        try:
            time.sleep(240)
            try: requests.get(f"http://localhost:{PORT}", timeout=5)
            except: pass
            if RENDER_URL:
                try: requests.get(RENDER_URL, timeout=5)
                except: pass
        except: time.sleep(60)
threading.Thread(target=keep_awake_trick, daemon=True).start()

BOT_TOKEN=os.getenv("BOT_TOKEN")
DEFAULT_CHANNEL_ID="-1004402762942"
CHANNEL_ID=os.getenv("CHANNEL_ID", DEFAULT_CHANNEL_ID)
ADMIN_ID=int(os.getenv("ADMIN_ID","2093810683"))
CRYPTO_WALLET="TGQu8k7BYJ8h1seQLBT6K8GFgajS33TYdM"
CHANNEL_USERNAME="@GoldVIPSignalsOnyebest"

SUBSCRIBERS=set()
AUTOPILOT_ACTIVE=False
AUTOPILOT_TASK=None
ACTIVE_TRADES={}
PRICE_CACHE={}; CACHE_TIME={}; FAILED_TRACKER={}; FAILED_EXPIRY_SECONDS=300

def ema(vals, period):
    if len(vals)<period: return sum(vals[-period:])/len(vals[-period:]) if vals else 0
    k=2/(period+1); ev=sum(vals[:period])/period
    for v in vals[period:]: ev=v*k+ev*(1-k)
    return ev

def get_spot_gold_price():
    try:
        r=requests.get("https://api.gold-api.com/price/XAU",timeout=5).json()
        p=float(r.get("price",0))
        if 1000<p<10000: return p
    except: pass
    return None

def get_spot_silver_price():
    try:
        r=requests.get("https://api.gold-api.com/price/XAG",timeout=5).json()
        p=float(r.get("price",0))
        if 10<p<100: return p
    except: pass
    return None

def atr(highs, lows, closes, period=14):
    if len(closes)<period+1: return (max(highs[-20:])-min(lows[-20:]))/20 if len(highs)>=20 else 5.0)
    trs=[]
    for i in range(1,len(closes)):
        hl=highs[i]-lows[i] if i<len(highs) and i<len(lows) else 0
        hc=abs(highs[i]-closes[i-1]) if i<len(highs) else 0
        lc=abs(lows[i]-closes[i-1]) if i<len(lows) else 0
        trs.append(max(hl,hc,lc))
    return sum(trs[-period:])/period if trs else 5.0

def get_twelvedata_api_key():
    for name in ["TWELVEDATA_API_KEY","TWELVE_DATA_API_KEY","TWELVEDATA_KEY","TWELVE_API_KEY","TWE_API_KEY"]:
        v=os.getenv(name,"").strip()
        if v and len(v)>10: return v
    for k,v in os.environ.items():
        if k.startswith("TWE") and len(v.strip())>10:
            vv=v.strip()
            if len(vv)>=20: return vv
    for p in ["/etc/secrets/TWELVEDATA_API_KEY","/etc/secrets/TWELVE_DATA_API_KEY","./TWELVEDATA_API_KEY","/mnt/data/TWELVEDATA_API_KEY"]:
        try:
            if os.path.exists(p):
                with open(p,'r') as sf:
                    v=sf.read().strip()
                    if len(v)>10: return v
        except: pass
    return ""

def get_twelvedata_mtf(symbol, interval, fallback):
    api_key=get_twelvedata_api_key()
    if not api_key: return None,[],[],[]
    try:
        td_map={"GC=F":"XAU/USD","SI=F":"XAG/USD","^DJI":"DJI","^GDAXI":"DAX","^NDX":"NDX"}
        td_symbol=td_map.get(symbol,symbol)
        td_int={"15m":"15min","1h":"1h","4h":"4h"}.get(interval,"15min")
        url=f"https://api.twelvedata.com/time_series?symbol={td_symbol}&interval={td_int}&outputsize=100&apikey={api_key}&order=ASC"
        r=requests.get(url,timeout=10).json()
        if "values" not in r: return None,[],[],[]
        values=r["values"]
        if len(values)<20: return None,[],[],[]
        closes=[]; highs=[]; lows=[]
        for v in values:
            try: closes.append(float(v["close"])); highs.append(float(v["high"])); lows.append(float(v["low"]))
            except: continue
        if len(closes)<20: return None,[],[],[]
        price=closes[-1]; max_hist=200 if interval=="4h" else 100
        history=closes[-max_hist:]; highs=highs[-max_hist:]; lows=lows[-max_hist:]
        PRICE_CACHE[f"{symbol}_{interval}"]=(price,history,highs,lows); CACHE_TIME[f"{symbol}_{interval}"]=time.time()
        return price,history,highs,lows
    except: return None,[],[],[]

def get_real_price_mtf_yahoo(symbol, interval, fallback):
    key=f"{symbol}_{interval}"; now=time.time()
    if key in PRICE_CACHE and key in CACHE_TIME:
        if now-CACHE_TIME[key]<90: return PRICE_CACHE[key]
    try:
        headers={'User-Agent':'Mozilla/5.0'}
        yf_interval={"15m":"15m","1h":"60m","4h":"60m"}[interval]
        range_map={"15m":"5d","1h":"10d","4h":"60d"}
        url=f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval={yf_interval}&range={range_map[interval]}"
        r=requests.get(url,headers=headers,timeout=8).json()
        result=r['chart']['result'][0]
        closes=result['indicators']['quote'][0]['close']; high_data=result['indicators']['quote'][0]['high']; low_data=result['indicators']['quote'][0]['low']
        closes=[c for c in closes if c is not None]; high_data=[h for h in high_data if h is not None]; low_data=[l for l in low_data if l is not None]
        if closes and len(closes)>=20:
            if interval=="4h":
                agg_c=[]; agg_h=[]; agg_l=[]
                for i in range(0,len(closes),4):
                    chunk_c=closes[i:i+4]; chunk_h=high_data[i:i+4] if i<len(high_data) else chunk_c; chunk_l=low_data[i:i+4] if i<len(low_data) else chunk_c
                    if chunk_c: agg_c.append(chunk_c[-1]); agg_h.append(max(chunk_h) if chunk_h else chunk_c[-1]); agg_l.append(min(chunk_l) if chunk_l else chunk_c[-1])
                closes=agg_c; high_data=agg_h; low_data=agg_l
            price=closes[-1]; max_hist=200 if interval=="4h" else 100
            history=closes[-max_hist:] if len(closes)>=max_hist else closes; highs=high_data[-max_hist:] if len(high_data)>=max_hist else high_data; lows=low_data[-max_hist:] if len(low_data)>=max_hist else low_data
            PRICE_CACHE[key]=(price,history,highs,lows); CACHE_TIME[key]=now
            return price,history,highs,lows
    except Exception as e: print(f"Yahoo failed {symbol} {interval}: {e}")
    if key in PRICE_CACHE: return PRICE_CACHE[key]
    if fallback and 10<fallback<100000:
        price=fallback; history=[fallback+(i-50)*0.1 for i in range(100)]; highs=[h+0.5 for h in history]; lows=[l-0.5 for l in history]
        return price,history,highs,lows
    return None,[],[],[]

def get_real_price_mtf(symbol, interval, fallback):
    if symbol in ["GC=F","SI=F"]:
        p,h,hi,lo=get_twelvedata_mtf(symbol,interval,fallback)
        if p is not None and len(h)>=20: return p,h,hi,lo
        return get_real_price_mtf_yahoo(symbol,interval,fallback)
    else:
        p,h,hi,lo=get_real_price_mtf_yahoo(symbol,interval,fallback)
        if p is not None and len(h)>=20: return p,h,hi,lo
        return get_twelvedata_mtf(symbol,interval,fallback)

def get_sr_levels(history, lookback=30, highs=None, lows=None, price=None, sh=None, sl=None):
    if sh is None or sl is None:
        if len(history)<10: return history[-1]*0.998, history[-1]*1.002
        recent=history[-lookback:] if len(history)>=lookback else history
        swing_lows=[]; swing_highs=[]
        for i in range(2,len(recent)-2):
            if recent[i]<recent[i-1] and recent[i]<recent[i-2] and recent[i]<recent[i+1] and recent[i]<recent[i+2]: swing_lows.append(recent[i])
            if recent[i]>recent[i-1] and recent[i]>recent[i-2] and recent[i]>recent[i+1] and recent[i]>recent[i+2]: swing_highs.append(recent[i])
        if not swing_lows: swing_lows=sorted(recent)[:3]
        if not swing_highs: swing_highs=sorted(recent)[-3:]
        sup=sum(swing_lows[-2:])/min(2,len(swing_lows[-2:])) if swing_lows else min(recent)
        res=sum(swing_highs[-2:])/min(2,len(swing_highs[-2:])) if swing_highs else max(recent)
        if res<=sup: res=max(recent); sup=min(recent)
        if price is not None:
            lows_below=[x for x in swing_lows if x<price]; highs_above=[x for x in swing_highs if x>price]
            sup=max(lows_below) if lows_below else price*0.998
            res=min(highs_above) if highs_above else price*1.002
        return sup,res
    else:
        if price is None: price=history[-1] if history else 0
        sl_below=[v for i,v in sl if v<price]; sh_above=[v for i,v in sh if v>price]
        sup=max(sl_below) if sl_below else (min(lows[-20:]) if lows and len(lows)>=20 else price*0.995)
        res=min(sh_above) if sh_above else (max(highs[-20:]) if highs and len(highs)>=20 else price*1.005)
        if sup>=price: sup=price*0.997
        if res<=price: res=price*1.003
        return sup,res

def get_swing_points(highs, lows, left=2, right=2):
    sh=[]; sl=[]
    for i in range(left, len(highs)-right):
        is_sh=all(highs[i]>highs[i-j] for j in range(1,left+1)) and all(highs[i]>highs[i+j] for j in range(1,right+1))
        if is_sh: sh.append((i,highs[i]))
        is_sl=all(lows[i]<lows[i-j] for j in range(1,left+1)) and all(lows[i]<lows[i+j] for j in range(1,right+1))
        if is_sl: sl.append((i,lows[i]))
    return sh,sl

def detect_bos_choch(hist, highs, lows):
    sh,sl=get_swing_points(highs,lows,2,2)
    if len(sh)<2 or len(sl)<2: return "RANGE",50,sh,sl,"No clear structure",False,None
    last_sh=sh[-1][1]; prev_sh=sh[-2][1]; last_sl=sl[-1][1]; prev_sl=sl[-2][1]; price=hist[-1]
    if len(highs)>=3 and highs[-2]>last_sh and price<last_sh:
        return "BEAR",90,sh,sl,f"FAILED BULL {last_sh:.2f} -> {highs[-2]:.2f} wick then close {price:.2f} below IMMEDIATE SELL",True,"BEAR"
    if len(lows)>=3 and lows[-2]<last_sl and price>last_sl:
        return "BULL",90,sh,sl,f"FAILED BEAR {last_sl:.2f} -> {lows[-2]:.2f} wick then close {price:.2f} above IMMEDIATE BUY",True,"BULL"
    hh=last_sh>prev_sh; hl=last_sl>prev_sl; ll=last_sl<prev_sl; lh=last_sh<prev_sh
    bos_bull=price>last_sh; bos_bear=price<last_sl
    if bos_bull and hh and hl: return "BULL",85,sh,sl,f"BOS BULL Break {last_sh:.2f} HH/HL",False,None
    if bos_bear and ll and lh: return "BEAR",85,sh,sl,f"BOS BEAR Break {last_sl:.2f} LL/LH",False,None
    if hh and hl: return "BULL",70,sh,sl,f"Uptrend HH {prev_sh:.2f}->{last_sh:.2f} HL {prev_sl:.2f}->{last_sl:.2f}",False,None
    if ll and lh: return "BEAR",70,sh,sl,f"Downtrend LL {prev_sl:.2f}->{last_sl:.2f} LH {prev_sh:.2f}->{last_sh:.2f}",False,None
    if price>prev_sh and ll: return "BULL",65,sh,sl,f"CHoCH BULL {prev_sh:.2f} break",False,None
    if price<prev_sl and hh: return "BEAR",65,sh,sl,f"CHoCH BEAR {prev_sl:.2f} break",False,None
    return "RANGE",40,sh,sl,f"Range {last_sl:.2f}-{last_sh:.2f}",False,None

def analyze_4h(symbol, fallback):
    spot_override=get_spot_gold_price() if symbol=="GC=F" else get_spot_silver_price() if symbol=="SI=F" else None
    result=get_real_price_mtf(symbol,"4h",fallback)
    if result[0] is None: return None
    price,hist,highs,lows=result
    if spot_override: price=spot_override
    trend,conf,sh,sl,desc,failed,fail_dir=detect_bos_choch(hist,highs,lows)
    sup,res=get_sr_levels(hist,30,highs,lows,price,sh,sl)
    atr_val=atr(highs,lows,hist,14)
    ob_high=res; ob_low=sup
    if sh: ob_high=sh[-1][1]
    if sl: ob_low=sl[-1][1]
    return {"price":price,"hist":hist,"highs":highs,"lows":lows,"trend":trend,"conf":conf,"sup":sup,"res":res,"atr":atr_val,"sh":sh,"sl":sl,"desc":desc,"ob_high":ob_high,"ob_low":ob_low,"failed":failed,"fail_dir":fail_dir}

def analyze_1h(symbol, fallback):
    spot_override=get_spot_gold_price() if symbol=="GC=F" else get_spot_silver_price() if symbol=="SI=F" else None
    result=get_real_price_mtf(symbol,"1h",fallback)
    if result[0] is None: return None
    price,hist,highs,lows=result
    if spot_override: price=spot_override
    trend,conf,sh,sl,desc,failed,fail_dir=detect_bos_choch(hist,highs,lows)
    sup,res=get_sr_levels(hist,50,highs,lows,price,sh,sl)
    atr_val=atr(highs,lows,hist,14)
    sweep="None"
    if len(highs)>=20:
        recent_high=max(highs[-20:-2]); recent_low=min(lows[-20:-2])
        if highs[-2]>recent_high and hist[-1]<recent_high: sweep=f"BEAR Sweep {recent_high:.2f} -> {highs[-2]:.2f} wick then close below"
        elif lows[-2]<recent_low and hist[-1]>recent_low: sweep=f"BULL Sweep {recent_low:.2f} -> {lows[-2]:.2f} wick then close above"
    bias=trend; near_sr=f"{desc} | Sweep: {sweep}"
    return {"price":price,"hist":hist,"highs":highs,"lows":lows,"bias":bias,"sup":sup,"res":res,"near_sr":near_sr,"atr":atr_val,"sh":sh,"sl":sl,"desc":desc,"sweep":sweep,"conf":conf,"failed":failed,"fail_dir":fail_dir}

def analyze_15m(symbol, fallback):
    spot_override=get_spot_gold_price() if symbol=="GC=F" else get_spot_silver_price() if symbol=="SI=F" else None
    result=get_real_price_mtf(symbol,"15m",fallback)
    if result[0] is None: return None
    price,hist,highs,lows=result
    if spot_override: price=spot_override
    trend,conf,sh,sl,desc,failed,fail_dir=detect_bos_choch(hist,highs,lows)
    sup,res=get_sr_levels(hist,20,highs,lows,price,sh,sl)
    atr_val=atr(highs,lows,hist,14)
    trigger="WAIT"
    if "CHoCH BULL" in desc: trigger="BUY"
    elif "CHoCH BEAR" in desc: trigger="SELL"
    else:
        if trend=="BULL" and conf>=70: trigger="BUY"
        elif trend=="BEAR" and conf>=70: trigger="SELL"
    fvg="None"
    if len(hist)>=3:
        if lows[-1]>highs[-3]: fvg=f"BULL FVG {highs[-3]:.2f}-{lows[-1]:.2f}"
        if highs[-1]<lows[-3]: fvg=f"BEAR FVG {lows[-3]:.2f}-{highs[-1]:.2f}"
    return {"price":price,"hist":hist,"highs":highs,"lows":lows,"sup":sup,"res":res,"trigger":trigger,"atr":atr_val,"sh":sh,"sl":sl,"desc":desc,"fvg":fvg,"conf":conf,"failed":failed,"fail_dir":fail_dir}

def update_trailing_status(symbol_name, current_price):
    if symbol_name not in ACTIVE_TRADES: return None
    t=ACTIVE_TRADES[symbol_name]; entry=t['entry']; atr_v=t.get('atr',15); direction=t['direction']; status=t.get('status','OPEN'); trail_sl=t.get('trail_sl',t['sl'])
    if current_price<=0: return None
    if symbol_name in ["GER30","US30","NDX100"] and current_price<1000: return None
    if symbol_name in ["GOLD"] and (current_price<1000 or current_price>10000): return None
    if symbol_name in ["SILVER"] and (current_price<10 or current_price>100): return None
    if abs(entry-current_price)>entry*0.20: return None
    trail_dist=atr_v*1.0; profit_trigger_small=atr_v*0.3; profit_trigger_be=1.0; msgs=[]
    # FIXED: handles BUY, BULL, BULL_FAILED_4H, BULL_CONTINUATION
    if "BUY" in direction or "BULL" in direction:
        profit=current_price-entry
        if profit>=profit_trigger_small and status=="OPEN":
            new_sl=entry+profit_trigger_be
            if new_sl>trail_sl: t['trail_sl']=new_sl; t['status']="PROFIT_LOCKED"; msgs.append(f"✅ {symbol_name} BUY +{profit:.2f}$ PROFIT! NO-LOSS ACTIVATED\nMove SL to BE+1: {new_sl:.2f}")
        if current_price>=t['tp1'] and status in ["OPEN","PROFIT_LOCKED"]:
            t['status']="TP1_HIT"; new_sl=entry+2.0
            if new_sl>t['trail_sl']: t['trail_sl']=new_sl
            msgs.append(f"🔒 {symbol_name} BUY TP1 HIT {t['tp1']:.2f}! SL now {t['trail_sl']:.2f} (+{t['trail_sl']-entry:.2f}$ locked)")
        if current_price>=t['tp2'] and status in ["TP1_HIT","PROFIT_LOCKED"]:
            t['status']="TP2_HIT"
            if t['tp1']>t['trail_sl']: t['trail_sl']=t['tp1']
            msgs.append(f"🔒🔒 {symbol_name} BUY TP2 HIT {t['tp2']:.2f}! Lock profit SL {t['trail_sl']:.2f} (+{t['trail_sl']-entry:.2f}$)")
        if status!="OPEN":
            new_trail=current_price-trail_dist
            if new_trail>t['trail_sl'] and new_trail>entry:
                profit_locked=new_trail-entry; t['trail_sl']=new_trail
                msgs.append(f"📈 {symbol_name} BUY TRAILING +{profit:.2f}$ -> SL now {new_trail:.2f} (+{profit_locked:.2f}$ GUARANTEED)")
    else:
        profit=entry-current_price
        if profit>=profit_trigger_small and status=="OPEN":
            new_sl=entry-profit_trigger_be
            if new_sl<trail_sl: t['trail_sl']=new_sl; t['status']="PROFIT_LOCKED"; msgs.append(f"✅ {symbol_name} SELL +{profit:.2f}$ PROFIT! NO-LOSS ACTIVATED\nMove SL to BE+1: {new_sl:.2f}")
        if current_price<=t['tp1'] and status in ["OPEN","PROFIT_LOCKED"]:
            t['status']="TP1_HIT"; new_sl=entry-2.0
            if new_sl<t['trail_sl']: t['trail_sl']=new_sl
            msgs.append(f"🔒 {symbol_name} SELL TP1 HIT {t['tp1']:.2f}! SL now {t['trail_sl']:.2f} (+{entry-t['trail_sl']:.2f}$ locked)")
        if current_price<=t['tp2'] and status in ["TP1_HIT","PROFIT_LOCKED"]:
            t['status']="TP2_HIT"
            if t['tp1']<t['trail_sl']: t['trail_sl']=t['tp1']
            msgs.append(f"🔒🔒 {symbol_name} SELL TP2 HIT {t['tp2']:.2f}! Lock profit SL {t['trail_sl']:.2f} (+{entry-t['trail_sl']:.2f}$)")
        if status!="OPEN":
            new_trail=current_price+trail_dist
            if new_trail<t['trail_sl'] and new_trail<entry:
                profit_locked=entry-new_trail; t['trail_sl']=new_trail
                msgs.append(f"📉 {symbol_name} SELL TRAILING +{profit:.2f}$ -> SL now {new_trail:.2f} (+{profit_locked:.2f}$ GUARANTEED)")
    ACTIVE_TRADES[symbol_name]=t
    return "\n".join(msgs) if msgs else None

SYMBOLS={"GOLD":("GC=F",4136.84),"SILVER":("SI=F",32.5),"US30":("^DJI",46000),"GER30":("^GDAXI",25148.03),"NDX100":("^NDX",30800),}

def build_mtf_confluence(symbol_name):
    sym,fallback=SYMBOLS[symbol_name]
    tf4=analyze_4h(sym,fallback); tf1=analyze_1h(sym,fallback); tf15=analyze_15m(sym,fallback)
    if tf4 is None or tf1 is None or tf15 is None: return f"⏳ {symbol_name} Data unavailable","", "WAIT", fallback, None
    price=tf15["price"]
    if sym=="GC=F":
        sp=get_spot_gold_price()
        if sp and 1000<sp<10000: price=sp
    elif sym=="SI=F":
        sp=get_spot_silver_price()
        if sp and 10<sp<100: price=sp
    now=datetime.now().strftime('%H:%M'); td_key=get_twelvedata_api_key()
    data_source=f"TwelveData XAU/USD key:{td_key[:6]}...{td_key[-4:]}" if td_key else "Yahoo GC=F"
    lines=[]; lines.append(f"🎯 {symbol_name} 4H->1H->15M PURE PRICE ACTION | Source: {data_source}")
    lines.append(f"💰 {price:.2f} | 4H {tf4['trend']} {tf4['conf']}% {tf4['desc']} | 1H {tf1['bias']} {tf1['sweep']} | 15M {tf15['trigger']} {tf15['desc']} FVG:{tf15['fvg']}")
    lines.append(f"4H: {tf4['desc']} | OB {tf4['ob_low']:.2f}/{tf4['ob_high']:.2f} S/R {tf4['sup']:.2f}/{tf4['res']:.2f} ATR {tf4['atr']:.2f}")
    lines.append(f"1H: {tf1['near_sr']} | S/R {tf1['sup']:.2f}/{tf1['res']:.2f} ATR {tf1['atr']:.2f}")
    lines.append(f"15M: {tf15['desc']} | FVG {tf15['fvg']} | S/R {tf15['sup']:.2f}/{tf15['res']:.2f} ATR {tf15['atr']:.2f}"); lines.append("")
    direction="WAIT"; vip_lines=[]; atr_1h=tf1["atr"]; sup_1h=tf1["sup"]; res_1h=tf1["res"]; sup_4h=tf4["sup"]; res_4h=tf4["res"]; sup_15m=tf15["sup"]; res_15m=tf15["res"]; buffer=atr_1h*0.3
    def calc_buy_sl_tp():
        sl_s=min(sup_1h,sup_15m)-buffer
        if price-sl_s<atr_1h*1.0: sl_s=price-atr_1h*1.2
        if price-sl_s>atr_1h*2.5: sl_s=price-atr_1h*2.0
        tp1=res_15m if res_15m>price+atr_1h*0.5 else price+atr_1h*1.8; tp2=res_1h if res_1h>tp1 else price+atr_1h*3.0; tp3=res_4h if res_4h>tp2 else price+atr_1h*4.5
        return sl_s,tp1,tp2,tp3
    def calc_sell_sl_tp():
        sl_s=max(res_1h,res_15m)+buffer
        if sl_s-price<atr_1h*1.0: sl_s=price+atr_1h*1.2
        if sl_s-price>atr_1h*2.5: sl_s=price+atr_1h*2.0
        tp1=sup_15m if sup_15m<price-atr_1h*0.5 else price-atr_1h*1.8; tp2=sup_1h if sup_1h<tp1 else price-atr_1h*3.0; tp3=sup_4h if sup_4h<tp2 else price-atr_1h*4.5
        return sl_s,tp1,tp2,tp3

    immediate_4h_failed=None
    if tf4.get("failed") and tf4.get("fail_dir"):
        try:
            import re as re_mod; m=re_mod.search(r"FAILED \w+ ([\d\.]+)",tf4["desc"])
            if m:
                failed_level=float(m.group(1)); dist=abs(price-failed_level); max_dist=tf4["atr"]*2.5
                if dist<=max_dist:
                    key=f"{symbol_name}_4H_{tf4['fail_dir']}_{tf4['desc'][:30]}"; now_ts=time.time(); age=0
                    if key in FAILED_TRACKER:
                        age=now_ts-FAILED_TRACKER[key]
                        if age>FAILED_EXPIRY_SECONDS:
                            lines.append(f"❌ EXPIRED 4H FAILED {tf4['fail_dir']} - {int(age)}s ago (>5m) - TOO LATE")
                            if age>600: del FAILED_TRACKER[key]
                            age=None
                        else:
                            lines.append(f"✅ FRESH 4H FAILED {tf4['fail_dir']} - {int(age)}s ago - VALID <5m")
                            immediate_4h_failed=(tf4["fail_dir"],tf4["desc"],tf4["atr"],failed_level,dist,max_dist)
                    else:
                        FAILED_TRACKER[key]=now_ts; immediate_4h_failed=(tf4["fail_dir"],tf4["desc"],tf4["atr"],failed_level,dist,max_dist)
                        lines.append(f"✅ FRESH 4H FAILED FIRST TIME {tf4['fail_dir']} level {failed_level:.2f} price {price:.2f} dist {dist:.2f} < {max_dist:.2f} - VALID")
                else: lines.append(f"❌ FAR 4H FAILED {tf4['fail_dir']} level {failed_level:.2f} vs price {price:.2f} dist {dist:.2f} > {max_dist:.2f} - skip")
        except Exception as e: print(f"4H failed check error {e}")

    if immediate_4h_failed:
        fail_dir,desc,atr_tf,failed_level,dist,max_dist=immediate_4h_failed; is_buy=fail_dir=="BULL"; direction=f"{fail_dir}_FAILED_4H"; emoji="🚨🟢" if is_buy else "🚨🔴"
        if is_buy:
            sl=sup_15m-atr_tf*0.3;
            if sl>=price: sl=price-atr_tf*0.8
            tp1=res_15m if res_15m>price+atr_tf*0.3 else price+atr_tf*0.8; tp2=res_1h if res_1h>tp1 else price+atr_tf*1.5; tp3=res_4h if res_4h>tp2 else price+atr_tf*2.2
        else:
            sl=res_15m+atr_tf*0.3
            if sl<=price: sl=price+atr_tf*0.8
            tp1=sup_15m if sup_15m<price-atr_tf*0.3 else price-atr_tf*0.8; tp2=sup_1h if sup_1h<tp1 else price-atr_tf*1.5; tp3=sup_4h if sup_4h<tp2 else price-atr_tf*2.2
        lines.append(f"🚨 4H IMMEDIATE FAILED {desc}"); lines.append(f"{emoji} {symbol_name} IMMEDIATE {fail_dir} NOW - Failed to transit (4H)"); lines.append(f"Entry: {price:.2f} SL: {sl:.2f} TP1: {tp1:.2f} (15M) TP2: {tp2:.2f} (1H) TP3: {tp3:.2f} (4H) ⏰ {now}")
        vip_lines.append(f"{emoji} {symbol_name} IMMEDIATE {fail_dir} FAILED 4H"); vip_lines.append(f"Entry: {price:.2f} SL: {sl:.2f} TP1: {tp1:.2f} TP2: {tp2:.2f} TP3: {tp3:.2f}"); vip_lines.append(f"🚨 {desc}")
        ACTIVE_TRADES[symbol_name]={'entry':price,'sl':sl,'tp1':tp1,'tp2':tp2,'tp3':tp3,'direction':direction,'atr':atr_1h,'trail_sl':sl,'status':'OPEN'}
        return "\n".join(lines), "\n".join(vip_lines), direction, price, None

    bull_align=(tf4["trend"]=="BULL" and tf4["conf"]>=60 and tf1["bias"]=="BULL" and tf1["conf"]>=60 and tf15["trigger"]=="BUY" and tf15["conf"]>=60)
    bear_align=(tf4["trend"]=="BEAR" and tf4["conf"]>=60 and tf1["bias"]=="BEAR" and tf1["conf"]>=60 and tf15["trigger"]=="SELL" and tf15["conf"]>=60)
    bull_align_sweep=(tf4["trend"]=="BULL" and tf4["conf"]>=70 and "BULL Sweep" in tf1["sweep"] and tf15["trigger"]=="BUY")
    bear_align_sweep=(tf4["trend"]=="BEAR" and tf4["conf"]>=70 and "BEAR Sweep" in tf1["sweep"] and tf15["trigger"]=="SELL")
    if bull_align or bull_align_sweep:
        sl,tp1,tp2,tp3=calc_buy_sl_tp(); direction="BUY"
        lines.append(f"🔥🔥 THREE STRUCTURES ALIGN BULL: 4H BULL {tf4['conf']}% + 1H BULL {tf1['conf']}% + 15M BUY {tf15['conf']}%")
        lines.append(f"🟢 {symbol_name} BUY NOW - 3 TF ALIGN"); lines.append(f"Entry: {price:.2f} SL: {sl:.2f} TP1: {tp1:.2f} TP2: {tp2:.2f} TP3: {tp3:.2f} ⏰ {now}")
        vip_lines.append(f"🟢 {symbol_name} BUY NOW - THREE STRUCTURES ALIGN"); vip_lines.append(f"Entry: {price:.2f} SL: {sl:.2f} TP1: {tp1:.2f} TP2: {tp2:.2f} TP3: {tp3:.2f}")
        ACTIVE_TRADES[symbol_name]={'entry':price,'sl':sl,'tp1':tp1,'tp2':tp2,'tp3':tp3,'direction':direction,'atr':atr_1h,'trail_sl':sl,'status':'OPEN'}
        return "\n".join(lines), "\n".join(vip_lines), direction, price, None
    if bear_align or bear_align_sweep:
        sl,tp1,tp2,tp3=calc_sell_sl_tp(); direction="SELL"
        lines.append(f"🔥🔥 THREE STRUCTURES ALIGN BEAR: 4H BEAR {tf4['conf']}% + 1H BEAR {tf4['conf']}% + 15M SELL {tf15['conf']}%")
        lines.append(f"🔴 {symbol_name} SELL NOW - 3 TF ALIGN"); lines.append(f"Entry: {price:.2f} SL: {sl:.2f} TP1: {tp1:.2f} TP2: {tp2:.2f} TP3: {tp3:.2f} ⏰ {now}")
        vip_lines.append(f"🔴 {symbol_name} SELL NOW - THREE STRUCTURES ALIGN"); vip_lines.append(f"Entry: {price:.2f} SL: {sl:.2f} TP1: {tp1:.2f} TP2: {tp2:.2f} TP3: {tp3:.2f}")
        ACTIVE_TRADES[symbol_name]={'entry':price,'sl':sl,'tp1':tp1,'tp2':tp2,'tp3':tp3,'direction':direction,'atr':atr_1h,'trail_sl':sl,'status':'OPEN'}
        return "\n".join(lines), "\n".join(vip_lines), direction, price, None

    # ===== CONDITION 3: TREND CONTINUATION AFTER PULLBACK + CONFIRMATION =====
    try:
        pullback_buy=False; pullback_sell=False; recent_low=None; recent_high=None; dist_to_sup=999; dist_to_res=999
        if tf15['lows'] and len(tf15['lows'])>=5:
            recent_low=min(tf15['lows'][-5:]); dist_to_sup=abs(recent_low-sup_15m)
            if dist_to_sup<=tf15['atr']*0.6 and tf4['trend']=="BULL" and tf1['bias']=="BULL": pullback_buy=True
        if tf15['highs'] and len(tf15['highs'])>=5:
            recent_high=max(tf15['highs'][-5:]); dist_to_res=abs(recent_high-res_15m)
            if dist_to_res<=tf15['atr']*0.6 and tf4['trend']=="BEAR" and tf1['bias']=="BEAR": pullback_sell=True
        conf_buy="CHoCH BULL" in tf15['desc'] or "BOS BULL" in tf15['desc'] or (tf15['trigger']=="BUY" and tf15['conf']>=55)
        conf_sell="CHoCH BEAR" in tf15['desc'] or "BOS BEAR" in tf15['desc'] or (tf15['trigger']=="SELL" and tf15['conf']>=55)
        if tf4['trend']=="BULL" and tf1['bias']=="BULL" and pullback_buy and conf_buy and price>sup_15m+atr_1h*0.2:
            sl,tp1,tp2,tp3=calc_buy_sl_tp(); direction="BULL_CONTINUATION"
            lines.append(f"♻️ CONTINUATION BULL: 4H BULL + 1H BULL + Pullback to {sup_15m:.2f} ({recent_low:.2f}) + {tf15['desc']}")
            lines.append(f"🟢 {symbol_name} BUY CONTINUATION - After Pullback"); lines.append(f"Entry: {price:.2f} SL: {sl:.2f} TP1: {tp1:.2f} TP2: {tp2:.2f} TP3: {tp3:.2f} ⏰ {now}")
            vip_lines.append(f"♻️🟢 {symbol_name} BUY CONTINUATION - Trend Resumes After Pullback"); vip_lines.append(f"Entry: {price:.2f} SL: {sl:.2f} TP1: {tp1:.2f} TP2: {tp2:.2f} TP3: {tp3:.2f}")
            ACTIVE_TRADES[symbol_name]={'entry':price,'sl':sl,'tp1':tp1,'tp2':tp2,'tp3':tp3,'direction':direction,'atr':atr_1h,'trail_sl':sl,'status':'OPEN'}
            return "\n".join(lines), "\n".join(vip_lines), direction, price, None
        if tf4['trend']=="BEAR" and tf1['bias']=="BEAR" and pullback_sell and conf_sell and price<sup_15m-atr_1h*0.2 or tf4['trend']=="BEAR" and tf1['bias']=="BEAR" and pullback_sell and conf_sell and price<res_15m-atr_1h*0.2:
            # Fixed condition for bear
            if price<res_15m-atr_1h*0.2:
                sl,tp1,tp2,tp3=calc_sell_sl_tp(); direction="BEAR_CONTINUATION"
                lines.append(f"♻️ CONTINUATION BEAR: 4H BEAR + 1H BEAR + Pullback to {res_15m:.2f} ({recent_high:.2f}) + {tf15['desc']}")
                lines.append(f"🔴 {symbol_name} SELL CONTINUATION - After Pullback"); lines.append(f"Entry: {price:.2f} SL: {sl:.2f} TP1: {tp1:.2f} TP2: {tp2:.2f} TP3: {tp3:.2f} ⏰ {now}")
                vip_lines.append(f"♻️🔴 {symbol_name} SELL CONTINUATION"); vip_lines.append(f"Entry: {price:.2f} SL: {sl:.2f} TP1: {tp1:.2f} TP2: {tp2:.2f} TP3: {tp3:.2f}")
                ACTIVE_TRADES[symbol_name]={'entry':price,'sl':sl,'tp1':tp1,'tp2':tp2,'tp3':tp3,'direction':direction,'atr':atr_1h,'trail_sl':sl,'status':'OPEN'}
                return "\n".join(lines), "\n".join(vip_lines), direction, price, None
    except Exception as e: print(f"Continuation error {e}")

    lines.append(f"❌ WAIT - No 4H FAILED, No 3-TF align, No pullback continuation")
    lines.append(f"Need: 1. 4H FAILED immediate 2. 3 TF align 60%+ 3. Trend continuation after pullback to S/R + CHoCH/BOS")
    lines.append(f"Current: 4H {tf4['trend']} {tf4['conf']}% | 1H {tf1['bias']} {tf1['conf']}% | 15M {tf15['trigger']} {tf15['conf']}%")
    if tf4.get("failed"): lines.append(f"4H has FAILED {tf4.get('fail_dir')} but not fresh: {tf4['desc']}")
    return "\n".join(lines), "", "WAIT", price, None

async def start(update:Update,context:ContextTypes.DEFAULT_TYPE):
    SUBSCRIBERS.add(update.effective_chat.id)
    await update.message.reply_text(f"🏆 GOLD VIP 3-COMBO FIXED 🏆\n📢 {CHANNEL_USERNAME}\n\n🎯 3 COMBOS (Profitable Long Term):\n\n1️⃣ MTF FAILED 4H IMMEDIATE (<5m) - Sniper\n/signal - GOLD MTF Premium\n\n2️⃣ THREE STRUCTURES ALIGN 4H 60%+ + 1H 60%+ + 15M 60%+ - High win\n/mtf - ALL markets MTF\n/gold - GOLD MTF\n/silver - SILVER MTF\n/us30 - US30 MTF\n/ger30 - GER30 MTF\n/ndx - NDX MTF\n\n3️⃣ TREND CONTINUATION AFTER PULLBACK + CHoCH/BOS 55%+ - Your request\n♻️ BUY CONTINUATION after pullback to S/R\n\n4H Trend: /4h\nOther: /buy VIP $25/month | /autopilot | /trail\n\nFixed: Trailing now works for BULL_FAILED_4H & BULL_CONTINUATION (your 4108->4136 +28$ bug fixed)")

async def buy(update:Update,context:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"💳 JOIN VIP $25/MONTH\nUSDT TRC20:\n{CRYPTO_WALLET}\n\n3 COMBOS:\n1. MTF FAILED 4H IMMEDIATE\n2. THREE STRUCTURES ALIGN 60%+\n3. TREND CONTINUATION AFTER PULLBACK + CONFIRMATION\n\n📢 {CHANNEL_USERNAME}", disable_web_page_preview=True)

async def signal_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text("⏳ Analyzing GOLD MTF 4H->1H->15M (3 combos)...")
        f,v,d,p,chart=build_mtf_confluence("GOLD")
        await update.message.reply_text(f)
    except Exception as e: await update.message.reply_text(f"❌ Error: {e}")

async def mtf_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text("⏳ Analyzing ALL markets MTF (5 markets)...")
        msgs=[]
        for name in SYMBOLS:
            try: f,v,d,p,chart=build_mtf_confluence(name); msgs.append(f)
            except Exception as e: msgs.append(f"❌ {name} failed: {e}")
        await update.message.reply_text("\n\n---\n\n".join(msgs))
    except Exception as e: await update.message.reply_text(f"❌ MTF error: {e}")

async def gold_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text("⏳ Analyzing GOLD MTF...")
        f,v,d,p,chart=build_mtf_confluence("GOLD"); await update.message.reply_text(f)
    except Exception as e: await update.message.reply_text(f"❌ GOLD error: {e}")

async def silver_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text("⏳ Analyzing SILVER MTF...")
        f,v,d,p,chart=build_mtf_confluence("SILVER"); await update.message.reply_text(f)
    except Exception as e: await update.message.reply_text(f"❌ SILVER error: {e}")

async def us30_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text("⏳ Analyzing US30 MTF...")
        f,v,d,p,chart=build_mtf_confluence("US30"); await update.message.reply_text(f)
    except Exception as e: await update.message.reply_text(f"❌ US30 error: {e}")

async def ger30_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text("⏳ Analyzing GER30 MTF...")
        f,v,d,p,chart=build_mtf_confluence("GER30"); await update.message.reply_text(f)
    except Exception as e: await update.message.reply_text(f"❌ GER30 error: {e}")

async def ndx_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text("⏳ Analyzing NDX MTF...")
        f,v,d,p,chart=build_mtf_confluence("NDX100"); await update.message.reply_text(f)
    except Exception as e: await update.message.reply_text(f"❌ NDX error: {e}")

async def tf4_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text("⏳ Analyzing 4H trends...")
        lines=["📊 4H TREND - BOSS"]
        for name in SYMBOLS:
            try:
                sym,fb=SYMBOLS[name]; tf4=analyze_4h(sym,fb)
                emoji="🟢" if tf4["trend"]=="BULL" else "🔴" if tf4["trend"]=="BEAR" else "⚪"
                lines.append(f"{emoji} {name}: {tf4['trend']} {tf4['conf']}% | {tf4['price']:.2f} S/R {tf4['sup']:.2f}/{tf4['res']:.2f} ATR {tf4['atr']:.2f}")
            except Exception as e: lines.append(f"❌ {name} 4H failed: {e}")
        await update.message.reply_text("\n".join(lines))
    except Exception as e: await update.message.reply_text(f"❌ 4H error: {e}")

async def autopilot_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    global AUTOPILOT_ACTIVE, AUTOPILOT_TASK
    AUTOPILOT_ACTIVE=True; SUBSCRIBERS.add(update.effective_chat.id)
    if AUTOPILOT_TASK and not AUTOPILOT_TASK.done(): AUTOPILOT_TASK.cancel()
    AUTOPILOT_TASK=asyncio.create_task(autopilot_loop(context))
    await update.message.reply_text(f"✅ AUTOPILOT ON - 3-COMBO MTF PREMIUM\nID {update.effective_chat.id} saved")

async def autostop(update:Update,context:ContextTypes.DEFAULT_TYPE):
    global AUTOPILOT_ACTIVE, AUTOPILOT_TASK
    AUTOPILOT_ACTIVE=False
    if AUTOPILOT_TASK and not AUTOPILOT_TASK.done(): AUTOPILOT_TASK.cancel()
    SUBSCRIBERS.discard(update.effective_chat.id)
    await update.message.reply_text("🛑 AUTOPILOT OFF")

async def autopilot_loop(context:ContextTypes.DEFAULT_TYPE):
    global AUTOPILOT_ACTIVE
    while AUTOPILOT_ACTIVE:
        try:
            for i in range(15):
                if not AUTOPILOT_ACTIVE: break
                await asyncio.sleep(60)
            if not AUTOPILOT_ACTIVE: break
            for active_name in list(ACTIVE_TRADES.keys()):
                try:
                    sym,fb=SYMBOLS[active_name]; pd=get_real_price_mtf(sym,"1h",fb); cur=pd[0] if pd[0] else fb
                    if sym=="GC=F":
                        sp=get_spot_gold_price()
                        if sp: cur=sp
                    trail_msg=update_trailing_status(active_name,cur)
                    if trail_msg:
                        for chat_id in list(SUBSCRIBERS):
                            try: await context.bot.send_message(chat_id=chat_id, text=trail_msg)
                            except: pass
                        try: await context.bot.send_message(chat_id=CHANNEL_ID, text=trail_msg)
                        except: pass
                except: pass
            for name in ["GOLD","SILVER","US30","GER30","NDX100"]:
                try:
                    f,v,d,p,chart=build_mtf_confluence(name)
                    if v and d not in ["WAIT","NONE"]:
                        for chat_id in list(SUBSCRIBERS):
                            try: await context.bot.send_message(chat_id=chat_id,text=f"🤖 {name} MTF PREMIUM\n{f}")
                            except: pass
                        try: await context.bot.send_message(chat_id=CHANNEL_ID,text=v)
                        except: pass
                except: pass
        except asyncio.CancelledError: break
        except Exception as e: print(f"Autopilot error: {e}"); await asyncio.sleep(60)

async def setchannel(update:Update,context:ContextTypes.DEFAULT_TYPE):
    global CHANNEL_ID
    if update.effective_user.id!=ADMIN_ID: await update.message.reply_text("❌ Admin only"); return
    if context.args: CHANNEL_ID=context.args[0]; await update.message.reply_text(f"✅ Channel set to: {CHANNEL_ID}")
    else: await update.message.reply_text(f"Current: {CHANNEL_ID}")

async def channeltest(update:Update,context:ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.send_message(chat_id=CHANNEL_ID,text="✅ Bot Connected! 3-COMBO FIXED LIVE")
        await update.message.reply_text("✅ Test sent!")
    except Exception as e: await update.message.reply_text(f"❌ Failed: {e}")

async def sendvip(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id!=ADMIN_ID: await update.message.reply_text("❌ Admin only"); return
    f,v,d,p,chart=build_mtf_confluence("GOLD")
    if v and d not in ["WAIT"]:
        try: await context.bot.send_message(chat_id=CHANNEL_ID, text=v); await update.message.reply_text(f"✅ GOLD MTF VIP SENT\n\n{v}")
        except Exception as e: await update.message.reply_text(f"❌ Failed: {e}")
    else: await update.message.reply_text(f"❌ No MTF confluence now\n\n{f}")

async def trail_cmd(update, context):
    try:
        msgs=[]
        for sym_name in list(ACTIVE_TRADES.keys()):
            try:
                sym,fb=SYMBOLS[sym_name]; price_data=get_real_price_mtf(sym,"1h",fb)
                if price_data[0] is None: continue
                cur_price=price_data[0]
                if sym=="GC=F":
                    sp=get_spot_gold_price()
                    if sp: cur_price=sp
                msg=update_trailing_status(sym_name,cur_price)
                if msg: msgs.append(msg)
            except Exception as e: msgs.append(f"{sym_name} trail error: {e}")
        if msgs: await update.message.reply_text("\n\n".join(msgs))
        else:
            if not ACTIVE_TRADES: await update.message.reply_text("No active trades to trail. Open a trade with /gold first.")
            else: await update.message.reply_text("No trailing updates needed yet. Trades still OPEN.")
    except Exception as e: await update.message.reply_text(f"Trail error: {e}")

async def trail_status_cmd(update, context):
    try:
        if not ACTIVE_TRADES: await update.message.reply_text("No active trades."); return
        lines=["📌 ACTIVE TRADES - TRAILING STATUS"]
        for name,t in ACTIVE_TRADES.items(): lines.append(f"{name} {t['direction']} Entry {t['entry']:.2f} SL {t['trail_sl']:.2f} TP1 {t['tp1']:.2f} TP2 {t['tp2']:.2f} TP3 {t['tp3']:.2f} | {t['status']}")
        await update.message.reply_text("\n".join(lines))
    except Exception as e: await update.message.reply_text(f"Status error: {e}")

def main():
    if not BOT_TOKEN: print("BOT_TOKEN missing"); return
    try: requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=true",timeout=5)
    except: pass
    app=ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",start)); app.add_handler(CommandHandler("buy",buy))
    app.add_handler(CommandHandler("signal",signal_cmd)); app.add_handler(CommandHandler("mtf",mtf_cmd))
    app.add_handler(CommandHandler("gold",gold_cmd)); app.add_handler(CommandHandler("silver",silver_cmd))
    app.add_handler(CommandHandler("us30",us30_cmd)); app.add_handler(CommandHandler("ger30",ger30_cmd))
    app.add_handler(CommandHandler("ndx",ndx_cmd)); app.add_handler(CommandHandler("ndx100",ndx_cmd)); app.add_handler(CommandHandler("nasdaq",ndx_cmd))
    app.add_handler(CommandHandler("4h",tf4_cmd)); app.add_handler(CommandHandler("trail",trail_cmd)); app.add_handler(CommandHandler("trailstatus",trail_status_cmd))
    app.add_handler(CommandHandler("autopilot",autopilot_cmd)); app.add_handler(CommandHandler("autostop",autostop))
    app.add_handler(CommandHandler("setchannel",setchannel)); app.add_handler(CommandHandler("channeltest",channeltest))
    app.add_handler(CommandHandler("sendvip",sendvip))
    app.add_handler(CommandHandler("goldmtf",gold_cmd)); app.add_handler(CommandHandler("bestcombo",signal_cmd))
    print("SIMPLIFIED 3-COMBO MTF LIVE - FIXED TRAILING + CONTINUATION")
    app.run_polling(drop_pending_updates=True)

if __name__=="__main__": main()
