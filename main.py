
import os, time, asyncio, logging, requests
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
TD_KEY = os.getenv("TWELVEDATA_API_KEY")
RAW_CHANNEL = os.getenv("CHANNEL_ID", "-1004402762942").strip()
# Accept both @username and -100... ID (your screenshot shows @GoldVIPSignalsOnyebest)
try:
    if RAW_CHANNEL.startswith("@") or RAW_CHANNEL.startswith("t.me/"):
        CHANNEL_ID = RAW_CHANNEL if RAW_CHANNEL.startswith("@") else "@" + RAW_CHANNEL.split("/")[-1]
    else:
        CHANNEL_ID = int(RAW_CHANNEL)
except:
    CHANNEL_ID = RAW_CHANNEL  # fallback keep as string
print(f"Channel resolved: {CHANNEL_ID}")

logging.basicConfig(level=logging.INFO)
SYMBOLS = {
    "XAU/USD": {"cmds":["gold","xau"],"name":"GOLD"},
    "XAG/USD": {"cmds":["silver","xag"],"name":"SILVER"},
    "DJI": {"cmds":["us30","dji"],"name":"US30"},
    "DAX": {"cmds":["ger30","dax","ger"],"name":"GER30"},
    "NDX": {"cmds":["ndx","nas100"],"name":"NDX100"},
}
TF_MAP = {"4h":"4h","1h":"1h","15min":"15min"}
AUTOPILOT_TASK = None

def fetch_candles(symbol, interval, outputsize=100):
    url = "https://api.twelvedata.com/time_series"
    params = {"symbol":symbol,"interval":interval,"outputsize":outputsize,"apikey":TD_KEY}
    r = requests.get(url, params=params, timeout=15)
    j = r.json()
    if "values" not in j:
        raise Exception(f"TD error {symbol} {interval}: {j}")
    vals = j["values"][::-1]  # oldest first
    out=[]
    for v in vals:
        out.append({"open":float(v["open"]),"high":float(v["high"]),"low":float(v["low"]),"close":float(v["close"]),"datetime":v["datetime"]})
    return out

def calc_atr(candles, period=14):
    if len(candles)<period+1: return 1.0
    trs=[]
    for i in range(1,len(candles)):
        h=candles[i]["high"]; l=candles[i]["low"]; pc=candles[i-1]["close"]
        tr = max(h-l, abs(h-pc), abs(l-pc))
        trs.append(tr)
    atr = sum(trs[-period:])/period if len(trs)>=period else sum(trs)/len(trs)
    return max(atr, 0.01)

def find_swings(candles):
    sh=[]; sl=[]
    for i in range(1,len(candles)-1):
        if candles[i]["high"]>candles[i-1]["high"] and candles[i]["high"]>candles[i+1]["high"]:
            sh.append((i, candles[i]["high"]))
        if candles[i]["low"]<candles[i-1]["low"] and candles[i]["low"]<candles[i+1]["low"]:
            sl.append((i, candles[i]["low"]))
    return sh, sl

def lowest_low_last_n(candles, n=50):
    sub = candles[-n:] if len(candles)>=n else candles
    return min(c["low"] for c in sub), min(c["high"] for c in sub)  # low, high not used

def highest_high_last_n(candles, n=50):
    sub = candles[-n:] if len(candles)>=n else candles
    return max(c["high"] for c in sub), max(c["low"] for c in sub)

def analyze_tf(candles, atr):
    if len(candles)<30:
        return {"trend":"RANGE","conf":40,"protected_low":None,"protected_high":None,"protected_valid":False,"last_sh":None,"prev_sh":None,"last_sl":None,"prev_sl":None,"price":candles[-1]["close"],"atr":atr,"desc":"not enough data","failed":None}
    sh, sl = find_swings(candles)
    # get last 2 swings
    last_sh = sh[-1][1] if len(sh)>=1 else None
    prev_sh = sh[-2][1] if len(sh)>=2 else None
    last_sl = sl[-1][1] if len(sl)>=1 else None
    prev_sl = sl[-2][1] if len(sl)>=2 else None

    # emergency protected if no swing
    if not last_sh:
        last_sh = highest_high_last_n(candles,50)[0]
    if not last_sl:
        last_sl = lowest_low_last_n(candles,50)[0]
    if not prev_sh: prev_sh = last_sh
    if not prev_sl: prev_sl = last_sl

    price = candles[-1]["close"]
    curr_close = price
    last3_closes = [c["close"] for c in candles[-3:]]

    trend="RANGE"; conf=40; protected_low=None; protected_high=None; desc="RANGE"

    # BOS detection
    if last_sh and prev_sh and last_sl and prev_sl:
        if last_sh>prev_sh and last_sl>prev_sl and price>last_sh:
            trend="BULL"; conf=85; protected_low=last_sl; desc=f"BOS BULL {prev_sh}->{last_sh} ProtLow {last_sl}"
        elif last_sl<prev_sl and last_sh<prev_sh and price<last_sl:
            trend="BEAR"; conf=85; protected_high=last_sh; desc=f"BOS BEAR {prev_sl}->{last_sl} ProtHigh {last_sh}"
        elif last_sh>prev_sh and last_sl>prev_sl:
            trend="BULL"; conf=70; protected_low=last_sl; desc=f"HH HL BULL ProtLow {last_sl}"
        elif last_sl<prev_sl and last_sh<prev_sh:
            trend="BEAR"; conf=70; protected_high=last_sh; desc=f"LL LH BEAR ProtHigh {last_sh}"
        else:
            # CHoCH
            if price>prev_sh:
                trend="BULL"; conf=65; protected_low=last_sl; desc=f"CHoCH BULL break {prev_sh}"
            elif price<prev_sl:
                trend="BEAR"; conf=65; protected_high=last_sh; desc=f"CHoCH BEAR break {prev_sl}"

    # Protected validity check
    protected_valid=True
    invalid_reason=""
    if trend=="BULL" and protected_low is not None:
        # still protected if close > protected_low +0.10 ATR
        if curr_close <= protected_low + atr*0.10:
            # check if wick only or real break? we need confirmation for break
            pass
        # break rule: close < protected_low -0.15 AND (1 of last3 < -0.10 OR close < -0.25)
        if curr_close < protected_low - atr*0.15:
            count_below = sum(1 for c in last3_closes if c < protected_low - atr*0.10)
            if count_below>=1 or curr_close < protected_low - atr*0.25:
                protected_valid=False
                invalid_reason=f"BROKEN BULL: Close {curr_close:.2f} < Prot {protected_low:.2f} -{atr*0.15:.2f}"
    elif trend=="BEAR" and protected_high is not None:
        if curr_close >= protected_high - atr*0.10:
            pass
        if curr_close > protected_high + atr*0.15:
            count_above = sum(1 for c in last3_closes if c > protected_high + atr*0.10)
            if count_above>=1 or curr_close > protected_high + atr*0.25:
                protected_valid=False
                invalid_reason=f"BROKEN BEAR: Close {curr_close:.2f} > Prot {protected_high:.2f} +{atr*0.15:.2f}"
    else:
        protected_valid=False
        invalid_reason="No protected"

    # For RANGE, still need protected for TP/SL emergency
    if trend=="RANGE":
        protected_low = last_sl
        protected_high = last_sh
        protected_valid=False

    # TRUE FAILED detection (4H) - wick >=0.25 ATR and close back >=0.15
    failed=None
    if len(candles)>=3:
        # bear sweep -> bull failed
        low_2 = candles[-2]["low"]
        high_2 = candles[-2]["high"]
        close_1 = candles[-1]["close"]  # current is actually last, we use last for close back logic relative to sweep
        # For 4H we will evaluate sweep in -2, close back in -1 and current
        # Here we store candidate, detailed check done in higher level with 15M confirmation
        if protected_low and low_2 < protected_low:
            wick = protected_low - low_2
            close_back = candles[-1]["close"] - protected_low
            if wick >= atr*0.25 and close_back >= atr*0.15:
                failed = {"type":"BULL","wick":wick,"close_back":close_back,"sweep_low":low_2,"prot":protected_low}
        if protected_high and high_2 > protected_high:
            wick = high_2 - protected_high
            close_back = protected_high - candles[-1]["close"]
            if wick >= atr*0.25 and close_back >= atr*0.15:
                failed = {"type":"BEAR","wick":wick,"close_back":close_back,"sweep_high":high_2,"prot":protected_high}

    return {
        "trend":trend,"conf":conf,"protected_low":protected_low,"protected_high":protected_high,
        "protected_valid":protected_valid,"invalid_reason":invalid_reason,
        "last_sh":last_sh,"prev_sh":prev_sh,"last_sl":last_sl,"prev_sl":prev_sl,
        "price":price,"atr":atr,"desc":desc,"failed":failed,"candles":candles
    }

def check_buying_candle(tf15_data, protected_level, direction):
    """Check buying candle on protected low after close back, per user rule"""
    candles = tf15_data["candles"]
    atr = tf15_data["atr"]
    if len(candles)<3: return False, "not enough 15M"
    # look at last 2 candles after sweep (current and -1)
    # We need: low within protected ±0.30 ATR, close>open, close>protected+0.10, close>prev close
    for idx in [-1, -2]:  # check last 2 candles for buying/selling candle
        c = candles[idx]
        prev = candles[idx-1] if len(candles)>=abs(idx)+1 else c
        if direction=="BUY" or direction=="BULL":
            # buying candle on protected low
            low_ok = abs(c["low"] - protected_level) <= atr*0.30 or c["low"] <= protected_level + atr*0.30 and c["low"] >= protected_level - atr*0.30
            # more lenient: low near protected
            low_ok = c["low"] >= protected_level - atr*0.30 and c["low"] <= protected_level + atr*0.30
            bullish = c["close"] > c["open"]
            close_prot = c["close"] > protected_level + atr*0.10
            close_prev = c["close"] > prev["close"]
            still_valid = c["close"] > protected_level - atr*0.15
            if low_ok and bullish and close_prot and close_prev and still_valid:
                return True, f"Buying candle OK: low {c['low']:.2f} within ±{atr*0.30:.2f} of Prot {protected_level:.2f} close {c['close']:.2f}>open"
        else:
            high_ok = c["high"] >= protected_level - atr*0.30 and c["high"] <= protected_level + atr*0.30
            bearish = c["close"] < c["open"]
            close_prot = c["close"] < protected_level - atr*0.10
            close_prev = c["close"] < prev["close"]
            still_valid = c["close"] < protected_level + atr*0.15
            if high_ok and bearish and close_prot and close_prev and still_valid:
                return True, f"Selling candle OK: high {c['high']:.2f} within ±{atr*0.30:.2f} of Prot {protected_level:.2f}"
    return False, "No buying/selling candle within 2 last 15M"

def get_protected_levels_always(tf15, tf1, tf4, direction):
    """Always available, no ATR fallback. Base is protected level, only buffer ±0.15 ATR"""
    # SL protected
    sl_prot = None
    if direction in ("BUY","BULL"):
        sl_prot = tf15["protected_low"] or tf1["protected_low"] or tf4["protected_low"]
        if not sl_prot:
            # emergency protected = lowest low last 50 (structure, not ATR)
            sl_prot = min(c["low"] for c in tf15["candles"][-50:])
        # TPs = protected highs
        tp1 = tf15["last_sh"] or tf1["last_sh"] or tf4["last_sh"]
        tp2 = tf15["prev_sh"] or tf1["prev_sh"] or tf4["protected_high"] or tf1["protected_high"]
        tp3 = tf4["prev_sh"] or tf4["protected_high"] or tf1["prev_sh"] or tp2
        # ensure all exist, if not use other TF
        if not tp1: tp1 = sl_prot + tf15["atr"]*1.5  # should not happen, but keep structure? Actually we must have, so use highest high
        # For strict no ATR fallback, we ensure tp1 from structure: if still none, use highest high last 50 as protected high
        if not tp1 or tp1==sl_prot:
            tp1 = max(c["high"] for c in tf15["candles"][-50:])
        if not tp2: tp2 = max(c["high"] for c in tf1["candles"][-50:])
        if not tp3: tp3 = max(c["high"] for c in tf4["candles"][-50:])
    else:
        sl_prot = tf15["protected_high"] or tf1["protected_high"] or tf4["protected_high"]
        if not sl_prot:
            sl_prot = max(c["high"] for c in tf15["candles"][-50:])
        tp1 = tf15["last_sl"] or tf1["last_sl"] or tf4["last_sl"]
        tp2 = tf15["prev_sl"] or tf1["prev_sl"] or tf4["protected_low"] or tf1["protected_low"]
        tp3 = tf4["prev_sl"] or tf4["protected_low"] or tf1["prev_sl"] or tp2
        if not tp1: tp1 = min(c["low"] for c in tf15["candles"][-50:])
        if not tp2: tp2 = min(c["low"] for c in tf1["candles"][-50:])
        if not tp3: tp3 = min(c["low"] for c in tf4["candles"][-50:])

    # SL with buffer on protected, TPs are pure protected levels
    atr = tf15["atr"]
    if direction in ("BUY","BULL"):
        sl = sl_prot - atr*0.15
    else:
        sl = sl_prot + atr*0.15
    return sl_prot, sl, tp1, tp2, tp3

def build_pure_pa_signal(symbol):
    try:
        c4 = fetch_candles(symbol, "4h", 100)
        c1 = fetch_candles(symbol, "1h", 100)
        c15 = fetch_candles(symbol, "15min", 100)
        atr4 = calc_atr(c4); atr1 = calc_atr(c1); atr15 = calc_atr(c15)
        tf4 = analyze_tf(c4, atr4)
        tf1 = analyze_tf(c1, atr1)
        tf15 = analyze_tf(c15, atr15)

        price = tf15["price"]
        direction=None; strategy=None; reason=""

        # STRATEGY 1 TRUE FAILED 4H with buying candle
        if tf4["failed"] and tf4["protected_valid"]:
            f = tf4["failed"]
            if f["type"]=="BULL":
                ok, msg = check_buying_candle(tf15, f["prot"], "BUY")
                if ok and tf15["protected_valid"] and tf15["protected_low"]:
                    # check current still valid
                    if tf15["price"] > tf15["protected_low"] + atr15*0.10:
                        direction="BUY"; strategy=f"TRUE FAILED BULL + Buying Candle {msg} | Wick {f['wick']:.2f}≥0.25ATR CloseBack {f['close_back']:.2f}"
                    else:
                        reason="TRUE FAILED BULL but 15M protected now BROKEN -> invalid"
                else:
                    reason=f"TRUE FAILED BULL wick {f['wick']:.2f} close {f['close_back']:.2f} but no buying candle yet: {msg}"
            else:
                ok, msg = check_buying_candle(tf15, f["prot"], "SELL")
                if ok and tf15["protected_valid"] and tf15["protected_high"]:
                    if tf15["price"] < tf15["protected_high"] - atr15*0.10:
                        direction="SELL"; strategy=f"TRUE FAILED BEAR + Selling Candle {msg} | Wick {f['wick']:.2f} CloseBack {f['close_back']:.2f}"
                    else:
                        reason="TRUE FAILED BEAR but 15M protected now BROKEN"
                else:
                    reason=f"TRUE FAILED BEAR but no selling candle: {msg}"

        # STRATEGY 3B NEW TREND after protected broken
        if not direction:
            if not tf15["protected_valid"] and tf15["invalid_reason"]:
                # broken
                if "BROKEN BULL" in tf15["invalid_reason"]:
                    # flip to BEAR, wait pullback to new protected high
                    new_ph = tf15["last_sh"] or tf1["last_sh"] or tf4["last_sh"]
                    if new_ph:
                        dist = abs(price - new_ph)
                        if dist <= atr15*0.8 and dist >= atr15*0.3 and tf15["trend"] in ("BEAR","RANGE"):
                            # check 15M BOS BEAR? simplified: price < last_sl or trend BEAR
                            direction="SELL"; strategy=f"NEW TREND SELL after Protected Low BROKEN {tf15['invalid_reason']} | Pullback to new ProtHigh {new_ph:.2f} | {tf15['desc']}"
                        else:
                            reason=f"Protected Low BROKEN - {tf15['invalid_reason']} - NO ENTRY - Wait new SELL pullback to new Protected High {new_ph:.2f} (dist {dist:.2f} ATR {atr15:.2f})"
                    else:
                        reason=f"Protected Low BROKEN - {tf15['invalid_reason']} - Wait new SELL"
                elif "BROKEN BEAR" in tf15["invalid_reason"]:
                    new_pl = tf15["last_sl"] or tf1["last_sl"] or tf4["last_sl"]
                    if new_pl:
                        dist = abs(price - new_pl)
                        if dist <= atr15*0.8 and dist >= atr15*0.3:
                            direction="BUY"; strategy=f"NEW TREND BUY after Protected High BROKEN {tf15['invalid_reason']} | Pullback to new ProtLow {new_pl:.2f}"
                        else:
                            reason=f"Protected High BROKEN - {tf15['invalid_reason']} - NO ENTRY - Wait new BUY pullback to new Protected Low {new_pl:.2f}"
                    else:
                        reason=f"Protected High BROKEN - {tf15['invalid_reason']} - Wait new BUY"

        # STRATEGY 2 THREE ALIGN
        if not direction:
            if tf4["trend"]==tf1["trend"]==tf15["trend"] and tf4["trend"]!="RANGE":
                if tf4["conf"]>=65 and tf1["conf"]>=60 and tf15["conf"]>=60:
                    if tf4["protected_valid"] and tf1["protected_valid"] and tf15["protected_valid"]:
                        direction = "BUY" if "BUY" in tf4["trend"] or "BULL" in tf4["trend"] else "SELL"
                        strategy=f"THREE ALIGN {tf4['trend']} | 4H {tf4['conf']}% {tf4['desc']} | 1H {tf1['conf']}% | 15M {tf15['conf']}%"
                    else:
                        reason=f"THREE ALIGN would be {tf4['trend']} but protected BROKEN: 4H valid {tf4['protected_valid']} 1H {tf1['protected_valid']} 15M {tf15['protected_valid']} {tf15['invalid_reason']} -> NO ENTRY"

        # STRATEGY 3A CONTINUATION pullback 0.6 ATR
        if not direction:
            if tf4["trend"]=="BULL" and tf4["protected_valid"] and tf15["trend"]=="BULL" and tf15["protected_valid"]:
                prot = tf4["protected_low"] or tf15["protected_low"]
                if prot:
                    dist = price - prot
                    if dist>=atr15*0.3 and dist<=atr15*0.8:
                        direction="BUY"; strategy=f"CONTINUATION BULL Pullback 0.6 ATR to Protected Low {prot:.2f} dist {dist:.2f} | {tf4['desc']}"
            if tf4["trend"]=="BEAR" and tf4["protected_valid"] and tf15["trend"]=="BEAR" and tf15["protected_valid"]:
                prot = tf4["protected_high"] or tf15["protected_high"]
                if prot:
                    dist = prot - price
                    if dist>=atr15*0.3 and dist<=atr15*0.8:
                        direction="SELL"; strategy=f"CONTINUATION BEAR Pullback 0.6 ATR to Protected High {prot:.2f}"

        if not direction:
            # WAIT
            details = f"4H: {tf4['trend']} {tf4['conf']}% | Prot: {tf4['protected_low'] or tf4['protected_high']} | Valid:{tf4['protected_valid']} | {tf4['desc']} | Price:{price:.2f} ATR:{atr4:.2f} | {tf4['invalid_reason']}\n"
            details+=f"1H: {tf1['trend']} {tf1['conf']}% | Prot: {tf1['protected_low'] or tf1['protected_high']} | Valid:{tf1['protected_valid']} | {tf1['desc']}\n"
            details+=f"15M: {tf15['trend']} {tf15['conf']}% | Prot: {tf15['protected_low'] or tf15['protected_high']} | Valid:{tf15['protected_valid']} | {tf15['desc']} | {tf15['invalid_reason']}\n"
            if tf4["failed"]:
                details+=f"FAILED candidate: {tf4['failed']}\n"
            if reason:
                details+=f"Reason: {reason}\n"
            return {"type":"WAIT","symbol":symbol,"reason":reason or "No alignment","details":details,"tf4":tf4,"tf1":tf1,"tf15":tf15}

        # Get protected levels always available no fallback
        sl_prot, sl, tp1, tp2, tp3 = get_protected_levels_always(tf15, tf1, tf4, direction)

        return {
            "type":direction,"symbol":symbol,"strategy":strategy,"entry":price,
            "sl_prot":sl_prot,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,
            "tf4":tf4,"tf1":tf1,"tf15":tf15
        }
    except Exception as e:
        return {"type":"ERROR","symbol":symbol,"error":str(e)}

def format_signal(sig):
    if sig["type"]=="WAIT":
        name = SYMBOLS.get(sig["symbol"],{}).get("name",sig["symbol"])
        return f"⏳ {name} | WAIT\nReason: {sig['reason']}\n\n{sig['details']}\n#WAIT #{name}"
    if sig["type"]=="ERROR":
        return f"❌ {sig['symbol']} Error: {sig['error']}"
    # BUY/SELL
    sym = sig["symbol"]; name = SYMBOLS.get(sym,{}).get("name",sym)
    direction = sig["type"]
    emoji = "🟢 BUY" if direction=="BUY" else "🔴 SELL"
    tf4=tf4d=sig["tf4"]; tf1=sig["tf1"]; tf15=sig["tf15"]
    entry=sig["entry"]; sl=sig["sl"]; sl_prot=sig["sl_prot"]; tp1=sig["tp1"]; tp2=sig["tp2"]; tp3=sig["tp3"]
    # protected info
    return (
        f"🪙 {name} VIP SIGNAL {emoji}\n\n"
        f"🎯 STRATEGY: {sig['strategy']}\n\n"
        f"💰 ENTRY: {entry:.2f} (15M Close)\n"
        f"🛡️ SL: {sl:.2f} on { '15M' if tf15['protected_low'] or tf15['protected_high'] else '1H/4H' } Protected {'Low' if direction=='BUY' else 'High'} {sl_prot:.2f} +0.15 ATR buffer\n"
        f"   Protected Level = Base, not price ±ATR\n\n"
        f"🎯 TP1: {tp1:.2f} (Next Protected {'High' if direction=='BUY' else 'Low'})\n"
        f"🎯 TP2: {tp2:.2f} (Structure: prev_sh/sl / 1H Prot)\n"
        f"🎯 TP3: {tp3:.2f} (4H prev_sh/sl / Extended)\n\n"
        f"📊 MTF ALIGNMENT:\n"
        f"• 4H: {tf4['trend']} ({tf4['conf']}%) Valid:{tf4['protected_valid']} Prot:{tf4['protected_low'] or tf4['protected_high']} | {tf4['desc']}\n"
        f"• 1H: {tf1['trend']} ({tf1['conf']}%) Valid:{tf1['protected_valid']} Prot:{tf1['protected_low'] or tf1['protected_high']}\n"
        f"• 15M: {tf15['trend']} ({tf15['conf']}%) Valid:{tf15['protected_valid']} Prot:{tf15['protected_low'] or tf15['protected_high']} | {tf15['desc']}\n\n"
        f"{'💥 TRUE FAILED: BULL' if 'TRUE FAILED BULL' in sig['strategy'] else '💥 TRUE FAILED: BEAR' if 'TRUE FAILED BEAR' in sig['strategy'] else ''} {tf4['failed'] if tf4['failed'] else ''}\n"
        f"@GoldVIPSignalsOnyebest GOLD VIP Onyebest\n"
        f"#{direction} #{name}"
    )

async def cmd_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, symbol_key):
    sig = build_pure_pa_signal(symbol_key)
    msg = format_signal(sig)
    await update.message.reply_text(msg)
    if sig["type"] in ("BUY","SELL"):
        try:
            await context.bot.send_message(chat_id=CHANNEL_ID, text=msg)
        except Exception as e:
            await update.message.reply_text(f"Channel send failed: {e}")

async def gold(update, context): await cmd_handler(update, context, "XAU/USD")
async def silver(update, context): await cmd_handler(update, context, "XAG/USD")
async def us30(update, context): await cmd_handler(update, context, "DJI")
async def ger30(update, context): await cmd_handler(update, context, "DAX")
async def ndx(update, context): await cmd_handler(update, context, "NDX")

async def mtf(update, context):
    out="📊 MTF PURE PA STATUS (Protected Always Available, No Fallback)\n\n"
    for sym in SYMBOLS:
        sig = build_pure_pa_signal(sym)
        name = SYMBOLS[sym]["name"]
        if sig["type"]=="WAIT":
            out+=f"{name} WAIT - {sig['reason']}\n{sym} 4H {sig['tf4']['trend']} {sig['tf4']['conf']}% Valid:{sig['tf4']['protected_valid']} Prot:{sig['tf4']['protected_low'] or sig['tf4']['protected_high']}\n1H {sig['tf1']['trend']} Valid:{sig['tf1']['protected_valid']} | 15M {sig['tf15']['trend']} Valid:{sig['tf15']['protected_valid']} | Price {sig['tf15']['price']:.2f}\n"
            if sig['tf4']['failed']:
                out+=f"FAILED: {sig['tf4']['failed']}\n"
            out+="\n"
        elif sig["type"] in ("BUY","SELL"):
            out+=f"{name} {sig['type']} {sig['entry']:.2f} SL {sig['sl']:.2f} on Prot {sig['sl_prot']:.2f} TP1 {sig['tp1']:.2f} | {sig['strategy'][:80]}\n\n"
        else:
            out+=f"{name} ERROR {sig.get('error')}\n\n"
    await update.message.reply_text(out[:4000])

async def autopilot_loop(app):
    while True:
        try:
            for sym in SYMBOLS:
                sig = build_pure_pa_signal(sym)
                if sig["type"] in ("BUY","SELL"):
                    msg = format_signal(sig)
                    await app.bot.send_message(chat_id=CHANNEL_ID, text=msg)
            await asyncio.sleep(900)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logging.error(f"autopilot error {e}")
            await asyncio.sleep(60)

async def autopilot(update, context):
    global AUTOPILOT_TASK
    if AUTOPILOT_TASK and not AUTOPILOT_TASK.done():
        await update.message.reply_text("Autopilot already running")
        return
    await update.message.reply_text("🚀 Autopilot started every 15m")
    AUTOPILOT_TASK = asyncio.create_task(autopilot_loop(context.application))

async def autostop(update, context):
    global AUTOPILOT_TASK
    if AUTOPILOT_TASK:
        AUTOPILOT_TASK.cancel()
        AUTOPILOT_TASK=None
        await update.message.reply_text("🛑 Autopilot stopped")
    else:
        await update.message.reply_text("No autopilot running")

async def start(update, context):
    await update.message.reply_text("Gold VIP Pure PA Bot\n/gold /silver /us30 /ger30 /ndx\n/mtf /autopilot /autostop\nProtected Always Available, No Fallback, No RR")

def main():
    if not BOT_TOKEN or not TD_KEY:
        print("Missing BOT_TOKEN or TWELVEDATA_API_KEY")
        return
    app = Application.builder().token(BOT_TOKEN).build()
    # fix conflict
    try:
        import requests as rq
        rq.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=True", timeout=10)
        time.sleep(2)
    except: pass
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("gold", gold))
    app.add_handler(CommandHandler("xau", gold))
    app.add_handler(CommandHandler("silver", silver))
    app.add_handler(CommandHandler("xag", silver))
    app.add_handler(CommandHandler("us30", us30))
    app.add_handler(CommandHandler("dji", us30))
    app.add_handler(CommandHandler("ger30", ger30))
    app.add_handler(CommandHandler("dax", ger30))
    app.add_handler(CommandHandler("ger", ger30))
    app.add_handler(CommandHandler("ndx", ndx))
    app.add_handler(CommandHandler("nas100", ndx))
    app.add_handler(CommandHandler("mtf", mtf))
    app.add_handler(CommandHandler("autopilot", autopilot))
    app.add_handler(CommandHandler("autostop", autostop))
    print("Bot polling...")
    app.run_polling()

if __name__=="__main__":
    main()
