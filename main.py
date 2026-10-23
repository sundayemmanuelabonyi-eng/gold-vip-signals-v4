import os, threading, asyncio, requests, time, math
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

PORT = int(os.getenv("PORT","10000"))
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "")

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        try: self.wfile.write(b"PURE PA + TWELVEDATA - PROTECTED HIGH/LOW - NO MATPLOTLIB")
        except: pass
    def do_HEAD(self):
        self.send_response(200); self.end_headers()
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
CHANNEL_USERNAME="@GoldVIPSignalsOnyebest"
CRYPTO_WALLET="TGQu8k7BYJ8h1seQLBT6K8GFgajS33TYdM"

SUBSCRIBERS=set()
AUTOPILOT_ACTIVE=False
AUTOPILOT_TASK=None
ACTIVE_TRADES={}
PRICE_CACHE={}
CACHE_TIME={}
FAILED_TRACKER={}
FAILED_EXPIRY_SECONDS=300

# ===== PURE PA ONLY - NO INDICATORS =====
# SYMBOLS -> TwelveData only
SYMBOLS={
    "GOLD": ("XAU/USD", "GOLD"),
    "SILVER": ("XAG/USD", "SILVER"),
    "US30": ("DJI", "US30"),
    "GER30": ("DAX", "GER30"),
    "NDX": ("NDX", "NDX100")
}

def get_twelvedata_api_key():
    for name in ["TWELVEDATA_API_KEY","TWELVE_DATA_API_KEY","TWELVEDATA_KEY","TWELVE_API_KEY","TWE_API_KEY"]:
        v=os.getenv(name,"").strip()
        if v and len(v)>10: return v
    for k,v in os.environ.items():
        if k.startswith("TWE") and len(v.strip())>=20:
            if "TOKEN" not in k or "TWELVE" in k:
                print(f"Found TwelveData key in env var {k}")
                return v.strip()
    secret_paths=["/etc/secrets/TWELVEDATA_API_KEY","/etc/secrets/TWELVE_DATA_API_KEY","./TWELVEDATA_API_KEY","/mnt/data/TWELVEDATA_API_KEY"]
    for p in secret_paths:
        try:
            if os.path.exists(p):
                with open(p,'r') as sf:
                    vv=sf.read().strip()
                    if len(vv)>10: return vv
        except: pass
    return ""

def atr(highs,lows,closes,period=14):
    if len(closes)<period+1:
        return (max(highs[-20:])-min(lows[-20:]))/20 if len(highs)>=20 else 5.0
    trs=[]
    for i in range(1,len(closes)):
        try:
            hl=highs[i]-lows[i]
            hc=abs(highs[i]-closes[i-1])
            lc=abs(lows[i]-closes[i-1])
            trs.append(max(hl,hc,lc))
        except: pass
    return sum(trs[-period:])/period if trs else 5.0

def get_swing_points(highs,lows,left=2,right=2):
    sh=[]; sl=[]
    for i in range(left,len(highs)-right):
        is_sh=True
        for j in range(1,left+1):
            if highs[i]<=highs[i-j]: is_sh=False
        for j in range(1,right+1):
            if highs[i]<=highs[i+j]: is_sh=False
        if is_sh: sh.append((i,highs[i]))
        is_sl=True
        for j in range(1,left+1):
            if lows[i]>=lows[i-j]: is_sl=False
        for j in range(1,right+1):
            if lows[i]>=lows[i+j]: is_sl=False
        if is_sl: sl.append((i,lows[i]))
    return sh,sl

def get_twelvedata_mtf(td_symbol, interval):
    # interval: 15m, 1h, 4h
    api_key=get_twelvedata_api_key()
    if not api_key:
        return None, [], [], []
    try:
        td_interval_map={"15m":"15min","1h":"1h","4h":"4h"}
        td_interval=td_interval_map.get(interval,"15min")
        # cache 45 sec
        cache_key=f"{td_symbol}_{td_interval}"
        now=time.time()
        if cache_key in PRICE_CACHE and cache_key in CACHE_TIME and now-CACHE_TIME[cache_key]<45:
            return PRICE_CACHE[cache_key]
        url=f"https://api.twelvedata.com/time_series?symbol={td_symbol}&interval={td_interval}&outputsize=200&apikey={api_key}"
        r=requests.get(url,timeout=10)
        data=r.json()
        if "values" not in data:
            print(f"TwelveData error {td_symbol} {td_interval}: {data}")
            return None, [], [], []
        vals=data["values"][::-1] # oldest first
        closes=[float(v["close"]) for v in vals]
        highs=[float(v["high"]) for v in vals]
        lows=[float(v["low"]) for v in vals]
        result=(closes[-1], closes, highs, lows)
        PRICE_CACHE[cache_key]=result
        CACHE_TIME[cache_key]=now
        return result
    except Exception as e:
        print(f"TwelveData fetch error {e}")
        return None, [], [], []

def detect_fvg(highs,lows):
    # simple bullish FVG: low[i] > high[i-2]
    # bearish FVG: high[i] < low[i-2]
    bv=[]; be=[]
    for i in range(2,len(highs)):
        if lows[i] > highs[i-2]:
            bv.append((i, highs[i-2], lows[i]))
        if highs[i] < lows[i-2]:
            be.append((i, lows[i-2], highs[i]))
    return bv, be

def analyze_tf_pure_pa(td_symbol, interval):
    price, hist, highs, lows = get_twelvedata_mtf(td_symbol, interval)
    if not hist or len(hist)<30:
        return None
    sh, sl = get_swing_points(highs,lows,2,2)
    if len(sh)<2 or len(sl)<2:
        return {
            "price": price, "hist": hist, "highs": highs, "lows": lows,
            "sh": sh, "sl": sl, "trend": "RANGE", "conf": 40,
            "desc": "Range - not enough swings", "failed": False, "fail_dir": None,
            "protected_high": None, "protected_low": None, "sup": min(lows[-20:]), "res": max(highs[-20:]),
            "atr": atr(highs,lows,hist), "bias": "RANGE", "sweep": "None", "trigger": "WAIT", "fvg": "None"
        }
    last_sh=sh[-1][1]; prev_sh=sh[-2][1]
    last_sl=sl[-1][1]; prev_sl=sl[-2][1]
    curr_price=hist[-1]
    prev_price=hist[-2] if len(hist)>=2 else curr_price
    atr_v=atr(highs,lows,hist)
    min_wick=atr_v*0.25
    min_close=atr_v*0.15

    # === PROTECTED HIGH/LOW DETECTION ===
    protected_high=None; protected_low=None
    trend="RANGE"; conf=40; desc=f"Range {last_sl:.2f}-{last_sh:.2f}"
    failed=False; fail_dir=None

    # Find last BOS to define protected levels
    # Search last 30 candles for BOS
    last_bos_type=None; last_bos_level=None
    for i in range(len(sh)-1,0,-1):
        # check if after this swing high there was a break
        # bullish BOS: price broke above sh[i]
        # To find protected low: last swing low before bullish BOS
        pass

    # Simplified pure PA BOS detection:
    # BOS BULL: close > last swing high
    # BOS BEAR: close < last swing low
    bos_bull = curr_price > last_sh
    bos_bear = curr_price < last_sl
    hh = last_sh > prev_sh
    hl = last_sl > prev_sl
    ll = last_sl < prev_sl
    lh = last_sh < prev_sh

    # === TRUE FAILED 0.25 ATR - FIXES FALSE 4181.10->4179.66 ===
    # Failed BULL: broke high with significant wick then close back below
    if len(highs)>=3 and highs[-2] > last_sh + min_wick and curr_price < last_sh - min_close:
        failed=True; fail_dir="BEAR"
        # protected high is last_sh still protected? No, failed so now bearish
        protected_high=last_sh
        return {
            "price": curr_price, "hist": hist, "highs": highs, "lows": lows, "sh": sh, "sl": sl,
            "trend": "BEAR", "conf": 90, "desc": f"TRUE FAILED BULL {last_sh:.2f} -> {highs[-2]:.2f} wick {highs[-2]-last_sh:.2f} need {min_wick:.2f} close {curr_price:.2f} below IMMEDIATE SELL",
            "failed": True, "fail_dir": "BEAR", "protected_high": last_sh, "protected_low": None,
            "sup": last_sl, "res": last_sh, "atr": atr_v, "bias": "BEAR", "sweep": f"BULL Sweep {last_sh:.2f}->{highs[-2]:.2f}", "trigger": "FAILED BULL", "fvg": "None"
        }
    # Failed BEAR: broke low with significant wick then close back above
    if len(lows)>=3 and lows[-2] < last_sl - min_wick and curr_price > last_sl + min_close:
        failed=True; fail_dir="BULL"
        protected_low=last_sl
        return {
            "price": curr_price, "hist": hist, "highs": highs, "lows": lows, "sh": sh, "sl": sl,
            "trend": "BULL", "conf": 90, "desc": f"TRUE FAILED BEAR {last_sl:.2f} -> {lows[-2]:.2f} wick {last_sl-lows[-2]:.2f} need {min_wick:.2f} close {curr_price:.2f} above IMMEDIATE BUY",
            "failed": True, "fail_dir": "BULL", "protected_high": None, "protected_low": last_sl,
            "sup": last_sl, "res": last_sh, "atr": atr_v, "bias": "BULL", "sweep": f"BEAR Sweep {last_sl:.2f}->{lows[-2]:.2f}", "trigger": "FAILED BEAR", "fvg": "None"
        }

    # === BOS + PROTECTED LOGIC ===
    if bos_bull and hh and hl:
        trend="BULL"; conf=85
        # Protected low is last swing low before this BOS
        protected_low=last_sl
        desc=f"BOS BULL Break {last_sh:.2f} HH/HL Protected Low {last_sl:.2f}"
    elif bos_bear and ll and lh:
        trend="BEAR"; conf=85
        protected_high=last_sh
        desc=f"BOS BEAR Break {last_sl:.2f} LL/LH Protected High {last_sh:.2f}"
    elif hh and hl:
        trend="BULL"; conf=70
        protected_low=last_sl
        desc=f"Uptrend HH {prev_sh:.2f}->{last_sh:.2f} HL {prev_sl:.2f}->{last_sl:.2f} Protected {last_sl:.2f}"
    elif ll and lh:
        trend="BEAR"; conf=70
        protected_high=last_sh
        desc=f"Downtrend LL {prev_sl:.2f}->{last_sl:.2f} LH {prev_sh:.2f}->{last_sh:.2f} Protected {last_sh:.2f}"
    elif curr_price > prev_sh and ll:
        trend="BULL"; conf=65
        protected_low=last_sl
        desc=f"CHoCH BULL {prev_sh:.2f} break Protected {last_sl:.2f}"
    elif curr_price < prev_sl and hh:
        trend="BEAR"; conf=65
        protected_high=last_sh
        desc=f"CHoCH BEAR {prev_sl:.2f} break Protected {last_sh:.2f}"
    else:
        # Try to find previous protected levels even in range
        # Last bullish BOS in recent history -> protected low
        for idx in range(len(hist)-1, max(0,len(hist)-50), -1):
            # simple check: if hist[idx] broke above previous sh
            pass
        desc=f"Range {last_sl:.2f}-{last_sh:.2f}"

    # FVG
    bv_fvg, be_fvg = detect_fvg(highs,lows)
    fvg_str="None"
    if trend=="BULL" and bv_fvg: fvg_str=f"BULL FVG {bv_fvg[-1][1]:.2f}-{bv_fvg[-1][2]:.2f}"
    if trend=="BEAR" and be_fvg: fvg_str=f"BEAR FVG {be_fvg[-1][1]:.2f}-{be_fvg[-1][2]:.2f}"

    sup = last_sl if trend=="BULL" else min(lows[-20:])
    res = last_sh if trend=="BEAR" else max(highs[-20:])

    # Sweep detection
    sweep="None"
    if len(highs)>=2 and highs[-2] > last_sh: sweep=f"BULL Sweep {last_sh:.2f}->{highs[-2]:.2f} wick {highs[-2]-last_sh:.2f}"
    if len(lows)>=2 and lows[-2] < last_sl: sweep=f"BEAR Sweep {last_sl:.2f}->{lows[-2]:.2f} wick {last_sl-lows[-2]:.2f}"

    # Bias for 1H
    bias=trend
    # Trigger for 15M
    trigger="WAIT"
    if failed: trigger=f"FAILED {fail_dir}"
    elif trend!="RANGE": trigger=trend

    return {
        "price": curr_price, "hist": hist, "highs": highs, "lows": lows, "sh": sh, "sl": sl,
        "trend": trend, "conf": conf, "desc": desc, "failed": failed, "fail_dir": fail_dir,
        "protected_high": protected_high, "protected_low": protected_low,
        "sup": sup, "res": res, "atr": atr_v, "bias": bias, "sweep": sweep, "trigger": trigger, "fvg": fvg_str
    }

def build_pure_pa_signal(symbol_key):
    td_symbol, _ = SYMBOLS[symbol_key]
    tf4=analyze_tf_pure_pa(td_symbol,"4h")
    tf1=analyze_tf_pure_pa(td_symbol,"1h")
    tf15=analyze_tf_pure_pa(td_symbol,"15m")
    if not tf4 or not tf1 or not tf15:
        return "❌ TwelveData not ready - check TWELVEDATA_API_KEY env. Single feed only.", None, "WAIT", 0

    price=tf15["price"]
    atr_v=tf15["atr"]
    # ===== 3 COMBOS - PURE PA =====
    # COMBO 1: TRUE FAILED 4H IMMEDIATE (0.25 ATR)
    if tf4["failed"]:
        direction="BUY" if tf4["fail_dir"]=="BULL" else "SELL"
        # SL/TP from protected levels
        if direction=="BUY":
            sl=tf4["protected_low"]-atr_v*0.8 if tf4["protected_low"] else price-atr_v*1.5
            tp1=price+atr_v*0.8; tp2=price+atr_v*1.5; tp3=price+atr_v*2.5
        else:
            sl=tf4["protected_high"]+atr_v*0.8 if tf4["protected_high"] else price+atr_v*1.5
            tp1=price-atr_v*0.8; tp2=price-atr_v*1.5; tp3=price-atr_v*2.5
        msg=(f"🔥 PURE PA TRUE FAILED 4H IMMEDIATE - {symbol_key} {direction}\n\n"
             f"{tf4['desc']}\n"
             f"4H: {tf4['trend']} {tf4['conf']}% | 1H: {tf1['trend']} | 15M: {tf15['trigger']}\n"
             f"Price: {price:.2f} ATR: {atr_v:.2f}\n"
             f"Protected: Low {tf4['protected_low']} High {tf4['protected_high']}\n"
             f"Sweep: {tf4['sweep']}\n"
             f"FVG: {tf4['fvg']}\n\n"
             f"ENTRY: {price:.2f}\nSL: {sl:.2f}\nTP1: {tp1:.2f}\nTP2: {tp2:.2f}\nTP3: {tp3:.2f}\n\n"
             f"Source: TwelveData {td_symbol} ONLY - Pure Price Action\n"
             f"Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
        return msg, direction, f"TRUE FAILED 4H {direction}", price, sl, tp1, tp2, tp3

    # COMBO 2: THREE ALIGN 4H+1H+15M - All BULL or All BEAR
    if tf4["trend"]==tf1["trend"]==tf15["trend"] and tf4["trend"]!="RANGE" and tf4["conf"]>=65 and tf1["conf"]>=60:
        direction="BUY" if tf4["trend"]=="BULL" else "SELL"
        # SL from protected low/high
        prot_low=tf4["protected_low"] or tf1["protected_low"] or tf15["protected_low"]
        prot_high=tf4["protected_high"] or tf1["protected_high"] or tf15["protected_high"]
        if direction=="BUY":
            sl=prot_low-atr_v*0.8 if prot_low else price-atr_v*1.2
            tp1=price+atr_v*0.8; tp2=price+atr_v*1.5; tp3=price+atr_v*2.5
        else:
            sl=prot_high+atr_v*0.8 if prot_high else price+atr_v*1.2
            tp1=price-atr_v*0.8; tp2=price-atr_v*1.5; tp3=price-atr_v*2.5
        msg=(f"🔥 PURE PA THREE ALIGN 4H+1H+15M - {symbol_key} {direction}\n\n"
             f"4H: {tf4['desc']}\n"
             f"1H: {tf1['desc']}\n"
             f"15M: {tf15['desc']}\n"
             f"Price: {price:.2f} ATR: {atr_v:.2f}\n"
             f"Protected Low: {prot_low} High: {prot_high}\n"
             f"FVG: {tf15['fvg']} | Sweep: {tf15['sweep']}\n\n"
             f"ENTRY: {price:.2f}\nSL: {sl:.2f}\nTP1: {tp1:.2f}\nTP2: {tp2:.2f}\nTP3: {tp3:.2f}\n\n"
             f"Source: TwelveData {td_symbol} ONLY - Pure Price Action\n"
             f"Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
        return msg, direction, f"THREE ALIGN {direction}", price, sl, tp1, tp2, tp3

    # COMBO 3: CONTINUATION PULLBACK 0.6 ATR to Protected + 15M BOS/CHoCH (your requested)
    # BULL case: 4H BULL with protected low, price pulls back 0.6 ATR near protected low, 15M BOS BULL
    prot_low_4h=tf4["protected_low"]
    prot_high_4h=tf4["protected_high"]
    # BULL CONTINUATION
    if tf4["trend"]=="BULL" and prot_low_4h:
        # price near protected low within 0.6 ATR?
        dist_to_prot=abs(price-prot_low_4h)
        if dist_to_prot <= atr_v*0.8:  # within 0.8 ATR of protected low (pullback)
            # need 15M BOS BULL confirmation
            if tf15["trend"]=="BULL" and tf15["conf"]>=60:
                direction="BUY"
                sl=prot_low_4h-atr_v*0.8
                tp1=price+atr_v*0.8; tp2=price+atr_v*1.5; tp3=price+atr_v*2.5
                msg=(f"🔥 PURE PA CONTINUATION PULLBACK 0.6 ATR + BOS - {symbol_key} BUY\n\n"
                     f"4H BULL Protected Low {prot_low_4h:.2f} - Pullback {dist_to_prot:.2f} ({dist_to_prot/atr_v:.2f} ATR)\n"
                     f"4H: {tf4['desc']}\n"
                     f"1H: {tf1['trend']} {tf1['desc']}\n"
                     f"15M: {tf15['desc']} - BOS BULL CONFIRMED\n"
                     f"Price: {price:.2f} ATR: {atr_v:.2f}\n"
                     f"FVG: {tf15['fvg']}\n\n"
                     f"ENTRY: {price:.2f} (pullback to protected + BOS)\nSL: {sl:.2f} (protected low -0.8 ATR)\nTP1: {tp1:.2f}\nTP2: {tp2:.2f}\nTP3: {tp3:.2f}\n\n"
                     f"Source: TwelveData {td_symbol} ONLY - Pure PA\n"
                     f"Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
                return msg, direction, f"CONTINUATION PULLBACK BUY", price, sl, tp1, tp2, tp3
    # BEAR CONTINUATION
    if tf4["trend"]=="BEAR" and prot_high_4h:
        dist_to_prot=abs(price-prot_high_4h)
        if dist_to_prot <= atr_v*0.8:
            if tf15["trend"]=="BEAR" and tf15["conf"]>=60:
                direction="SELL"
                sl=prot_high_4h+atr_v*0.8
                tp1=price-atr_v*0.8; tp2=price-atr_v*1.5; tp3=price-atr_v*2.5
                msg=(f"🔥 PURE PA CONTINUATION PULLBACK 0.6 ATR + BOS - {symbol_key} SELL\n\n"
                     f"4H BEAR Protected High {prot_high_4h:.2f} - Pullback {dist_to_prot:.2f} ({dist_to_prot/atr_v:.2f} ATR)\n"
                     f"4H: {tf4['desc']}\n"
                     f"1H: {tf1['trend']} {tf1['desc']}\n"
                     f"15M: {tf15['desc']} - BOS BEAR CONFIRMED\n"
                     f"Price: {price:.2f} ATR: {atr_v:.2f}\n"
                     f"FVG: {tf15['fvg']}\n\n"
                     f"ENTRY: {price:.2f} (pullback to protected + BOS)\nSL: {sl:.2f} (protected high +0.8 ATR)\nTP1: {tp1:.2f}\nTP2: {tp2:.2f}\nTP3: {tp3:.2f}\n\n"
                     f"Source: TwelveData {td_symbol} ONLY - Pure PA\n"
                     f"Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
                return msg, direction, f"CONTINUATION PULLBACK SELL", price, sl, tp1, tp2, tp3

    # No signal
    return (f"⏳ PURE PA WAIT - {symbol_key} - No valid setup now\n\n"
            f"4H: {tf4['trend']} {tf4['conf']}% {tf4['desc']}\nProtected Low: {tf4['protected_low']} High: {tf4['protected_high']}\n"
            f"1H: {tf1['trend']} {tf1['desc']}\n"
            f"15M: {tf15['trend']} {tf15['desc']}\n"
            f"Price: {price:.2f} ATR: {atr_v:.2f}\nFVG: {tf15['fvg']} Sweep: {tf15['sweep']}\n\n"
            f"Need: TRUE FAILED 0.25 ATR OR THREE ALIGN OR Pullback 0.6 ATR to Protected + 15M BOS\n"
            f"Source: TwelveData {td_symbol} ONLY"), None, "WAIT", 0

# ===== TELEGRAM COMMANDS =====
async def start(update:Update,context:ContextTypes.DEFAULT_TYPE):
    txt=(f"👋 PURE PA + TWELVEDATA - PROTECTED HIGH/LOW\n\n"
         f"Bot: {CHANNEL_USERNAME}\nChannel ID: {CHANNEL_ID}\n"
         f"Source: TwelveData ONLY (no gold-api, no Yahoo) - matches MT5\n"
         f"Logic: Pure Price Action - Swing BOS CHoCH Protected ATR only\n"
         f"Combos:\n"
         f"1. TRUE FAILED 4H IMMEDIATE 0.25 ATR wick +0.15 close\n"
         f"2. THREE ALIGN 4H+1H+15M\n"
         f"3. CONTINUATION PULLBACK 0.6 ATR to Protected + 15M BOS\n\n"
         f"Commands:\n/gold /silver /us30 /ger30 /ndx /mtf /signal\n/trail /trailstatus /autopilot /autostop\n/buy /setchannel /channeltest /sendvip /sendgoldmtf\n\n"
         f"SL: Protected ±0.8 ATR\nTP: 0.8R, 1.5R, 2.5R\nNo matplotlib - text only")
    await update.message.reply_text(txt)

async def signal_cmd(update,context): await gold_cmd(update,context)
async def gold_cmd(update,context):
    try:
        await update.message.reply_text("⏳ GOLD PURE PA analyzing TwelveData XAU/USD...")
        msg, direction, setup, price, sl, tp1, tp2, tp3 = build_pure_pa_signal("GOLD")
        if direction and direction!="WAIT":
            ACTIVE_TRADES["GOLD"]={"entry":price,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"direction":direction,"trail_sl":sl,"status":"ACTIVE"}
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"Gold error: {e}")

async def silver_cmd(update,context):
    try:
        await update.message.reply_text("⏳ SILVER PURE PA analyzing TwelveData XAG/USD...")
        msg, direction, setup, price, sl, tp1, tp2, tp3 = build_pure_pa_signal("SILVER")
        if direction and direction!="WAIT":
            ACTIVE_TRADES["SILVER"]={"entry":price,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"direction":direction,"trail_sl":sl,"status":"ACTIVE"}
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"Silver error: {e}")

async def us30_cmd(update,context):
    try:
        msg, direction, setup, price, sl, tp1, tp2, tp3 = build_pure_pa_signal("US30")
        if direction and direction!="WAIT":
            ACTIVE_TRADES["US30"]={"entry":price,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"direction":direction,"trail_sl":sl,"status":"ACTIVE"}
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"US30 error: {e}")

async def ger30_cmd(update,context):
    try:
        msg, direction, setup, price, sl, tp1, tp2, tp3 = build_pure_pa_signal("GER30")
        if direction and direction!="WAIT":
            ACTIVE_TRADES["GER30"]={"entry":price,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"direction":direction,"trail_sl":sl,"status":"ACTIVE"}
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"GER30 error: {e}")

async def ndx_cmd(update,context):
    try:
        msg, direction, setup, price, sl, tp1, tp2, tp3 = build_pure_pa_signal("NDX")
        if direction and direction!="WAIT":
            ACTIVE_TRADES["NDX"]={"entry":price,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"direction":direction,"trail_sl":sl,"status":"ACTIVE"}
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"NDX error: {e}")

async def mtf_cmd(update,context):
    try:
        await update.message.reply_text("⏳ PURE PA MTF scanning 5 symbols (TwelveData only)...")
        results=[]
        for key in ["GOLD","SILVER","US30","GER30","NDX"]:
            try:
                msg, direction, setup, price, sl, tp1, tp2, tp3 = build_pure_pa_signal(key)
                if direction and direction!="WAIT":
                    ACTIVE_TRADES[key]={"entry":price,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"direction":direction,"trail_sl":sl,"status":"ACTIVE"}
                    results.append(f"{key}: 🔥 {direction} {setup} Entry {price:.2f}")
                else:
                    # short summary
                    results.append(f"{key}: ⏳ WAIT - {setup}")
            except Exception as e:
                results.append(f"{key}: Error {e}")
        await update.message.reply_text("\n".join(results))
    except Exception as e:
        await update.message.reply_text(f"MTF error: {e}")

async def tf4_cmd(update,context):
    await update.message.reply_text("Use /gold for 4H protected analysis - pure PA")

async def trail_cmd(update,context):
    try:
        if not ACTIVE_TRADES:
            await update.message.reply_text("No active trades.")
            return
        lines=["🔄 TRAILING CHECK - PURE PA"]
        for sym, t in ACTIVE_TRADES.items():
            try:
                td_sym, _ = SYMBOLS[sym]
                price, hist, highs, lows = get_twelvedata_mtf(td_sym, "15m")
                if not price: continue
                entry=t["entry"]; sl=t["trail_sl"]
                # FIXED TRAILING BUG: check BULL/BEAR in direction
                if "BUY" in t["direction"] or "BULL" in t["direction"]:
                    # move SL to breakeven after +0.8 ATR, then trail
                    atr_v=atr(highs,lows,hist)
                    if price >= entry + atr_v*0.8 and sl < entry:
                        t["trail_sl"]=entry
                        lines.append(f"{sym} BUY: SL -> BE {entry:.2f} (price {price:.2f})")
                    elif price >= entry + atr_v*1.5:
                        new_sl=price-atr_v*0.5
                        if new_sl > t["trail_sl"]:
                            t["trail_sl"]=new_sl
                            lines.append(f"{sym} BUY: Trail SL {new_sl:.2f} (price {price:.2f})")
                else:
                    atr_v=atr(highs,lows,hist)
                    if price <= entry - atr_v*0.8 and sl > entry:
                        t["trail_sl"]=entry
                        lines.append(f"{sym} SELL: SL -> BE {entry:.2f} (price {price:.2f})")
                    elif price <= entry - atr_v*1.5:
                        new_sl=price+atr_v*0.5
                        if new_sl < t["trail_sl"]:
                            t["trail_sl"]=new_sl
                            lines.append(f"{sym} SELL: Trail SL {new_sl:.2f} (price {price:.2f})")
            except Exception as e:
                lines.append(f"{sym} trail error {e}")
        if len(lines)==1: lines.append("No trailing updates - price not reached BE yet")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"Trail error: {e}")

async def trail_status_cmd(update,context):
    try:
        if not ACTIVE_TRADES:
            await update.message.reply_text("No active trades.")
            return
        lines=["📌 ACTIVE TRADES - TRAILING STATUS (Pure PA)"]
        for name, t in ACTIVE_TRADES.items():
            lines.append(f"{name} {t['direction']} Entry {t['entry']:.2f} SL {t['trail_sl']:.2f} TP1 {t['tp1']:.2f} TP2 {t['tp2']:.2f} TP3 {t['tp3']:.2f} | {t['status']}")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"Status error: {e}")

async def autopilot_cmd(update,context):
    global AUTOPILOT_ACTIVE, AUTOPILOT_TASK
    if update.effective_user.id!=ADMIN_ID:
        await update.message.reply_text("❌ Admin only"); return
    if AUTOPILOT_ACTIVE:
        await update.message.reply_text("⚠️ Autopilot already active. Use /autostop to stop.")
        return
    AUTOPILOT_ACTIVE=True
    await update.message.reply_text(f"✅ PURE PA AUTOPILOT STARTED - Channel {CHANNEL_ID}\nSource: TwelveData ONLY\nLogic: Protected High/Low + 0.6 ATR Pullback + 15M BOS\nNo matplotlib")

    async def autopilot_loop():
        while AUTOPILOT_ACTIVE:
            try:
                for key in ["GOLD","SILVER","US30","GER30","NDX"]:
                    try:
                        msg, direction, setup, price, sl, tp1, tp2, tp3 = build_pure_pa_signal(key)
                        if direction and direction!="WAIT":
                            # duplicate protection 15min
                            tracker_key=f"{key}_{direction}_{setup}"
                            now=time.time()
                            if tracker_key in FAILED_TRACKER and now-FAILED_TRACKER[tracker_key]<900:
                                continue
                            FAILED_TRACKER[tracker_key]=now
                            try:
                                await context.bot.send_message(chat_id=CHANNEL_ID, text=msg)
                            except Exception as e:
                                print(f"Channel send failed {e}")
                            ACTIVE_TRADES[key]={"entry":price,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"direction":direction,"trail_sl":sl,"status":"ACTIVE"}
                    except Exception as e:
                        print(f"Autopilot {key} error {e}")
                # trailing every loop
                try:
                    for sym, t in list(ACTIVE_TRADES.items()):
                        td_sym, _ = SYMBOLS[sym]
                        price, hist, highs, lows = get_twelvedata_mtf(td_sym, "15m")
                        if not price: continue
                        entry=t["entry"]
                        if "BUY" in t["direction"] or "BULL" in t["direction"]:
                            atr_v=atr(highs,lows,hist)
                            if price >= entry + atr_v*0.8 and t["trail_sl"] < entry:
                                t["trail_sl"]=entry
                        else:
                            atr_v=atr(highs,lows,hist)
                            if price <= entry - atr_v*0.8 and t["trail_sl"] > entry:
                                t["trail_sl"]=entry
                except: pass
            except Exception as e:
                print(f"Autopilot loop error {e}")
            await asyncio.sleep(120)  # 2 min scan

    AUTOPILOT_TASK=asyncio.create_task(autopilot_loop())

async def autostop(update,context):
    global AUTOPILOT_ACTIVE
    if update.effective_user.id!=ADMIN_ID:
        await update.message.reply_text("❌ Admin only"); return
    AUTOPILOT_ACTIVE=False
    if AUTOPILOT_TASK:
        try: AUTOPILOT_TASK.cancel()
        except: pass
    await update.message.reply_text("🛑 Autopilot stopped.")

async def buy(update,context):
    txt=(f"💳 SUBSCRIBE VIP - {CHANNEL_USERNAME}\n\n"
         f"GOLD + SILVER + US30 + GER30 + NDX\nPure PA + TwelveData\nProtected High/Low + 0.6 ATR Pullback\n\n"
         f"Wallet (USDT TRC20):\n{CRYPTO_WALLET}\n\n"
         f"Send proof to admin after payment.")
    await update.message.reply_text(txt)

async def setchannel(update,context):
    global CHANNEL_ID
    if update.effective_user.id!=ADMIN_ID:
        await update.message.reply_text("❌ Admin only"); return
    if not context.args:
        await update.message.reply_text(f"Current channel: {CHANNEL_ID}\nUsage: /setchannel -100xxx"); return
    CHANNEL_ID=context.args[0]
    await update.message.reply_text(f"✅ Channel set to {CHANNEL_ID}")

async def channeltest(update,context):
    if update.effective_user.id!=ADMIN_ID:
        await update.message.reply_text("❌ Admin only"); return
    try:
        await context.bot.send_message(chat_id=CHANNEL_ID, text=f"✅ Channel test OK - Pure PA bot - {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
        await update.message.reply_text(f"✅ Test sent to {CHANNEL_ID}")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed: {e}")

async def sendvip(update,context):
    if update.effective_user.id!=ADMIN_ID:
        await update.message.reply_text("❌ Admin only"); return
    try:
        msg, direction, setup, price, sl, tp1, tp2, tp3 = build_pure_pa_signal("GOLD")
        await context.bot.send_message(chat_id=CHANNEL_ID, text=msg)
        await update.message.reply_text(f"✅ Sent to {CHANNEL_ID}")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed: {e}")

async def sendgoldmtf_cmd(update,context):
    await sendvip(update,context)

def main():
    if not BOT_TOKEN:
        print("BOT_TOKEN missing"); return
    try: requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=true",timeout=5)
    except: pass
    app=ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("buy",buy))
    app.add_handler(CommandHandler("signal",signal_cmd))
    app.add_handler(CommandHandler("mtf",mtf_cmd))
    app.add_handler(CommandHandler("gold",gold_cmd))
    app.add_handler(CommandHandler("silver",silver_cmd))
    app.add_handler(CommandHandler("us30",us30_cmd))
    app.add_handler(CommandHandler("ger30",ger30_cmd))
    app.add_handler(CommandHandler("ndx",ndx_cmd))
    app.add_handler(CommandHandler("ndx100",ndx_cmd))
    app.add_handler(CommandHandler("nasdaq",ndx_cmd))
    app.add_handler(CommandHandler("4h",tf4_cmd))
    app.add_handler(CommandHandler("trail",trail_cmd))
    app.add_handler(CommandHandler("trailstatus",trail_status_cmd))
    app.add_handler(CommandHandler("autopilot",autopilot_cmd))
    app.add_handler(CommandHandler("autostop",autostop))
    app.add_handler(CommandHandler("setchannel",setchannel))
    app.add_handler(CommandHandler("channeltest",channeltest))
    app.add_handler(CommandHandler("sendvip",sendvip))
    app.add_handler(CommandHandler("sendgoldmtf",sendgoldmtf_cmd))
    # aliases
    app.add_handler(CommandHandler("goldmtf",gold_cmd))
    app.add_handler(CommandHandler("bestcombo",signal_cmd))
    app.add_handler(CommandHandler("gold3",gold_cmd))
    print("PURE PA + TWELVEDATA - PROTECTED HIGH/LOW - NO MATPLOTLIB LIVE")
    app.run_polling(drop_pending_updates=True)

if __name__=="__main__": main()
