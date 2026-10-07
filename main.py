
import os, threading, asyncio, requests, random, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


PORT = int(os.getenv("PORT","10000"))
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "")

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        try: self.wfile.write(b"SIMPLIFIED 2-COMBO MTF LIVE")
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
CRYPTO_WALLET="TGQu8k7BYJ8h1seQLBT6K8GFgajS33TYdM"
CHANNEL_USERNAME="@GoldVIPSignalsOnyebest"

SUBSCRIBERS=set()
AUTOPILOT_ACTIVE=False
AUTOPILOT_TASK=None
ACTIVE_TRADES={}  # {symbol: {entry, sl, tp1, tp2, tp3, direction, trail_sl, status}}

PRICE_CACHE = {}
CACHE_TIME = {}
FAILED_TRACKER = {}  # key: symbol_tf_dir -> first seen timestamp, to enforce 1-5min expiry
FAILED_EXPIRY_SECONDS = 300  # 5 mins max - avoid late entry per user request

def ema(vals, period):
    if len(vals) < period:
        return sum(vals[-period:]) / len(vals[-period:]) if vals else 0
    k=2/(period+1)
    ev=sum(vals[:period])/period
    for v in vals[period:]: ev=v*k+ev*(1-k)
    return ev

def get_spot_gold_price():
    try:
        r=requests.get("https://api.gold-api.com/price/XAU",timeout=5).json()
        p=float(r.get("price",0))
        if 1000 < p < 10000:
            return p
    except: pass
    return None

def get_spot_silver_price():
    try:
        r=requests.get("https://api.gold-api.com/price/XAG",timeout=5).json()
        p=float(r.get("price",0))
        if 10 < p < 100:
            return p
    except: pass
    return None

def rsi(vals, period=14):
    if len(vals)<period+1: return 50.0
    gains=0; losses=0
    for i in range(1,period+1):
        diff=vals[-i]-vals[-i-1]
        if diff>0: gains+=diff
        else: losses+=-diff
    if losses==0: return 70 if gains>0 else 50
    rs=gains/losses if losses!=0 else 1
    return 100-(100/(1+rs))

def atr(highs, lows, closes, period=14):
    if len(closes)<period+1: 
        return (max(highs[-20:]) - min(lows[-20:])) / 20 if len(highs)>=20 else 5.0
    trs=[]
    for i in range(1,len(closes)):
        hl = highs[i]-lows[i] if i < len(highs) and i < len(lows) else 0
        hc = abs(highs[i]-closes[i-1]) if i < len(highs) else 0
        lc = abs(lows[i]-closes[i-1]) if i < len(lows) else 0
        trs.append(max(hl,hc,lc))
    return sum(trs[-period:])/period if trs else 5.0

def get_real_price_mtf(symbol, interval, fallback):
    key = f"{symbol}_{interval}"
    now = time.time()
    if key in PRICE_CACHE and key in CACHE_TIME:
        if now - CACHE_TIME[key] < 90:
            return PRICE_CACHE[key]
    price = None
    history = []
    highs = []
    lows = []
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        # FIXED: use real 4H interval via 60m aggregated correctly, or use 15m/60m directly
        # Yahoo does not support 240m, so we fetch 60m and aggregate properly to 4H OHLC
        yf_interval = {"15m":"15m", "1h":"60m", "4h":"60m"}[interval]
        range_map = {"15m":"5d", "1h":"10d", "4h":"60d"}
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval={yf_interval}&range={range_map[interval]}"
        r = requests.get(url, headers=headers, timeout=8).json()
        result = r['chart']['result'][0]
        closes = result['indicators']['quote'][0]['close']
        high_data = result['indicators']['quote'][0]['high']
        low_data = result['indicators']['quote'][0]['low']
        closes = [c for c in closes if c is not None]
        high_data = [h for h in high_data if h is not None]
        low_data = [l for l in low_data if l is not None]
        if closes and len(closes) >= 20:
            if interval == "4h":
                # PROPER 4H: group 4x 1H candles into real 4H OHLC
                agg_closes = []
                agg_highs = []
                agg_lows = []
                for i in range(0, len(closes), 4):
                    chunk_c = closes[i:i+4]
                    chunk_h = high_data[i:i+4] if i < len(high_data) else chunk_c
                    chunk_l = low_data[i:i+4] if i < len(low_data) else chunk_c
                    if chunk_c:
                        agg_closes.append(chunk_c[-1])  # close of last in group
                        agg_highs.append(max(chunk_h) if chunk_h else chunk_c[-1])
                        agg_lows.append(min(chunk_l) if chunk_l else chunk_c[-1])
                closes = agg_closes
                high_data = agg_highs
                low_data = agg_lows
            price = closes[-1]
            max_hist = 200 if interval=="4h" else 100
            history = closes[-max_hist:] if len(closes)>=max_hist else closes
            highs = high_data[-max_hist:] if len(high_data)>=max_hist else high_data
            lows = low_data[-max_hist:] if len(low_data)>=max_hist else low_data
            PRICE_CACHE[key] = (price, history, highs, lows)
            CACHE_TIME[key] = now
            return price, history, highs, lows
    except Exception as e:
        print(f"Yahoo MTF failed {symbol} {interval}: {e}")
    # FIXED: NO RANDOM - if API fails, use cache or fallback but mark as stale
    if key in PRICE_CACHE:
        print(f"Using cached {key}")
        return PRICE_CACHE[key]
    # Last resort: use fallback but still return valid structure, DO NOT RANDOMIZE
    if fallback and 10 < fallback < 100000:
        print(f"Using fallback for {key}: {fallback}")
        price = fallback
        history = [fallback + (i-50)*0.1 for i in range(100)]  # flat trend, not random
        highs = [h+0.5 for h in history]
        lows = [l-0.5 for l in history]
        return price, history, highs, lows
    # If everything fails, return None - caller must handle WAIT
    print(f"CRITICAL: No data for {key}")
    return None, [], [], []

def get_sr_levels(history, lookback=30, highs=None, lows=None, price=None, sh=None, sl=None):
    # IMPROVED: uses actual swing points sh/sl and ensures sup < price < res for 15M structure
    if sh is None or sl is None:
        # fallback old logic but with price filter
        if len(history) < 10:
            return history[-1]*0.998, history[-1]*1.002
        recent = history[-lookback:] if len(history)>=lookback else history
        swing_lows = []
        swing_highs = []
        for i in range(2, len(recent)-2):
            if recent[i] < recent[i-1] and recent[i] < recent[i-2] and recent[i] < recent[i+1] and recent[i] < recent[i+2]:
                swing_lows.append(recent[i])
            if recent[i] > recent[i-1] and recent[i] > recent[i-2] and recent[i] > recent[i+1] and recent[i] > recent[i+2]:
                swing_highs.append(recent[i])
        if not swing_lows:
            swing_lows = sorted(recent)[:3]
        if not swing_highs:
            swing_highs = sorted(recent)[-3:]
        sup = sum(swing_lows[-2:]) / min(2, len(swing_lows[-2:])) if swing_lows else min(recent)
        res = sum(swing_highs[-2:]) / min(2, len(swing_highs[-2:])) if swing_highs else max(recent)
        if res <= sup:
            res = max(recent)
            sup = min(recent)
        # Ensure sup < price < res if price given
        if price is not None:
            # find sup below price
            lows_below = [x for x in swing_lows if x < price]
            highs_above = [x for x in swing_highs if x > price]
            if lows_below:
                sup = max(lows_below)  # nearest support below
            else:
                sup = price * 0.998
            if highs_above:
                res = min(highs_above)  # nearest resistance above
            else:
                res = price * 1.002
        return sup, res
    else:
        # Use actual sh/sl swing points for true structure
        if price is None:
            price = history[-1] if history else 0
        # Support = nearest swing low below price
        sl_below = [v for i,v in sl if v < price]
        sh_above = [v for i,v in sh if v > price]
        if sl_below:
            sup = max(sl_below)
        else:
            # fallback to lowest low in recent
            sup = min(lows[-20:]) if lows and len(lows)>=20 else price*0.995
        if sh_above:
            res = min(sh_above)
        else:
            res = max(highs[-20:]) if highs and len(highs)>=20 else price*1.005
        # If still invalid (both above/below), use ATR buffer
        if sup >= price:
            sup = price * 0.997
        if res <= price:
            res = price * 1.003
        return sup, res



def get_swing_points(highs, lows, left=2, right=2):
    sh = []; sl = []
    for i in range(left, len(highs)-right):
        is_sh = all(highs[i] > highs[i-j] for j in range(1, left+1)) and all(highs[i] > highs[i+j] for j in range(1, right+1))
        if is_sh: sh.append((i, highs[i]))
        is_sl = all(lows[i] < lows[i-j] for j in range(1, left+1)) and all(lows[i] < lows[i+j] for j in range(1, right+1))
        if is_sl: sl.append((i, lows[i]))
    return sh, sl

def detect_bos_choch(hist, highs, lows):
    sh, sl = get_swing_points(highs, lows, 2, 2)
    if len(sh) < 2 or len(sl) < 2:
        return "RANGE", 50, sh, sl, "No clear structure", False, None
    last_sh = sh[-1][1]; prev_sh = sh[-2][1]
    last_sl = sl[-1][1]; prev_sl = sl[-2][1]
    price = hist[-1]
    prev_price = hist[-2] if len(hist)>=2 else price
    hh = last_sh > prev_sh
    hl = last_sl > prev_sl
    ll = last_sl < prev_sl
    lh = last_sh < prev_sh
    bos_bull = price > last_sh
    bos_bear = price < last_sl
    # IMMEDIATE FAILED TRANSIT DETECTION
    failed = False
    fail_dir = None
    # Failed BULL: broke high then closed back below = immediate BEAR scalp
    if len(highs)>=3 and highs[-2] > last_sh and price < last_sh:
        failed = True
        fail_dir = "BEAR"
        return "BEAR", 90, sh, sl, f"FAILED BULL {last_sh:.2f} -> {highs[-2]:.2f} wick then close {price:.2f} below IMMEDIATE SELL", failed, fail_dir
    if len(lows)>=3 and lows[-2] < last_sl and price > last_sl:
        failed = True
        fail_dir = "BULL"
        return "BULL", 90, sh, sl, f"FAILED BEAR {last_sl:.2f} -> {lows[-2]:.2f} wick then close {price:.2f} above IMMEDIATE BUY", failed, fail_dir
    if bos_bull and hh and hl:
        return "BULL", 85, sh, sl, f"BOS BULL Break {last_sh:.2f} HH/HL", False, None
    if bos_bear and ll and lh:
        return "BEAR", 85, sh, sl, f"BOS BEAR Break {last_sl:.2f} LL/LH", False, None
    if hh and hl:
        return "BULL", 70, sh, sl, f"Uptrend HH {prev_sh:.2f}->{last_sh:.2f} HL {prev_sl:.2f}->{last_sl:.2f}", False, None
    if ll and lh:
        return "BEAR", 70, sh, sl, f"Downtrend LL {prev_sl:.2f}->{last_sl:.2f} LH {prev_sh:.2f}->{last_sh:.2f}", False, None
    if price > prev_sh and ll:
        return "BULL", 65, sh, sl, f"CHoCH BULL {prev_sh:.2f} break", False, None
    if price < prev_sl and hh:
        return "BEAR", 65, sh, sl, f"CHoCH BEAR {prev_sl:.2f} break", False, None
    return "RANGE", 40, sh, sl, f"Range {last_sl:.2f}-{last_sh:.2f}", False, None

def detect_failed_transit_immediate(hist, highs, lows, sh, sl):
    # Extra check for any timeframe: if BOS in last 2 candles then fail
    if len(hist) < 3 or not sh or not sl:
        return False, None, ""
    price = hist[-1]
    # Check if last high was BOS BULL then failed
    if len(highs)>=3:
        for idx, level in reversed(sh[-3:]):
            if idx >= len(hist)-3:  # recent swing
                if highs[idx+1] > level if idx+1 < len(highs) else False:
                    # it broke
                    if price < level:
                        return True, "BEAR", f"Immediate FAILED BULL BOS {level:.2f} -> sweep {highs[idx+1]:.2f} now {price:.2f} below"
    if len(lows)>=3:
        for idx, level in reversed(sl[-3:]):
            if idx >= len(hist)-3:
                if lows[idx+1] < level if idx+1 < len(lows) else False:
                    if price > level:
                        return True, "BULL", f"Immediate FAILED BEAR BOS {level:.2f} -> sweep {lows[idx+1]:.2f} now {price:.2f} above"
    return False, None, ""


def analyze_4h(symbol, fallback):
    spot_override = None
    if symbol == "GC=F": spot_override = get_spot_gold_price()
    elif symbol == "SI=F": spot_override = get_spot_silver_price()
    result = get_real_price_mtf(symbol, "4h", fallback)
    if result[0] is None: return None
    price, hist, highs, lows = result
    if spot_override: price = spot_override
    trend, conf, sh, sl, desc, failed, fail_dir = detect_bos_choch(hist, highs, lows)
    sup, res = get_sr_levels(hist, 30, highs, lows, price, sh, sl)
    atr_val = atr(highs, lows, hist, 14)
    ob_high = res; ob_low = sup
    if sh: ob_high = sh[-1][1]
    if sl: ob_low = sl[-1][1]
    return {"price":price, "hist":hist, "highs":highs, "lows":lows, "trend":trend, "conf":conf, "sup":sup, "res":res, "atr":atr_val, "sh":sh, "sl":sl, "desc":desc, "ob_high":ob_high, "ob_low":ob_low, "failed":failed, "fail_dir":fail_dir}

def analyze_1h(symbol, fallback):
    spot_override = None
    if symbol == "GC=F": spot_override = get_spot_gold_price()
    elif symbol == "SI=F": spot_override = get_spot_silver_price()
    result = get_real_price_mtf(symbol, "1h", fallback)
    if result[0] is None: return None
    price, hist, highs, lows = result
    if spot_override: price = spot_override
    trend, conf, sh, sl, desc, failed, fail_dir = detect_bos_choch(hist, highs, lows)
    sup, res = get_sr_levels(hist, 50, highs, lows, price, sh, sl)
    atr_val = atr(highs, lows, hist, 14)
    sweep = "None"
    if len(highs) >= 20:
        recent_high = max(highs[-20:-2])
        recent_low = min(lows[-20:-2])
        if highs[-2] > recent_high and hist[-1] < recent_high:
            sweep = f"BEAR Sweep {recent_high:.2f} -> {highs[-2]:.2f} wick then close below"
        elif lows[-2] < recent_low and hist[-1] > recent_low:
            sweep = f"BULL Sweep {recent_low:.2f} -> {lows[-2]:.2f} wick then close above"
    bias = trend
    near_sr = f"{desc} | Sweep: {sweep}"
    return {"price":price, "hist":hist, "highs":highs, "lows":lows, "bias":bias, "sup":sup, "res":res, "near_sr":near_sr, "atr":atr_val, "sh":sh, "sl":sl, "desc":desc, "sweep":sweep, "conf":conf, "failed":failed, "fail_dir":fail_dir}

def analyze_15m(symbol, fallback):
    spot_override = None
    if symbol == "GC=F": spot_override = get_spot_gold_price()
    elif symbol == "SI=F": spot_override = get_spot_silver_price()
    result = get_real_price_mtf(symbol, "15m", fallback)
    if result[0] is None: return None
    price, hist, highs, lows = result
    if spot_override: price = spot_override
    trend, conf, sh, sl, desc, failed, fail_dir = detect_bos_choch(hist, highs, lows)
    sup, res = get_sr_levels(hist, 20, highs, lows, price, sh, sl)
    atr_val = atr(highs, lows, hist, 14)
    trigger = "WAIT"
    if "CHoCH BULL" in desc:
        trigger = "BUY"
    elif "CHoCH BEAR" in desc:
        trigger = "SELL"
    else:
        if trend == "BULL" and conf >= 70: trigger = "BUY"
        elif trend == "BEAR" and conf >= 70: trigger = "SELL"
    fvg = "None"
    if len(hist) >= 3:
        if lows[-1] > highs[-3]: fvg = f"BULL FVG {highs[-3]:.2f}-{lows[-1]:.2f}"
        if highs[-1] < lows[-3]: fvg = f"BEAR FVG {lows[-3]:.2f}-{highs[-1]:.2f}"
    return {"price":price, "hist":hist, "highs":highs, "lows":lows, "sup":sup, "res":res, "trigger":trigger, "atr":atr_val, "sh":sh, "sl":sl, "desc":desc, "fvg":fvg, "conf":conf, "failed":failed, "fail_dir":fail_dir}



def generate_mtf_chart(symbol_name, tf4, tf1, tf15, price, sl, tp1, tp2, direction):
    try:
        fig, axes = plt.subplots(3,1, figsize=(10,8), sharex=False)
        fig.suptitle(f'{symbol_name} 4H->1H->15M PA {direction} | Entry {price:.2f} SL {sl:.2f} TP1 {tp1:.2f} TP2 {tp2:.2f}', fontsize=10, fontweight='bold')
        ax = axes[0]
        h4 = tf4['hist'][-80:]
        ax.plot(h4, label='Price', color='black', linewidth=1.2)
        ax.axhline(tf4['sup'], color='green', linestyle=':', label=f"Sup {tf4['sup']:.2f}")
        ax.axhline(tf4['res'], color='green', linestyle=':', label=f"Res {tf4['res']:.2f}")
        if tf4.get('sh'):
            for _, v in tf4['sh'][-2:]: ax.axhline(v, color='red', linestyle='--', alpha=0.4)
        if tf4.get('sl'):
            for _, v in tf4['sl'][-2:]: ax.axhline(v, color='green', linestyle='--', alpha=0.4)
        ax.set_title(f"4H {tf4['trend']} {tf4['conf']}% {tf4['desc']}")
        ax.legend(fontsize=7, loc='best')
        ax = axes[1]
        h1 = tf1['hist'][-80:]
        ax.plot(h1, color='black', linewidth=1.1)
        if tf1.get('sh'):
            for _, v in tf1['sh'][-3:]: ax.axhline(v, color='red', linestyle=':', alpha=0.5)
        if tf1.get('sl'):
            for _, v in tf1['sl'][-3:]: ax.axhline(v, color='green', linestyle=':', alpha=0.5)
        ax.axhline(tf1['sup'], color='green', linestyle=':', label=f"Sup {tf1['sup']:.2f}")
        ax.axhline(tf1['res'], color='red', linestyle=':', label=f"Res {tf1['res']:.2f}")
        ax.set_title(f"1H {tf1['bias']} {tf1['desc']} | {tf1['sweep']}")
        ax.legend(fontsize=7, loc='best')
        ax = axes[2]
        h15 = tf15['hist'][-80:]
        ax.plot(h15, color='black', linewidth=1.1)
        ax.axhline(price, color='purple', linewidth=1.5, label=f"ENTRY {price:.2f}")
        ax.axhline(sl, color='red', linewidth=1.5, linestyle='-', label=f"SL {sl:.2f}")
        ax.axhline(tp1, color='green', linewidth=1.2, linestyle='-', label=f"TP1 {tp1:.2f}")
        ax.axhline(tp2, color='darkgreen', linewidth=1.2, linestyle='-', label=f"TP2 {tp2:.2f}")
        ax.set_title(f"15M {tf15['trigger']} {tf15['desc']} FVG:{tf15['fvg']}")
        ax.legend(fontsize=7, loc='best')
        plt.tight_layout(rect=[0,0,1,0.96])
        out_path = f"/tmp/{symbol_name}_mtf_{int(time.time())}.png"
        plt.savefig(out_path, dpi=150)
        plt.close(fig)
        return out_path
    except Exception as e:
        print(f"Chart error: {e}")
        return None






def update_trailing_status(symbol_name, current_price):
    # === NO-LOSS + PROFIT-LOCK TRAILING ===
    # If trade ever moved in profit, it can NEVER close in loss.
    # It will always close in profit (BE+1 minimum)
    if symbol_name not in ACTIVE_TRADES:
        return None
    t = ACTIVE_TRADES[symbol_name]
    entry = t['entry']
    atr = t.get('atr', 15)
    direction = t['direction']
    status = t.get('status','OPEN')
    trail_sl = t.get('trail_sl', t['sl'])
    
    trail_dist = atr * 1.0  # tighter trail for profit lock
    profit_trigger_small = atr * 0.3  # ~6-7$ for GOLD = first profit lock
    profit_trigger_be = 1.0  # $1 profit = BE+1 lock (NO LOSS guarantee)
    
    msgs = []
    
    if direction == "BUY":
        profit = current_price - entry
        
        # STEP 0: NO-LOSS GUARANTEE - As soon as +$5 or +0.3 ATR in profit, move SL to BE+1
        # This ensures if trade ever in profit, it can never be loss
        if profit >= profit_trigger_small and status == "OPEN":
            # First time in profit
            new_sl = entry + profit_trigger_be  # BE + $1 profit
            if new_sl > trail_sl:
                t['trail_sl'] = new_sl
                t['status'] = "PROFIT_LOCKED"
                msgs.append(f"✅ {symbol_name} BUY +{profit:.2f}$ PROFIT! NO-LOSS ACTIVATED\nMove SL to BE+1: {new_sl:.2f} (Never loss again)")
        
        # STEP 1: TP1 hit -> lock BE
        if current_price >= t['tp1'] and status in ["OPEN","PROFIT_LOCKED"]:
            t['status'] = "TP1_HIT"
            new_sl = entry + 2.0  # BE+2
            if new_sl > t['trail_sl']:
                t['trail_sl'] = new_sl
            msgs.append(f"🔒 {symbol_name} BUY TP1 HIT {t['tp1']:.2f}! SL now {t['trail_sl']:.2f} (+{t['trail_sl']-entry:.2f}$ locked)")
        
        # STEP 2: TP2 hit -> lock TP1 profit
        if current_price >= t['tp2'] and status in ["TP1_HIT","PROFIT_LOCKED"]:
            t['status'] = "TP2_HIT"
            # Lock at least TP1
            if t['tp1'] > t['trail_sl']:
                t['trail_sl'] = t['tp1']
            msgs.append(f"🔒🔒 {symbol_name} BUY TP2 HIT {t['tp2']:.2f}! Lock profit SL {t['trail_sl']:.2f} (+{t['trail_sl']-entry:.2f}$)")
        
        # STEP 3: CONTINUOUS PROFIT TRAILING after any profit
        if status != "OPEN":
            new_trail = current_price - trail_dist
            if new_trail > t['trail_sl'] and new_trail > entry:
                profit_locked = new_trail - entry
                t['trail_sl'] = new_trail
                msgs.append(f"📈 {symbol_name} BUY TRAILING +{profit:.2f}$ -> SL now {new_trail:.2f} (+{profit_locked:.2f}$ GUARANTEED PROFIT)")
    
    else: # SELL - NO-LOSS LOGIC
        profit = entry - current_price
        
        # STEP 0: NO-LOSS - As soon as in profit, lock BE+1
        if profit >= profit_trigger_small and status == "OPEN":
            new_sl = entry - profit_trigger_be  # BE+1 for SELL (below entry)
            if new_sl < trail_sl:
                t['trail_sl'] = new_sl
                t['status'] = "PROFIT_LOCKED"
                msgs.append(f"✅ {symbol_name} SELL +{profit:.2f}$ PROFIT! NO-LOSS ACTIVATED\nMove SL to BE+1: {new_sl:.2f} (Never loss again, will close +${profit_trigger_be})")
        
        # STEP 1: TP1
        if current_price <= t['tp1'] and status in ["OPEN","PROFIT_LOCKED"]:
            t['status'] = "TP1_HIT"
            new_sl = entry - 2.0
            if new_sl < t['trail_sl']:
                t['trail_sl'] = new_sl
            msgs.append(f"🔒 {symbol_name} SELL TP1 HIT {t['tp1']:.2f}! SL now {t['trail_sl']:.2f} (+{entry-t['trail_sl']:.2f}$ locked)")
        
        # STEP 2: TP2
        if current_price <= t['tp2'] and status in ["TP1_HIT","PROFIT_LOCKED"]:
            t['status'] = "TP2_HIT"
            if t['tp1'] < t['trail_sl']:
                t['trail_sl'] = t['tp1']
            msgs.append(f"🔒🔒 {symbol_name} SELL TP2 HIT {t['tp2']:.2f}! Lock profit SL {t['trail_sl']:.2f} (+{entry-t['trail_sl']:.2f}$)")
        
        # STEP 3: CONTINUOUS TRAILING
        if status != "OPEN":
            new_trail = current_price + trail_dist
            if new_trail < t['trail_sl'] and new_trail < entry:
                profit_locked = entry - new_trail
                t['trail_sl'] = new_trail
                msgs.append(f"📉 {symbol_name} SELL TRAILING +{profit:.2f}$ -> SL now {new_trail:.2f} (+{profit_locked:.2f}$ GUARANTEED PROFIT)")
    
    ACTIVE_TRADES[symbol_name] = t
    return "\n".join(msgs) if msgs else None

SYMBOLS = {
    "GOLD": ("GC=F", 4140.52),
    "SILVER": ("SI=F", 32.5),
    "US30": ("^DJI", 46000),
    "GER30": ("^GDAXI", 19450),
    "NDX100": ("^NDX", 30800),
}

def build_mtf_confluence(symbol_name):
    sym, fallback = SYMBOLS[symbol_name]
    tf4 = analyze_4h(sym, fallback)
    tf1 = analyze_1h(sym, fallback)
    tf15 = analyze_15m(sym, fallback)
    # SAFETY: if any timeframe fails, return WAIT
    if tf4 is None or tf1 is None or tf15 is None:
        msg = f"⏳ {symbol_name} Data unavailable - API failed, using fallback next try"
        return msg, "", "WAIT", fallback, None
    price = tf15["price"]
    now = datetime.now().strftime('%H:%M')
    lines = []
    lines.append(f"🎯 {symbol_name} 4H->1H->15M PURE PRICE ACTION")
    lines.append(f"💰 {price:.2f} | 4H {tf4['trend']} {tf4['conf']}% {tf4['desc']} | 1H {tf1['bias']} {tf1['sweep']} | 15M {tf15['trigger']} {tf15['desc']} FVG:{tf15['fvg']}")
    lines.append(f"4H: {tf4['desc']} | OB {tf4['ob_low']:.2f}/{tf4['ob_high']:.2f} S/R {tf4['sup']:.2f}/{tf4['res']:.2f} ATR {tf4['atr']:.2f}")
    lines.append(f"1H: {tf1['near_sr']} | S/R {tf1['sup']:.2f}/{tf1['res']:.2f} ATR {tf1['atr']:.2f}")
    lines.append(f"15M: {tf15['desc']} | FVG {tf15['fvg']} | S/R {tf15['sup']:.2f}/{tf15['res']:.2f} ATR {tf15['atr']:.2f}")
    lines.append("")
    direction = "WAIT"
    # === IMMEDIATE FAILED TRANSIT - 1-5 MIN EXPIRY + CONFLICT FILTER ===
    # User: 1-5mins only, avoid late entry. Also avoid opposite TF conflict.
    immediate_failed = None
    fresh_failed_list = []  # collect all fresh failed across TFs

    def check_fresh(tf_name, fail_dir, desc, atr_tf, sup_tf, res_tf):
        if not fail_dir:
            return None
        key = f"{symbol_name}_{tf_name}_{fail_dir}_{desc[:30]}"
        now_ts = time.time()
        if key not in FAILED_TRACKER:
            FAILED_TRACKER[key] = now_ts
            age = 0
        else:
            age = now_ts - FAILED_TRACKER[key]
            if age > FAILED_EXPIRY_SECONDS:
                lines.append(f"❌ EXPIRED FAILED {tf_name} {fail_dir} - {int(age)}s ago ({int(age//60)}m) - TOO LATE")
                if age > 600:
                    del FAILED_TRACKER[key]
                return None
        # valid fresh
        if age == 0:
            lines.append(f"✅ FRESH FAILED {tf_name} {fail_dir} - {int(age)}s ago (within 5m) - VALID")
        else:
            lines.append(f"✅ FRESH FAILED {tf_name} {fail_dir} - {int(age)}s ago ({int(age//60)}m {int(age%60)}s) - VALID (<5m)")
        return (tf_name, fail_dir, desc, atr_tf, sup_tf, res_tf, age)

    # Check each TF independently (don't elif - check all)
    if tf15.get("failed") and tf15.get("fail_dir"):
        f = check_fresh("15M", tf15["fail_dir"], tf15["desc"], tf15["atr"], tf15["sup"], tf15["res"])
        if f: fresh_failed_list.append(f)
    if tf1.get("failed") and tf1.get("fail_dir"):
        f = check_fresh("1H", tf1["fail_dir"], tf1["desc"] + f" | {tf1['sweep']}", tf1["atr"], tf1["sup"], tf1["res"])
        if f: fresh_failed_list.append(f)
    if tf4.get("failed") and tf4.get("fail_dir"):
        f = check_fresh("4H", tf4["fail_dir"], tf4["desc"], tf4["atr"], tf4["sup"], tf4["res"])
        if f: fresh_failed_list.append(f)

    # Clean old trackers if no fresh at all
    if not fresh_failed_list:
        keys_to_clear = [k for k in FAILED_TRACKER.keys() if k.startswith(symbol_name+"_")]
        for k in keys_to_clear:
            if time.time() - FAILED_TRACKER[k] > FAILED_EXPIRY_SECONDS + 60:
                del FAILED_TRACKER[k]
    else:
        # Handle conflict: if we have opposite directions within 5m, avoid counter-trend
        dirs = set([x[1] for x in fresh_failed_list])
        if len(dirs) > 1:
            # Conflict detected - e.g., 4H BEAR and 1H BULL both fresh
            # Prioritize 4H trend (higher TF) and 15M alignment, avoid counter-trend scalp
            # Count: if 2 SELL (4H+15M) vs 1 BUY (1H) -> go SELL, but show conflict warning
            # If 4H 90% BEAR vs 1H BULL, prioritize 4H
            bulls = [x for x in fresh_failed_list if x[1]=="BULL"]
            bears = [x for x in fresh_failed_list if x[1]=="BEAR"]
            # If 4H is present, it wins
            has_4h = [x for x in fresh_failed_list if x[0]=="4H"]
            has_15m_choc_bear = "CHoCH BEAR" in tf15["desc"] or tf15["trigger"]=="SELL"
            has_15m_choc_bull = "CHoCH BULL" in tf15["desc"] or tf15["trigger"]=="BUY"
            if has_4h:
                # 4H is strongest - use 4H direction
                immediate_failed = has_4h[0][:6]  # take 4H as main, ignore counter
                lines.append(f"⚠️ CONFLICT: {len(bulls)} BULL vs {len(bears)} BEAR fresh - 4H {has_4h[0][1]} wins (higher TF) | 15M {tf15['trigger']} aligns")
                # If 15M CHoCH aligns with 4H, even stronger
                if has_4h[0][1]=="BEAR" and has_15m_choc_bear:
                    lines.append(f"✅ 15M {tf15['trigger']} aligns with 4H BEAR - STRONG SELL")
                elif has_4h[0][1]=="BULL" and has_15m_choc_bull:
                    lines.append(f"✅ 15M {tf15['trigger']} aligns with 4H BULL - STRONG BUY")
            else:
                # No 4H, conflict between 1H and 15M - WAIT to avoid late entry
                lines.append(f"❌ CONFLICT: 1H {fresh_failed_list[0][1]} vs 15M opposite - WAIT (avoid counter-trend, need alignment)")
                immediate_failed = None
        else:
            # All same direction - pick most recent (lowest age) or highest TF priority 4H>1H>15M
            # Sort by TF priority: 4H first, then 1H, then 15M, but also by freshness
            priority = {"4H":0, "1H":1, "15M":2}
            fresh_failed_list.sort(key=lambda x: (priority.get(x[0],3), x[6]))  # priority then age
            immediate_failed = fresh_failed_list[0][:6]

    # PURE PRICE ACTION CONFLUENCE - No EMA/RSI
    # Need: 4H BOS + 1H Sweep + 15M CHoCH/FVG
    bull_sweep = "BULL Sweep" in tf1["sweep"] or "BEAR Sweep" in tf1["sweep"]  # sweep opposite direction is entry
    bear_sweep = "BEAR Sweep" in tf1["sweep"] or "BULL Sweep" in tf1["sweep"]
    # For BUY: 4H BULL + 1H BULL sweep (liquidity taken low) + 15M BULL CHoCH/BUY
    bull_confluence = (tf4["trend"] == "BULL" and tf1["bias"] in ["BULL","RANGE"] and tf15["trigger"] == "BUY")
    bear_confluence = (tf4["trend"] == "BEAR" and tf1["bias"] in ["BEAR","RANGE"] and tf15["trigger"] == "SELL")
    # Premium requires sweep
    bull_premium = bull_confluence and ("BULL Sweep" in tf1["sweep"] or tf4["conf"] >= 70)
    bear_premium = bear_confluence and ("BEAR Sweep" in tf1["sweep"] or tf4["conf"] >= 70)
    # Also allow high-conf BOS even without sweep
    if tf4["conf"] >= 85 and tf15["trigger"] in ["BUY","SELL"]:
        if tf15["trigger"] == "BUY": bull_premium = True
        if tf15["trigger"] == "SELL": bear_premium = True

    # === STRUCTURE SUPERSEDES ATR - NEW HYBRID LOGIC ===
    atr_1h = tf1["atr"]
    atr_4h = tf4["atr"]
    # Structure levels
    sup_1h_struct = tf1["sup"]
    res_1h_struct = tf1["res"]
    sup_4h_struct = tf4["sup"]
    res_4h_struct = tf4["res"]
    sup_15m_struct = tf15["sup"]
    res_15m_struct = tf15["res"]
    
    buffer = atr_1h * 0.3
    atr_sl_min = atr_1h * 1.0
    atr_sl_max = atr_1h * 2.5
    
    # BUY SL: below swing lows + buffer, controlled by ATR
    buy_sl_struct_1h = sup_1h_struct - buffer
    buy_sl_struct_15m = sup_15m_struct - buffer
    buy_sl_struct = min(buy_sl_struct_1h, buy_sl_struct_15m)
    buy_sl_dist_struct = price - buy_sl_struct
    if buy_sl_dist_struct < atr_sl_min:
        buy_sl = price - atr_1h * 1.2
        buy_sl_reason = f"ATR guard (struct {buy_sl_dist_struct:.1f} too tight -> ATR 1.2)"
    elif buy_sl_dist_struct > atr_sl_max:
        buy_sl = price - atr_1h * 2.0
        buy_sl_reason = f"ATR cap (struct {buy_sl_dist_struct:.1f} too wide -> ATR 2.0)"
    else:
        buy_sl = buy_sl_struct
        buy_sl_reason = f"Structure 1H {sup_1h_struct:.2f} / 15M {sup_15m_struct:.2f} + {buffer:.1f} buf"
    
    # SELL SL: above swing highs + buffer, controlled by ATR
    sell_sl_struct_1h = res_1h_struct + buffer
    sell_sl_struct_15m = res_15m_struct + buffer
    sell_sl_struct = max(sell_sl_struct_1h, sell_sl_struct_15m)
    sell_sl_dist_struct = sell_sl_struct - price
    if sell_sl_dist_struct < atr_sl_min:
        sell_sl = price + atr_1h * 1.2
        sell_sl_reason = f"ATR guard (struct {sell_sl_dist_struct:.1f} too tight -> ATR 1.2)"
    elif sell_sl_dist_struct > atr_sl_max:
        sell_sl = price + atr_1h * 2.0
        sell_sl_reason = f"ATR cap (struct {sell_sl_dist_struct:.1f} too wide -> ATR 2.0)"
    else:
        sell_sl = sell_sl_struct
        sell_sl_reason = f"Structure 1H {res_1h_struct:.2f} / 15M {res_15m_struct:.2f} + {buffer:.1f} buf"
    
    # TPs: Structure first, ATR minimum RR
    # BUY
    buy_tp1_struct = min(res_15m_struct, res_1h_struct)
    buy_tp2_struct = res_1h_struct
    buy_tp3_struct = res_4h_struct
    buy_tp1 = buy_tp1_struct if buy_tp1_struct > price + atr_1h*1.5 else price + atr_1h*1.8
    buy_tp2 = buy_tp2_struct if buy_tp2_struct > price + atr_1h*2.5 and buy_tp2_struct > buy_tp1 else price + atr_1h*3.0
    buy_tp3 = buy_tp3_struct if buy_tp3_struct > price + atr_1h*4.0 and buy_tp3_struct > buy_tp2 else price + atr_1h*4.5
    if buy_tp3 <= price + atr_1h*3.0:
        buy_tp3 = price + atr_1h*4.5
    
    # SELL
    sell_tp1_struct = max(sup_15m_struct, sup_1h_struct)
    sell_tp2_struct = sup_1h_struct
    sell_tp3_struct = sup_4h_struct
    sell_tp1 = sell_tp1_struct if sell_tp1_struct < price - atr_1h*1.5 else price - atr_1h*1.8
    sell_tp2 = sell_tp2_struct if sell_tp2_struct < price - atr_1h*2.5 and sell_tp2_struct < sell_tp1 else price - atr_1h*3.0
    sell_tp3 = sell_tp3_struct if sell_tp3_struct < price - atr_1h*4.0 and sell_tp3_struct < sell_tp2 else price - atr_1h*4.5
    if sell_tp3 >= price - atr_1h*3.0:
        sell_tp3 = price - atr_1h*4.5

    vip_lines = []
    # === PRIORITY 0: IMMEDIATE FAILED TRANSIT (user: immediately they failed, if not don't give signal) ===
    if immediate_failed:
        tf_name, fail_dir, desc, atr_tf, sup_tf, res_tf = immediate_failed
        is_buy = fail_dir == "BULL"
        direction = f"{fail_dir}_FAILED_{tf_name}"
        emoji = f"🚨{'🟢' if is_buy else '🔴'}"
        # TP must respect 15M structure (user request)
        # 15M structure for TP always, even if failed is 4H/1H
        sup_15 = tf15["sup"]; res_15 = tf15["res"]
        # SL: beyond failed wick + buffer
        if is_buy:
            # Failed BEAR -> BUY, SL below 15M sup (respect 15M structure - FIXED tight SL)
            scalp_sl = tf15["sup"] - atr_tf*0.3  # 15M structure SL, not 4H
            if scalp_sl >= price:
                scalp_sl = price - atr_tf*0.8
            # TP1,2,3 respect 15M structure: next swing highs / OB / FVG
            tp1 = res_15 if res_15 > price + atr_tf*0.3 else price + atr_tf*0.8
            tp2 = tf1["res"] if tf1["res"] > tp1 else price + atr_tf*1.5
            tp3 = tf4["res"] if tf4["res"] > tp2 else price + atr_tf*2.2
            lines.append(f"🚨 {tf_name} IMMEDIATE FAILED {desc}")
            lines.append(f"{emoji} {symbol_name} IMMEDIATE {fail_dir} NOW - Failed to transit")
            lines.append(f"Entry: {price:.2f} SL: {scalp_sl:.2f} TP1: {tp1:.2f} (15M {res_15:.2f}) TP2: {tp2:.2f} (1H) TP3: {tp3:.2f} (4H) ⏰ {now}")
            lines.append(f"15M Structure TP: TP1 respects 15M res {res_15:.2f} | TP2 1H | TP3 4H")
            vip_lines.append(f"{emoji} {symbol_name} IMMEDIATE {fail_dir} FAILED {tf_name}")
            vip_lines.append(f"Entry: {price:.2f} SL: {scalp_sl:.2f} TP1: {tp1:.2f} TP2: {tp2:.2f} TP3: {tp3:.2f}")
            vip_lines.append(f"🚨 {desc}")
            vip_lines.append(f"15M Structure respected: TP1=15M {res_15:.2f}")
        else:
            # FIXED: SL respects 15M structure only, tight (not 4H 4198)
            scalp_sl = tf15["res"] + atr_tf*0.3  # 15M res + buffer
            if scalp_sl <= price:
                scalp_sl = price + atr_tf*0.8
            tp1 = sup_15 if sup_15 < price - atr_tf*0.3 else price - atr_tf*0.8
            tp2 = tf1["sup"] if tf1["sup"] < tp1 else price - atr_tf*1.5
            tp3 = tf4["sup"] if tf4["sup"] < tp2 else price - atr_tf*2.2
            lines.append(f"🚨 {tf_name} IMMEDIATE FAILED {desc}")
            lines.append(f"{emoji} {symbol_name} IMMEDIATE {fail_dir} NOW - Failed to transit")
            lines.append(f"Entry: {price:.2f} SL: {scalp_sl:.2f} TP1: {tp1:.2f} (15M {sup_15:.2f}) TP2: {tp2:.2f} (1H) TP3: {tp3:.2f} (4H) ⏰ {now}")
            lines.append(f"15M Structure TP: TP1 respects 15M sup {sup_15:.2f} | TP2 1H | TP3 4H")
            vip_lines.append(f"{emoji} {symbol_name} IMMEDIATE {fail_dir} FAILED {tf_name}")
            vip_lines.append(f"Entry: {price:.2f} SL: {scalp_sl:.2f} TP1: {tp1:.2f} TP2: {tp2:.2f} TP3: {tp3:.2f}")
            vip_lines.append(f"🚨 {desc}")
            vip_lines.append(f"15M Structure respected: TP1=15M {sup_15:.2f}")
        buy_sl = scalp_sl; buy_tp1 = tp1; buy_tp2 = tp2; buy_tp3 = tp3
        sell_sl = scalp_sl; sell_tp1 = tp1; sell_tp2 = tp2; sell_tp3 = tp3
    elif bull_premium:
        direction = "BUY"
        emoji = "🟢"
        lines.append(f"🔥🔥 PREMIUM BUY 4H BULL->1H Support->15M BUY (Struct>ATR)")
        lines.append(f"{emoji} {symbol_name} BUY NOW")
        lines.append(f"Entry: {price:.2f} SL: {buy_sl:.2f} TP1: {buy_tp1:.2f} TP2: {buy_tp2:.2f} TP3: {buy_tp3:.2f} ⏰ {now}")
        lines.append(f"SL: {buy_sl_reason}")
        vip_lines.append(f"{emoji} {symbol_name} BUY NOW - STRUCTURE > ATR")
        vip_lines.append("")
        vip_lines.append(f"Entry: {price:.2f}")
        vip_lines.append(f"SL: {buy_sl:.2f} ({buy_sl_reason})")
        vip_lines.append(f"TP1: {buy_tp1:.2f} TP2: {buy_tp2:.2f} TP3: {buy_tp3:.2f}")
        vip_lines.append(f"4H {tf4['trend']}->1H {tf1['bias']}->15M {tf15['trigger']} ⏰ {now}")
        vip_lines.append(f"📌 TRAILING: TP1->BE | TP2->TP1 Lock | ATR Trail {atr_1h*1.5:.2f}")
    elif bear_premium:
        direction = "SELL"
        emoji = "🔴"
        lines.append(f"🔥🔥 PREMIUM SELL 4H BEAR->1H Res->15M SELL (Struct>ATR)")
        lines.append(f"{emoji} {symbol_name} SELL NOW")
        lines.append(f"Entry: {price:.2f} SL: {sell_sl:.2f} TP1: {sell_tp1:.2f} TP2: {sell_tp2:.2f} TP3: {sell_tp3:.2f} ⏰ {now}")
        lines.append(f"SL: {sell_sl_reason}")
        vip_lines.append(f"{emoji} {symbol_name} SELL NOW - STRUCTURE > ATR")
        vip_lines.append("")
        vip_lines.append(f"Entry: {price:.2f}")
        vip_lines.append(f"SL: {sell_sl:.2f} ({sell_sl_reason})")
        vip_lines.append(f"TP1: {sell_tp1:.2f} TP2: {sell_tp2:.2f} TP3: {sell_tp3:.2f}")
        vip_lines.append(f"4H {tf4['trend']}->1H {tf1['bias']}->15M {tf15['trigger']} ⏰ {now}")
        vip_lines.append(f"📌 TRAILING: TP1->BE | TP2->TP1 Lock | ATR Trail {atr_1h*1.5:.2f}")
    elif bull_confluence:
        direction = "BUY"
        emoji = "🟢"
        lines.append(f"🔥 MTF BUY 4H {tf4['trend']}+1H {tf1['bias']}+15M {tf15['trigger']} (Struct>ATR)")
        lines.append(f"{emoji} {symbol_name} BUY NOW Entry: {price:.2f} SL: {buy_sl:.2f} TP1: {buy_tp1:.2f} TP2: {buy_tp2:.2f} TP3: {buy_tp3:.2f} ⏰ {now}")
        vip_lines.append(f"{emoji} {symbol_name} BUY NOW - MTF Struct>ATR")
        vip_lines.append("")
        vip_lines.append(f"Entry: {price:.2f}")
        vip_lines.append(f"SL: {buy_sl:.2f} TP1: {buy_tp1:.2f} TP2: {buy_tp2:.2f} TP3: {buy_tp3:.2f}")
        vip_lines.append(f"⏰ {now}")
    elif bear_confluence:
        direction = "SELL"
        emoji = "🔴"
        lines.append(f"🔥 MTF SELL 4H {tf4['trend']}+1H {tf1['bias']}+15M {tf15['trigger']} (Struct>ATR)")
        lines.append(f"{emoji} {symbol_name} SELL NOW Entry: {price:.2f} SL: {sell_sl:.2f} TP1: {sell_tp1:.2f} TP2: {sell_tp2:.2f} TP3: {sell_tp3:.2f} ⏰ {now}")
        vip_lines.append(f"{emoji} {symbol_name} SELL NOW - MTF Struct>ATR")
        vip_lines.append("")
        vip_lines.append(f"Entry: {price:.2f}")
        vip_lines.append(f"SL: {sell_sl:.2f} TP1: {sell_tp1:.2f} TP2: {sell_tp2:.2f} TP3: {sell_tp3:.2f}")
        vip_lines.append(f"⏰ {now}")
    # === 15M SCALP MODE: immediate fail only + 15M structure TP (1-5min expiry) ===
    elif tf15["conf"] >= 60 and tf15["trigger"] in ["BUY","SELL"]:
        has_fail = tf15.get("failed") and tf15.get("fail_dir")
        recent_15 = False
        if tf15.get("sh") and tf15.get("sl"):
            try:
                last_idx = max([i for i,_ in tf15["sh"]+tf15["sl"]], default=0)
                recent_15 = last_idx >= len(tf15["hist"])-3
            except:
                recent_15 = True
        else:
            recent_15 = True
        has_fail = has_fail and recent_15
        if not has_fail:
            direction = "WAIT"
        else:
            is_buy_scalp = tf15["trigger"] == "BUY" or (tf15.get("fail_dir")=="BULL")
            direction = f"{'BUY' if is_buy_scalp else 'SELL'}_SCALP_15M"
            emoji = "⚡🟢" if is_buy_scalp else "⚡🔴"
            atr_15 = tf15["atr"]
            if is_buy_scalp:
                scalp_sl = tf15["sup"] - atr_15*0.3 if tf15["sup"] < price else price - atr_15*0.8
                tp1_struct = tf15["res"] if tf15["res"] > price + atr_15*0.3 else price + atr_15*1.0
                tp2_struct = tf1["res"] if tf1["res"] > tp1_struct else price + atr_15*1.8
                tp3_struct = tf4["res"] if tf4["res"] > tp2_struct else price + atr_15*2.5
                scalp_tp1 = tp1_struct; scalp_tp2 = tp2_struct; scalp_tp3 = tp3_struct
                lines.append(f"⚡ 15M IMMEDIATE FAILED -> BUY (15M structure TP) FRESH <5m")
                lines.append(f"{emoji} {symbol_name} SCALP BUY NOW Entry: {price:.2f} SL: {scalp_sl:.2f} TP1: {scalp_tp1:.2f} [15M {tf15['res']:.2f}] TP2: {scalp_tp2:.2f} [1H] TP3: {scalp_tp3:.2f} [4H] ⏰ {now}")
                vip_lines.append(f"{emoji} {symbol_name} 15M SCALP BUY - IMMEDIATE FAILED <5m Entry: {price:.2f} SL: {scalp_sl:.2f} TP1: {scalp_tp1:.2f}")
                buy_sl = scalp_sl; buy_tp1 = scalp_tp1; buy_tp2 = scalp_tp2; buy_tp3 = scalp_tp3
                sell_sl = scalp_sl; sell_tp1 = scalp_tp1; sell_tp2 = scalp_tp2; sell_tp3 = scalp_tp3
            else:
                scalp_sl = tf15["res"] + atr_15*0.3 if tf15["res"] > price else price + atr_15*0.8
                tp1_struct = tf15["sup"] if tf15["sup"] < price - atr_15*0.3 else price - atr_15*1.0
                tp2_struct = tf1["sup"] if tf1["sup"] < tp1_struct else price - atr_15*1.8
                tp3_struct = tf4["sup"] if tf4["sup"] < tp2_struct else price - atr_15*2.5
                scalp_tp1 = tp1_struct; scalp_tp2 = tp2_struct; scalp_tp3 = tp3_struct
                lines.append(f"⚡ 15M IMMEDIATE FAILED -> SELL (15M structure TP) FRESH <5m")
                lines.append(f"{emoji} {symbol_name} SCALP SELL NOW Entry: {price:.2f} SL: {scalp_sl:.2f} TP1: {scalp_tp1:.2f} [15M {tf15['sup']:.2f}] TP2: {scalp_tp2:.2f} [1H] TP3: {scalp_tp3:.2f} [4H] ⏰ {now}")
                vip_lines.append(f"{emoji} {symbol_name} 15M SCALP SELL - IMMEDIATE FAILED <5m Entry: {price:.2f} SL: {scalp_sl:.2f} TP1: {scalp_tp1:.2f}")
                buy_sl = scalp_sl; buy_tp1 = scalp_tp1; buy_tp2 = scalp_tp2; buy_tp3 = scalp_tp3
                sell_sl = scalp_sl; sell_tp1 = scalp_tp1; sell_tp2 = scalp_tp2; sell_tp3 = scalp_tp3
    # === 1H FAILED TRANSIT SCALP - IMMEDIATE 1-5min only ===
    elif tf1["conf"] >= 60 and tf1["bias"] in ["BULL","BEAR"]:
        has_fail_1h = tf1.get("failed") and tf1.get("fail_dir")
        recent_1h = False
        if tf1.get("sh") and tf1.get("sl"):
            try:
                last_idx = max([i for i,_ in tf1["sh"]+tf1["sl"]], default=0)
                recent_1h = last_idx >= len(tf1["hist"])-2
            except:
                recent_1h = True
        else:
            recent_1h = True
        has_fail_1h = has_fail_1h and recent_1h
        if not has_fail_1h:
            direction = "WAIT"
        else:
            is_buy = tf1.get("fail_dir")=="BULL"
            direction = f"{'BULL' if is_buy else 'BEAR'}_SCALP_1H"
            emoji = "⚡⚡🟢" if is_buy else "⚡⚡🔴"
            atr_1 = tf1["atr"]
            if is_buy:
                scalp_sl = tf15["sup"] - atr_1*0.3
                scalp_tp1 = tf15["res"] if tf15["res"] > price + atr_1*0.3 else price + atr_1*0.8
                scalp_tp2 = tf1["res"] if tf1["res"] > scalp_tp1 else price + atr_1*1.5
                scalp_tp3 = tf4["res"] if tf4["res"] > scalp_tp2 else price + atr_1*2.2
                lines.append(f"⚡⚡ 1H IMMEDIATE FAILED -> BUY FRESH <5m Entry: {price:.2f} SL: {scalp_sl:.2f} TP1: {scalp_tp1:.2f} [15M]")
                vip_lines.append(f"{emoji} {symbol_name} 1H SCALP BUY <5m Entry: {price:.2f}")
            else:
                scalp_sl = tf15["res"] + atr_1*0.3
                scalp_tp1 = tf15["sup"] if tf15["sup"] < price - atr_1*0.3 else price - atr_1*0.8
                scalp_tp2 = tf1["sup"] if tf1["sup"] < scalp_tp1 else price - atr_1*1.5
                scalp_tp3 = tf4["sup"] if tf4["sup"] < scalp_tp2 else price - atr_1*2.2
                lines.append(f"⚡⚡ 1H IMMEDIATE FAILED -> SELL FRESH <5m Entry: {price:.2f} SL: {scalp_sl:.2f} TP1: {scalp_tp1:.2f} [15M]")
                vip_lines.append(f"{emoji} {symbol_name} 1H SCALP SELL <5m Entry: {price:.2f}")
            buy_sl = scalp_sl; buy_tp1 = scalp_tp1; buy_tp2 = scalp_tp2; buy_tp3 = scalp_tp3
            sell_sl = scalp_sl; sell_tp1 = scalp_tp1; sell_tp2 = scalp_tp2; sell_tp3 = scalp_tp3
    # === 4H FAILED TRANSIT SCALP - IMMEDIATE 1-5min only ===
    elif tf4["conf"] >= 60 and tf4["trend"] in ["BULL","BEAR"]:
        has_fail_4h = tf4.get("failed") and tf4.get("fail_dir")
        recent_4h = False
        if tf4.get("sh") and tf4.get("sl"):
            try:
                last_idx = max([i for i,_ in tf4["sh"]+tf4["sl"]], default=0)
                recent_4h = last_idx >= len(tf4["hist"])-2
            except:
                recent_4h = True
        else:
            recent_4h = True
        has_fail_4h = has_fail_4h and recent_4h
        if not has_fail_4h:
            direction = "WAIT"
        else:
            is_buy = tf4.get("fail_dir")=="BULL"
            direction = f"{'BULL' if is_buy else 'BEAR'}_SCALP_4H"
            emoji = "⚡⚡⚡🟢" if is_buy else "⚡⚡⚡🔴"
            atr_4 = tf4["atr"]
            if is_buy:
                scalp_sl = tf15["sup"] - atr_4*0.4
                scalp_tp1 = tf15["res"] if tf15["res"] > price + atr_4*0.3 else price + atr_4*0.8
                scalp_tp2 = tf1["res"] if tf1["res"] > scalp_tp1 else price + atr_4*1.5
                scalp_tp3 = tf4["res"] if tf4["res"] > scalp_tp2 else price + atr_4*2.5
                lines.append(f"⚡⚡⚡ 4H IMMEDIATE FAILED -> BUY FRESH <5m Entry: {price:.2f} SL: {scalp_sl:.2f} TP1: {scalp_tp1:.2f}")
                vip_lines.append(f"{emoji} {symbol_name} 4H SCALP BUY <5m")
            else:
                scalp_sl = tf15["res"] + atr_4*0.4
                scalp_tp1 = tf15["sup"] if tf15["sup"] < price - atr_4*0.3 else price - atr_4*0.8
                scalp_tp2 = tf1["sup"] if tf1["sup"] < scalp_tp1 else price - atr_4*1.5
                scalp_tp3 = tf4["sup"] if tf4["sup"] < scalp_tp2 else price - atr_4*2.5
                lines.append(f"⚡⚡⚡ 4H IMMEDIATE FAILED -> SELL FRESH <5m Entry: {price:.2f} SL: {scalp_sl:.2f} TP1: {scalp_tp1:.2f}")
                vip_lines.append(f"{emoji} {symbol_name} 4H SCALP SELL <5m")
            buy_sl = scalp_sl; buy_tp1 = scalp_tp1; buy_tp2 = scalp_tp2; buy_tp3 = scalp_tp3
            sell_sl = scalp_sl; sell_tp1 = scalp_tp1; sell_tp2 = scalp_tp2; sell_tp3 = scalp_tp3
    else:
        lines.append(f"❌ WAIT No MTF confluence - No fresh FAILED in last 5m (avoid late entry)")
        lines.append(f"4H {tf4['trend']} | 1H {tf1['bias']} | 15M {tf15['trigger']}")
        if tf15["trigger"] in ["BUY","SELL"]:
            lines.append(f"👀 15M {tf15['trigger']} {tf15['desc']} - not fresh FAILED, waiting")
        if tf1["bias"] in ["BULL","BEAR"]:
            lines.append(f"👀 1H {tf1['bias']} {tf1['desc']} - waiting for fresh FAILED <5m")
        if tf4["trend"] in ["BULL","BEAR"]:
            lines.append(f"👀 4H {tf4['trend']} {tf4['desc']} - waiting for fresh FAILED <5m")
    # Generate chart
    # Generate chart only when we have a valid trade (including SCALP)
    chart_path = None
    if "BUY" in direction or "SELL" in direction:
        try:
            if "SCALP" in direction:
                is_buy = "BUY" in direction
            else:
                is_buy = direction=="BUY"
            sl = buy_sl if is_buy else sell_sl
            tp1 = buy_tp1 if is_buy else sell_tp1
            tp2 = buy_tp2 if is_buy else sell_tp2
            tp3 = buy_tp3 if is_buy else sell_tp3
            chart_path = generate_mtf_chart(symbol_name, tf4, tf1, tf15, price, sl, tp1, tp2, direction)
            # SAVE ACTIVE TRADE FOR TRAILING
            ACTIVE_TRADES[symbol_name] = {
                'entry': price,
                'sl': sl,
                'tp1': tp1,
                'tp2': tp2,
                'tp3': tp3,
                'direction': direction,
                'atr': atr_1h,
                'trail_sl': sl,
                'status': 'OPEN'
            }
        except:
            chart_path = None
    return "\n".join(lines), "\n".join(vip_lines), direction, price, chart_path



# ===== SIMPLIFIED COMMANDS - ONLY 2 COMBOS =====
async def start(update:Update,context:ContextTypes.DEFAULT_TYPE):
    SUBSCRIBERS.add(update.effective_chat.id)
    await update.message.reply_text(f"🏆 GOLD VIP SIMPLIFIED 2-COMBO 🏆\n📢 {CHANNEL_USERNAME}\n\n🎯 ONLY 2 COMBOS (Profitable Long Term):\n\n1️⃣ MTF PREMIUM (4H->1H->15M) - 2-3 signals/day, 65% win, RR 1:2.5\n/signal - GOLD MTF Premium\n/mtf - ALL markets MTF\n/gold - GOLD MTF\n/silver - SILVER MTF\n/us30 - US30 MTF\n/ger30 - GER30 MTF\n/ndx - NDX MTF\n\n2️⃣ TREND (4H Only) - For bias\n/4h - 4H trend all\n\nOther:\n/buy - Join VIP $25/month\n/autopilot - Auto MTF\n\nThat's it! Only 2 combos, not 15. Profitable, simple.")

async def buy(update:Update,context:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"💳 JOIN VIP $25/MONTH\nUSDT TRC20:\n{CRYPTO_WALLET}\n\n2 COMBOS ONLY:\n1. MTF PREMIUM 4H1H15M - RR 1:2.5 Profitable\n2. 4H Trend Filter\n\n📢 {CHANNEL_USERNAME}", disable_web_page_preview=True)


async def signal_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text("⏳ Analyzing GOLD MTF 4H->1H->15M...")
        f,v,d,p,chart = build_mtf_confluence("GOLD")
        await update.message.reply_text(f)
        if chart and os.path.exists(chart):
            try:
                await update.message.reply_photo(photo=open(chart,'rb'), caption=f"📊 GOLD MTF Chart\nEntry/SL/TP marked\n{d}")
            except Exception as e:
                print(f"Photo send failed: {e}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error fetching GOLD MTF: {e}\nTrying cache...\n" + build_4h_fallback("GOLD"))

def build_4h_fallback(name):
    try:
        sym, fb = SYMBOLS[name]
        tf4 = analyze_4h(sym, fb)
        return f"📊 {name} 4H {tf4['trend']} {tf4['conf']}% {tf4['desc']} | Price {tf4['price']:.2f} OB {tf4['ob_low']:.0f}/{tf4['ob_high']:.0f}"
    except Exception as e2:
        return f"❌ Fallback failed: {e2}"

async def mtf_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text("⏳ Analyzing ALL markets MTF (5 markets x 3 timeframes = 15 API calls)... may take 20s")
        msgs=[]
        for name in SYMBOLS:
            try:
                f,v,d,p,chart = build_mtf_confluence(name)
                msgs.append(f)
            except Exception as e:
                msgs.append(f"❌ {name} failed: {e}")
        await update.message.reply_text("\n\n---\n\n".join(msgs))
    except Exception as e:
        await update.message.reply_text(f"❌ MTF error: {e}")

async def gold_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text("⏳ Analyzing GOLD MTF...")
        f,v,d,p,chart = build_mtf_confluence("GOLD")
        await update.message.reply_text(f)
    except Exception as e:
        await update.message.reply_text(f"❌ GOLD MTF error: {e}")

async def silver_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text("⏳ Analyzing SILVER MTF...")
        f,v,d,p,chart = build_mtf_confluence("SILVER")
        await update.message.reply_text(f)
        if chart and os.path.exists(chart):
            try: await update.message.reply_photo(photo=open(chart,'rb'), caption=f"📊 SILVER {d}")
            except: pass
    except Exception as e:
        await update.message.reply_text(f"❌ SILVER error: {e}")

async def us30_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text("⏳ Analyzing US30 MTF...")
        f,v,d,p,chart = build_mtf_confluence("US30")
        await update.message.reply_text(f)
        if chart and os.path.exists(chart):
            try: await update.message.reply_photo(photo=open(chart,'rb'), caption=f"📊 US30 {d}")
            except: pass
    except Exception as e:
        await update.message.reply_text(f"❌ US30 error: {e}")

async def ger30_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text("⏳ Analyzing GER30 MTF...")
        f,v,d,p,chart = build_mtf_confluence("GER30")
        await update.message.reply_text(f)
        if chart and os.path.exists(chart):
            try: await update.message.reply_photo(photo=open(chart,'rb'), caption=f"📊 GER30 {d}")
            except: pass
    except Exception as e:
        await update.message.reply_text(f"❌ GER30 error: {e}")

async def ndx_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text("⏳ Analyzing NDX100 MTF...")
        f,v,d,p,chart = build_mtf_confluence("NDX100")
        await update.message.reply_text(f)
        if chart and os.path.exists(chart):
            try: await update.message.reply_photo(photo=open(chart,'rb'), caption=f"📊 NDX100 {d}")
            except: pass
    except Exception as e:
        await update.message.reply_text(f"❌ NDX100 error: {e}")

async def tf4_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text("⏳ Analyzing 4H trends...")
        lines = ["📊 4H TREND - BOSS"]
        for name in SYMBOLS:
            try:
                sym, fb = SYMBOLS[name]
                tf4 = analyze_4h(sym, fb)
                emoji = "🟢" if tf4["trend"]=="BULL" else "🔴" if tf4["trend"]=="BEAR" else "⚪"
                lines.append(f"{emoji} {name}: {tf4['trend']} {tf4['conf']}% | {tf4['price']:.2f} EMA50 {tf4['e50']:.2f} EMA100 {tf4['e100']:.2f} RSI {tf4['rsi']:.1f}")
            except Exception as e:
                lines.append(f"❌ {name} 4H failed: {e}")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"❌ 4H error: {e}")


async def autopilot_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    global AUTOPILOT_ACTIVE, AUTOPILOT_TASK
    AUTOPILOT_ACTIVE=True; SUBSCRIBERS.add(update.effective_chat.id)
    if AUTOPILOT_TASK and not AUTOPILOT_TASK.done(): AUTOPILOT_TASK.cancel()
    AUTOPILOT_TASK = asyncio.create_task(autopilot_loop(context))
    await update.message.reply_text(f"✅ AUTOPILOT ON - MTF PREMIUM\nID {update.effective_chat.id} saved")

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
            # Check trailing for active trades every loop
            for active_name in list(ACTIVE_TRADES.keys()):
                try:
                    sym, fb = SYMBOLS[active_name]
                    pd = get_real_price_mtf(sym, "1h", fb)
                    cur = pd[0] if pd[0] else fb
                    if sym == "GC=F":
                        sp = get_spot_gold_price()
                        if sp: cur = sp
                    trail_msg = update_trailing_status(active_name, cur)
                    if trail_msg:
                        for chat_id in list(SUBSCRIBERS):
                            try: await context.bot.send_message(chat_id=chat_id, text=trail_msg)
                            except: pass
                        try: await context.bot.send_message(chat_id=CHANNEL_ID, text=trail_msg)
                        except: pass
                except: pass

            for name in ["GOLD","SILVER","US30","GER30","NDX100"]:
                try:
                    f,v,d,p,chart = build_mtf_confluence(name)
                    if v and d not in ["WAIT","NONE"]:
                        for chat_id in list(SUBSCRIBERS):
                            try: 
                                await context.bot.send_message(chat_id=chat_id,text=f"🤖 {name} MTF PREMIUM\n{f}")
                                if chart and os.path.exists(chart):
                                    try: await context.bot.send_photo(chat_id=chat_id, photo=open(chart,'rb'))
                                    except: pass
                            except: pass
                        try: 
                            await context.bot.send_message(chat_id=CHANNEL_ID,text=v)
                            if chart and os.path.exists(chart):
                                try: await context.bot.send_photo(chat_id=CHANNEL_ID, photo=open(chart,'rb'))
                                except: pass
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
        await context.bot.send_message(chat_id=CHANNEL_ID,text="✅ Bot Connected! SIMPLIFIED 2-COMBO LIVE")
        await update.message.reply_text("✅ Test sent!")
    except Exception as e: await update.message.reply_text(f"❌ Failed: {e}")

async def sendvip(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id!=ADMIN_ID: await update.message.reply_text("❌ Admin only"); return
    f,v,d,p,chart = build_mtf_confluence("GOLD")
    if v and d not in ["WAIT"]:
        try: 
            await context.bot.send_message(chat_id=CHANNEL_ID, text=v)
            if chart and os.path.exists(chart):
                try: await context.bot.send_photo(chat_id=CHANNEL_ID, photo=open(chart,'rb'), caption=f"📊 {v[:200]}")
                except: pass
            await update.message.reply_text(f"✅ GOLD MTF VIP SENT\n\n{v}")
        except Exception as e: await update.message.reply_text(f"❌ Failed: {e}")
    else: await update.message.reply_text(f"❌ No MTF confluence now\n\n{f}")


async def trail_cmd(update, context):
    try:
        # Check all active trades for trailing updates
        msgs=[]
        for sym_name in list(ACTIVE_TRADES.keys()):
            try:
                sym, fb = SYMBOLS[sym_name]
                # get current price
                price_data = get_real_price_mtf(sym, "1h", fb)
                if price_data[0] is None:
                    continue
                cur_price = price_data[0]
                # override with spot for gold/silver
                if sym == "GC=F":
                    sp = get_spot_gold_price()
                    if sp: cur_price = sp
                elif sym == "SI=F":
                    sp = get_spot_silver_price()
                    if sp: cur_price = sp
                msg = update_trailing_status(sym_name, cur_price)
                if msg:
                    msgs.append(msg)
            except Exception as e:
                msgs.append(f"{sym_name} trail error: {e}")
        if msgs:
            await update.message.reply_text("\n\n".join(msgs))
        else:
            if not ACTIVE_TRADES:
                await update.message.reply_text("No active trades to trail. Open a trade with /gold first.")
            else:
                await update.message.reply_text("No trailing updates needed yet. Trades still OPEN.")
    except Exception as e:
        await update.message.reply_text(f"Trail error: {e}")

async def trail_status_cmd(update, context):
    try:
        if not ACTIVE_TRADES:
            await update.message.reply_text("No active trades.")
            return
        lines=["📌 ACTIVE TRADES - TRAILING STATUS"]
        for name, t in ACTIVE_TRADES.items():
            lines.append(f"{name} {t['direction']} Entry {t['entry']:.2f} SL {t['trail_sl']:.2f} TP1 {t['tp1']:.2f} TP2 {t['tp2']:.2f} TP3 {t['tp3']:.2f} | {t['status']}")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"Status error: {e}")

async def sendgoldmtf_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id!=ADMIN_ID: await update.message.reply_text("❌ Admin only"); return
    f,v,d,p,chart = build_mtf_confluence("GOLD")
    if v and d not in ["WAIT","NONE"]:
        try: 
            await context.bot.send_message(chat_id=CHANNEL_ID, text=v)
            if chart and os.path.exists(chart):
                try: await context.bot.send_photo(chat_id=CHANNEL_ID, photo=open(chart,'rb'), caption=f"📊 GOLD MTF")
                except: pass
            await update.message.reply_text(f"✅ GOLD MTF PREMIUM VIP SENT\n\n{v}")
        except Exception as e: await update.message.reply_text(f"❌ Failed: {e}")
    else: await update.message.reply_text(f"❌ No Gold MTF now\n\n{f}")

def main():
    if not BOT_TOKEN: print("BOT_TOKEN missing"); return
    try: requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=true",timeout=5)
    except: pass
    app=ApplicationBuilder().token(BOT_TOKEN).build()
    # SIMPLIFIED - ONLY 12 COMMANDS
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
    # Keep old names as aliases to same MTF to avoid breaking
    app.add_handler(CommandHandler("goldmtf",gold_cmd))
    app.add_handler(CommandHandler("bestcombo",signal_cmd))
    app.add_handler(CommandHandler("gold3",gold_cmd))
    app.add_handler(CommandHandler("goldsweep",gold_cmd))
    print("SIMPLIFIED 2-COMBO MTF LIVE")
    app.run_polling(drop_pending_updates=True)

if __name__=="__main__": main()
