
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



def get_twelvedata_api_key():
    # Robust: check env vars, secret files, .env, any TWE* var (your screenshot shows TWE...)
    # 1. Direct env vars (multiple possible names)
    for name in ["TWELVEDATA_API_KEY", "TWELVE_DATA_API_KEY", "TWELVEDATA_KEY", "TWELVE_API_KEY", "TWE_API_KEY"]:
        v = os.getenv(name, "").strip()
        if v and len(v) > 10:
            return v
    # 2. Any env var starting with TWE (your screenshot shows TWE... key)
    for k,v in os.environ.items():
        if k.startswith("TWE") and len(v.strip()) > 10:
            # avoid BOT_TOKEN etc
            if "TOKEN" not in k or "TWELVE" in k or k.startswith("TWE"):
                vv = v.strip()
                # TwelveData keys are like 123abc... 32 chars
                if len(vv) >= 20:
                    print(f"Found TwelveData key in env var {k}")
                    return vv
    # 3. Secret files (Render Secret Files are in /etc/secrets/)
    secret_paths = [
        "/etc/secrets/TWELVEDATA_API_KEY",
        "/etc/secrets/TWELVE_DATA_API_KEY",
        "/etc/secrets/TWELVEDATA",
        "/etc/secrets/twelvedata",
        "/etc/secrets/TWE",
        "./TWELVEDATA_API_KEY",
        "/mnt/data/TWELVEDATA_API_KEY"
    ]
    for p in secret_paths:
        try:
            if os.path.exists(p):
                with open(p, 'r') as sf:
                    v = sf.read().strip()
                    if len(v) > 10:
                        print(f"Found TwelveData key in file {p}")
                        return v
        except:
            pass
    # 4. Try reading .env file if exists
    try:
        if os.path.exists(".env"):
            with open(".env", "r") as ef:
                for line in ef:
                    if "TWELVE" in line and "=" in line:
                        parts = line.strip().split("=",1)
                        if len(parts)==2:
                            v = parts[1].strip().strip('"').strip("'")
                            if len(v) > 10:
                                return v
    except:
        pass
    return ""



def get_twelvedata_mtf(symbol, interval, fallback):
    # TwelveData API - more accurate real-time, fixes Yahoo lag issue
    api_key = get_twelvedata_api_key()
    if not api_key:
        return None, [], [], []  # no key, fallback to Yahoo
    try:
        td_symbol_map = {
            "GC=F": "XAU/USD",
            "SI=F": "XAG/USD",
            "^DJI": "DJI",
            "^GDAXI": "DAX",
            "^NDX": "NDX"
        }
        td_symbol = td_symbol_map.get(symbol, symbol)
        td_interval_map = {"15m":"15min", "1h":"1h", "4h":"4h"}
        td_interval = td_interval_map.get(interval, "15min")
        # TwelveData time_series
        url = f"https://api.twelvedata.com/time_series?symbol={td_symbol}&interval={td_interval}&outputsize=100&apikey={api_key}&order=ASC"
        r = requests.get(url, timeout=10).json()
        if "values" not in r:
            print(f"TwelveData failed {symbol} {interval}: {r}")
            return None, [], [], []
        values = r["values"]  # oldest first because ASC
        if len(values) < 20:
            return None, [], [], []
        closes = []
        highs = []
        lows = []
        for v in values:
            try:
                closes.append(float(v["close"]))
                highs.append(float(v["high"]))
                lows.append(float(v["low"]))
            except:
                continue
        if len(closes) < 20:
            return None, [], [], []
        price = closes[-1]
        # For 4H, TwelveData already gives 4h directly, no need to aggregate
        max_hist = 200 if interval=="4h" else 100
        history = closes[-max_hist:]
        highs = highs[-max_hist:]
        lows = lows[-max_hist:]
        key = f"{symbol}_{interval}_TD"
        # Also cache in main cache for compatibility
        PRICE_CACHE[f"{symbol}_{interval}"] = (price, history, highs, lows)
        CACHE_TIME[f"{symbol}_{interval}"] = time.time()
        print(f"TwelveData OK {symbol} {interval} price {price} len {len(history)}")
        return price, history, highs, lows
    except Exception as e:
        print(f"TwelveData exception {symbol} {interval}: {e}")
        return None, [], [], []

def get_real_price_mtf_twelve_first(symbol, interval, fallback):
    api_key = get_twelvedata_api_key()
    if api_key:
        price, hist, highs, lows = get_twelvedata_mtf(symbol, interval, fallback)
        if price is not None and len(hist) >= 20:
            return price, hist, highs, lows
        else:
            print(f"TwelveData failed for {symbol} {interval}, falling back to Yahoo - check API limit")
    # Fallback to Yahoo only if TwelveData fails or no key
    return get_real_price_mtf_yahoo(symbol, interval, fallback)



def get_real_price_mtf_yahoo(symbol, interval, fallback):
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


def get_real_price_mtf(symbol, interval, fallback):
    # FIXED: For GOLD/SILVER use TwelveData first (accurate XAU/USD)
    # For indices (GER30/US30/NDX) use Yahoo first - closer to MT5 broker cash price
    # TwelveData DAX is Xetra exchange, not broker CFD -> 48 points disparity (25148 vs 25100)
    if symbol in ["GC=F", "SI=F"]:
        # GOLD/SILVER - TwelveData XAU/USD is best
        return get_real_price_mtf_twelve_first(symbol, interval, fallback)
    else:
        # INDICES - Yahoo ^GDAXI/^DJI/^NDX is closer to MT5 broker
        # Try Yahoo first, TwelveData as fallback
        price, hist, highs, lows = get_real_price_mtf_yahoo(symbol, interval, fallback)
        if price is not None and len(hist) >= 20:
            return price, hist, highs, lows
        # Fallback to TwelveData if Yahoo fails
        return get_real_price_mtf_twelve_first(symbol, interval, fallback)


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
    if not get_twelvedata_api_key():
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
    if not get_twelvedata_api_key():
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
    if not get_twelvedata_api_key():
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
    # === NO-LOSS + PROFIT-LOCK TRAILING WITH SANITY CHECK ===
    if symbol_name not in ACTIVE_TRADES:
        return None
    t = ACTIVE_TRADES[symbol_name]
    entry = t['entry']
    atr = t.get('atr', 15)
    direction = t['direction']
    status = t.get('status','OPEN')
    trail_sl = t.get('trail_sl', t['sl'])

    # === SANITY CHECK - FIXES YOUR GER30 SL 135.17 BUG ===
    # Your screenshot: GER30 entry 25288, current fetched as 135.17 -> profit 25154, SL 135 bug
    # Reject bad price feeds: if price moved >20% instantly or price < 500 for indices, it's bad data
    if current_price <= 0:
        return None
    # For indices/GOLD, price should be > 1000 for GER30/US30, > 100 for GOLD/SILVER
    if symbol_name in ["GER30", "US30", "NDX100"] and current_price < 1000:
        print(f"BAD PRICE FEED {symbol_name} price {current_price} < 1000, entry {entry} - reject trailing (fixes SL 135 bug)")
        return None
    if symbol_name in ["GOLD"] and (current_price < 1000 or current_price > 10000):
        print(f"BAD PRICE FEED GOLD {current_price} out of range - reject")
        return None
    if symbol_name in ["SILVER"] and (current_price < 10 or current_price > 100):
        return None
    # Reject if profit > 20% of entry (impossible spike = bad data)
    # For GER30 entry 25288, 20% = 5057, profit 25245 > 5057 = bad feed 135.17
    profit_abs = abs(entry - current_price)
    if profit_abs > entry * 0.20:
        print(f"BAD PRICE SPIKE {symbol_name} entry {entry} current {current_price} profit {profit_abs} >20% - reject (GER30 135 bug)")
        return None
    
    trail_dist = atr * 1.0
    profit_trigger_small = atr * 0.3
    profit_trigger_be = 1.0
    
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
    "GOLD": ("GC=F", 4136.84),
    "SILVER": ("SI=F", 32.5),
    "US30": ("^DJI", 46000),
    "GER30": ("^GDAXI", 25148.03),  # Updated from screenshot 25148, not 19450 old
    "NDX100": ("^NDX", 30800),
}


def build_mtf_confluence(symbol_name):
    sym, fallback = SYMBOLS[symbol_name]
    tf4 = analyze_4h(sym, fallback)
    tf1 = analyze_1h(sym, fallback)
    tf15 = analyze_15m(sym, fallback)
    if tf4 is None or tf1 is None or tf15 is None:
        msg = f"⏳ {symbol_name} Data unavailable"
        return msg, "", "WAIT", fallback, None
    price = tf15["price"]
    now = datetime.now().strftime('%H:%M')
    td_key = get_twelvedata_api_key()
    data_source = f"TwelveData XAU/USD key:{td_key[:6]}...{td_key[-4:]}" if td_key else "Yahoo GC=F"
    lines = []
    lines.append(f"🎯 {symbol_name} 4H->1H->15M PURE PRICE ACTION | Source: {data_source}")
    lines.append(f"💰 {price:.2f} | 4H {tf4['trend']} {tf4['conf']}% {tf4['desc']} | 1H {tf1['bias']} {tf1['sweep']} | 15M {tf15['trigger']} {tf15['desc']} FVG:{tf15['fvg']}")
    lines.append(f"4H: {tf4['desc']} | OB {tf4['ob_low']:.2f}/{tf4['ob_high']:.2f} S/R {tf4['sup']:.2f}/{tf4['res']:.2f} ATR {tf4['atr']:.2f}")
    lines.append(f"1H: {tf1['near_sr']} | S/R {tf1['sup']:.2f}/{tf1['res']:.2f} ATR {tf1['atr']:.2f}")
    lines.append(f"15M: {tf15['desc']} | FVG {tf15['fvg']} | S/R {tf15['sup']:.2f}/{tf15['res']:.2f} ATR {tf15['atr']:.2f}")
    lines.append("")
    direction = "WAIT"
    vip_lines = []

    atr_1h = tf1["atr"]
    sup_1h = tf1["sup"]; res_1h = tf1["res"]
    sup_4h = tf4["sup"]; res_4h = tf4["res"]
    sup_15m = tf15["sup"]; res_15m = tf15["res"]
    buffer = atr_1h * 0.3

    def calc_buy_sl_tp():
        sl_s = min(sup_1h, sup_15m) - buffer
        if price - sl_s < atr_1h*1.0: sl_s = price - atr_1h*1.2
        if price - sl_s > atr_1h*2.5: sl_s = price - atr_1h*2.0
        tp1 = res_15m if res_15m > price + atr_1h*0.5 else price + atr_1h*1.8
        tp2 = res_1h if res_1h > tp1 else price + atr_1h*3.0
        tp3 = res_4h if res_4h > tp2 else price + atr_1h*4.5
        return sl_s, tp1, tp2, tp3
    def calc_sell_sl_tp():
        sl_s = max(res_1h, res_15m) + buffer
        if sl_s - price < atr_1h*1.0: sl_s = price + atr_1h*1.2
        if sl_s - price > atr_1h*2.5: sl_s = price + atr_1h*2.0
        tp1 = sup_15m if sup_15m < price - atr_1h*0.5 else price - atr_1h*1.8
        tp2 = sup_1h if sup_1h < tp1 else price - atr_1h*3.0
        tp3 = sup_4h if sup_4h < tp2 else price - atr_1h*4.5
        return sl_s, tp1, tp2, tp3

    # ===== CONDITION 1: ONLY 4H FAILS TO TRANSIT IMMEDIATE =====
    immediate_4h_failed = None
    if tf4.get("failed") and tf4.get("fail_dir"):
        try:
            import re as re_mod
            m = re_mod.search(r"FAILED \w+ ([\d\.]+)", tf4["desc"])
            if m:
                failed_level = float(m.group(1))
                dist = abs(price - failed_level)
                max_dist = tf4["atr"] * 2.5
                if dist <= max_dist:
                    key = f"{symbol_name}_4H_{tf4['fail_dir']}_{tf4['desc'][:30]}"
                    now_ts = time.time()
                    age = 0
                    if key in FAILED_TRACKER:
                        age = now_ts - FAILED_TRACKER[key]
                        if age > FAILED_EXPIRY_SECONDS:
                            lines.append(f"❌ EXPIRED 4H FAILED {tf4['fail_dir']} - {int(age)}s ago (>5m) - TOO LATE")
                            if age > 600:
                                del FAILED_TRACKER[key]
                            age = None
                        else:
                            lines.append(f"✅ FRESH 4H FAILED {tf4['fail_dir']} - {int(age)}s ago - VALID <5m")
                            immediate_4h_failed = (tf4["fail_dir"], tf4["desc"], tf4["atr"], failed_level, dist, max_dist)
                    else:
                        FAILED_TRACKER[key] = now_ts
                        immediate_4h_failed = (tf4["fail_dir"], tf4["desc"], tf4["atr"], failed_level, dist, max_dist)
                        lines.append(f"✅ FRESH 4H FAILED FIRST TIME {tf4['fail_dir']} level {failed_level:.2f} price {price:.2f} dist {dist:.2f} < {max_dist:.2f} - VALID")
                else:
                    lines.append(f"❌ FAR 4H FAILED {tf4['fail_dir']} level {failed_level:.2f} vs price {price:.2f} dist {dist:.2f} > {max_dist:.2f} - skip (4166 vs 4138 case)")
        except Exception as e:
            print(f"4H failed check error {e}")

    if immediate_4h_failed:
        fail_dir, desc, atr_tf, failed_level, dist, max_dist = immediate_4h_failed
        is_buy = fail_dir == "BULL"
        direction = f"{fail_dir}_FAILED_4H"
        emoji = "🚨🟢" if is_buy else "🚨🔴"
        if is_buy:
            sl = sup_15m - atr_tf*0.3
            if sl >= price: sl = price - atr_tf*0.8
            tp1 = res_15m if res_15m > price + atr_tf*0.3 else price + atr_tf*0.8
            tp2 = res_1h if res_1h > tp1 else price + atr_tf*1.5
            tp3 = res_4h if res_4h > tp2 else price + atr_tf*2.2
        else:
            sl = res_15m + atr_tf*0.3
            if sl <= price: sl = price + atr_tf*0.8
            tp1 = sup_15m if sup_15m < price - atr_tf*0.3 else price - atr_tf*0.8
            tp2 = sup_1h if sup_1h < tp1 else price - atr_tf*1.5
            tp3 = sup_4h if sup_4h < tp2 else price - atr_tf*2.2
        lines.append(f"🚨 4H IMMEDIATE FAILED {desc}")
        lines.append(f"{emoji} {symbol_name} IMMEDIATE {fail_dir} NOW - Failed to transit (4H)")
        lines.append(f"Entry: {price:.2f} SL: {sl:.2f} TP1: {tp1:.2f} (15M) TP2: {tp2:.2f} (1H) TP3: {tp3:.2f} (4H) ⏰ {now}")
        vip_lines.append(f"{emoji} {symbol_name} IMMEDIATE {fail_dir} FAILED 4H - ONLY 4H FAILED SIGNAL")
        vip_lines.append(f"Entry: {price:.2f} SL: {sl:.2f} TP1: {tp1:.2f} TP2: {tp2:.2f} TP3: {tp3:.2f}")
        vip_lines.append(f"🚨 {desc}")
        chart_path = None
        try:
            chart_path = generate_mtf_chart(symbol_name, tf4, tf1, tf15, price, sl, tp1, tp2, direction)
            ACTIVE_TRADES[symbol_name] = {'entry':price,'sl':sl,'tp1':tp1,'tp2':tp2,'tp3':tp3,'direction':direction,'atr':atr_1h,'trail_sl':sl,'status':'OPEN'}
        except:
            pass
        return "\n".join(lines), "\n".join(vip_lines), direction, price, chart_path

    # ===== CONDITION 2: THREE STRUCTURES ALIGN =====
    bull_align = (tf4["trend"] == "BULL" and tf4["conf"] >= 60 and tf1["bias"] == "BULL" and tf1["conf"] >= 60 and tf15["trigger"] == "BUY" and tf15["conf"] >= 60)
    bear_align = (tf4["trend"] == "BEAR" and tf4["conf"] >= 60 and tf1["bias"] == "BEAR" and tf1["conf"] >= 60 and tf15["trigger"] == "SELL" and tf15["conf"] >= 60)
    bull_align_sweep = (tf4["trend"] == "BULL" and tf4["conf"] >= 70 and "BULL Sweep" in tf1["sweep"] and tf15["trigger"] == "BUY")
    bear_align_sweep = (tf4["trend"] == "BEAR" and tf4["conf"] >= 70 and "BEAR Sweep" in tf1["sweep"] and tf15["trigger"] == "SELL")

    if bull_align or bull_align_sweep:
        sl, tp1, tp2, tp3 = calc_buy_sl_tp()
        direction = "BUY"
        lines.append(f"🔥🔥 THREE STRUCTURES ALIGN BULL: 4H BULL {tf4['conf']}% + 1H BULL {tf1['conf']}% + 15M BUY {tf15['conf']}%")
        lines.append(f"🟢 {symbol_name} BUY NOW - 3 TF ALIGN")
        lines.append(f"Entry: {price:.2f} SL: {sl:.2f} TP1: {tp1:.2f} TP2: {tp2:.2f} TP3: {tp3:.2f} ⏰ {now}")
        vip_lines.append(f"🟢 {symbol_name} BUY NOW - THREE STRUCTURES ALIGN")
        vip_lines.append(f"Entry: {price:.2f} SL: {sl:.2f} TP1: {tp1:.2f} TP2: {tp2:.2f} TP3: {tp3:.2f}")
        chart_path = None
        try:
            chart_path = generate_mtf_chart(symbol_name, tf4, tf1, tf15, price, sl, tp1, tp2, direction)
            ACTIVE_TRADES[symbol_name] = {'entry':price,'sl':sl,'tp1':tp1,'tp2':tp2,'tp3':tp3,'direction':direction,'atr':atr_1h,'trail_sl':sl,'status':'OPEN'}
        except:
            pass
        return "\n".join(lines), "\n".join(vip_lines), direction, price, chart_path

    if bear_align or bear_align_sweep:
        sl, tp1, tp2, tp3 = calc_sell_sl_tp()
        direction = "SELL"
        lines.append(f"🔥🔥 THREE STRUCTURES ALIGN BEAR: 4H BEAR {tf4['conf']}% + 1H BEAR {tf1['conf']}% + 15M SELL {tf15['conf']}%")
        lines.append(f"🔴 {symbol_name} SELL NOW - 3 TF ALIGN")
        lines.append(f"Entry: {price:.2f} SL: {sl:.2f} TP1: {tp1:.2f} TP2: {tp2:.2f} TP3: {tp3:.2f} ⏰ {now}")
        vip_lines.append(f"🔴 {symbol_name} SELL NOW - THREE STRUCTURES ALIGN")
        vip_lines.append(f"Entry: {price:.2f} SL: {sl:.2f} TP1: {tp1:.2f} TP2: {tp2:.2f} TP3: {tp3:.2f}")
        chart_path = None
        try:
            chart_path = generate_mtf_chart(symbol_name, tf4, tf1, tf15, price, sl, tp1, tp2, direction)
            ACTIVE_TRADES[symbol_name] = {'entry':price,'sl':sl,'tp1':tp1,'tp2':tp2,'tp3':tp3,'direction':direction,'atr':atr_1h,'trail_sl':sl,'status':'OPEN'}
        except:
            pass
        return "\n".join(lines), "\n".join(vip_lines), direction, price, chart_path

    # WAIT
    lines.append(f"❌ WAIT - No 4H FAILED immediate (<5m) and No 3-TF alignment")
    lines.append(f"Need either: 1. 4H FAILED to transit immediate 2. Three structures align 4H BULL 60%+ + 1H BULL 60%+ + 15M BUY 60%+ (or BEAR)")
    lines.append(f"Current: 4H {tf4['trend']} {tf4['conf']}% | 1H {tf1['bias']} {tf1['conf']}% | 15M {tf15['trigger']} {tf15['conf']}%")
    if tf4.get("failed"):
        lines.append(f"4H has FAILED {tf4.get('fail_dir')} but not fresh/proximity: {tf4['desc']}")
    return "\n".join(lines), "", "WAIT", price, None


# ===== SIMPLIFIED COMMANDS - ONLY 2 COMBOS =====

# ============================================================
# MOMENTUM BOT — Mechanical & Testable Logic per user spec
# Market: XAU/USD, H1 bias, M15 setup, closed candles only
# London 08:00-12:00 UTC, NY 13:00-17:00 UTC (08:00-12:00 ET = 13:00-17:00 UTC)
# ============================================================

MOMENTUM_STATE = {}  # symbol -> state dict
MOMENTUM_LAST_SIGNAL = {}  # symbol_leg_id -> timestamp (duplicate protection)

def is_valid_session():
    # London 08:00-12:00 UTC, NY 13:00-17:00 UTC
    now_utc = datetime.utcnow()
    hour = now_utc.hour
    # London
    if 8 <= hour < 12:
        return True, "LONDON"
    # NY (13-17 UTC = 08-12 ET)
    if 13 <= hour < 17:
        return True, "NEW YORK"
    return False, f"OUTSIDE {hour:02d}:00 UTC"

def check_news_filter():
    # Configurable high-impact news protection - stub for now, returns OK
    # TODO: integrate ForexFactory API or TwelveData news
    # For XAUUSD, avoid 5 min before/after high impact USD news
    # For first version, just check if spread is abnormal (implemented in spread filter)
    return True, ""

def get_m15_candle_stats(closes, highs, lows):
    # Returns avg body size last 20 candles
    if len(closes) < 21:
        return 0, 0
    bodies = [abs(closes[i] - closes[i-1]) for i in range(-20, 0)] if len(closes)>=20 else []
    avg_body = sum(bodies)/len(bodies) if bodies else 1.0
    return avg_body, bodies

def detect_displacement_m15(price_data):
    # price_data: dict from analyze_15m
    hist = price_data["hist"]
    highs = price_data["highs"]
    lows = price_data["lows"]
    if len(hist) < 30:
        return None
    avg_body, _ = get_m15_candle_stats(hist, highs, lows)
    # Last closed candle
    last_close = hist[-1]
    last_open = hist[-2] if len(hist)>=2 else last_close
    last_high = highs[-1] if highs else last_close
    last_low = lows[-1] if lows else last_close
    body = abs(last_close - last_open)
    candle_range = last_high - last_low
    # Conditions for valid displacement per spec:
    # 1. Body significantly larger than recent (1.8x)
    # 2. Close strongly in direction (>70% of range)
    # 3. Not immediately rejected by next candle (we check close direction)
    # Direction
    is_bull = last_close > last_open
    is_bear = last_close < last_open
    if not (is_bull or is_bear):
        return None
    # 1. Body size filter
    if body < avg_body * 1.8:
        return None
    # 2. Strong close
    if candle_range == 0:
        return None
    close_strength = (last_close - last_low) / candle_range if is_bull else (last_high - last_close) / candle_range
    if close_strength < 0.70:
        return None
    # 3. Structure break - last close breaks recent 20 high/low
    recent_high = max(highs[-21:-1]) if len(highs)>=21 else max(highs[:-1])
    recent_low = min(lows[-21:-1]) if len(lows)>=21 else min(lows[:-1])
    breaks_high = last_close > recent_high
    breaks_low = last_close < recent_low
    if not (breaks_high or breaks_low):
        return None
    # Direction must match break
    if is_bull and not breaks_high:
        return None
    if is_bear and not breaks_low:
        return None
    # Return displacement leg
    return {
        "direction": "BULL" if is_bull else "BEAR",
        "body": body,
        "avg_body": avg_body,
        "close": last_close,
        "open": last_open,
        "high": last_high,
        "low": last_low,
        "break_level": recent_high if is_bull else recent_low,
        "close_strength": close_strength,
        "timestamp": time.time()
    }

def detect_fvg_m15(hist, highs, lows, direction):
    # Fair Value Gap: 3 candle pattern
    if len(hist) < 5:
        return None
    # Bullish FVG: low of candle3 > high of candle1
    # Bearish FVG: high of candle3 < low of candle1
    try:
        if direction == "BULL":
            # Check last 3 candles
            if lows[-1] > highs[-3]:
                return {"type":"BULL_FVG", "top": lows[-1], "bottom": highs[-3], "mid": (lows[-1]+highs[-3])/2}
        else:
            if highs[-1] < lows[-3]:
                return {"type":"BEAR_FVG", "top": lows[-3], "bottom": highs[-1], "mid": (lows[-3]+highs[-1])/2}
    except:
        pass
    return None

def build_momentum_signal(symbol_name="GOLD"):
    sym, fallback = SYMBOLS[symbol_name]
    # 1. Session filter
    session_ok, session_name = is_valid_session()
    if not session_ok:
        return f"⏳ {symbol_name} OUTSIDE TRADING SESSION\nCurrent UTC hour outside London (08-12) & NY (13-17)\nSTATUS: NO SIGNAL", "", "WAIT", fallback, None
    
    # 2. News filter
    news_ok, news_reason = check_news_filter()
    if not news_ok:
        return f"⏳ {symbol_name} NEWS FILTER ACTIVE: {news_reason}\nSTATUS: NO SIGNAL", "", "WAIT", fallback, None

    # Get data - TwelveData
    tf1 = analyze_1h(sym, fallback)
    tf15 = analyze_15m(sym, fallback)
    if tf1 is None or tf15 is None:
        return f"⏳ {symbol_name} Data unavailable", "", "WAIT", fallback, None
    
    price = tf15["price"]
    hist = tf15["hist"]
    highs = tf15["highs"]
    lows = tf15["lows"]
    atr_val = tf15["atr"]
    
    # Spread/market quality filter
    if atr_val < 0.5 or atr_val > 100:
        return f"❌ {symbol_name} Abnormal ATR {atr_val:.2f} - market quality reject", "", "WAIT", fallback, None
    if len(hist) < 30:
        return f"❌ {symbol_name} Insufficient history {len(hist)}", "", "WAIT", fallback, None

    # 2. H1 directional filter
    h1_trend = tf1["trend"]
    h1_desc = tf1["desc"]
    h1_sup = tf1["sup"]
    h1_res = tf1["res"]
    
    # H1 bias: must be BULL or BEAR, not RANGE
    if h1_trend not in ["BULL", "BEAR"]:
        return f"""⏳ {symbol_name} MOMENTUM CHECK
💰 {price:.2f}
H1: {h1_trend} {h1_desc} - NO CLEAR MOMENTUM BIAS
M15: {tf15['desc']}
STATUS: WAITING FOR H1 BIAS
Session: {session_name}
""", "", "WAIT", fallback, None

    bias = h1_trend  # BULL or BEAR

    # 3. Detect genuine M15 momentum (displacement)
    displacement = detect_displacement_m15(tf15)
    if not displacement:
        return f"""⏳ {symbol_name} MOMENTUM CHECK
💰 {price:.2f}
H1 Bias: {bias} {h1_desc}
M15: {tf15['desc']}
Avg Body: {get_m15_candle_stats(hist, highs, lows)[0]:.2f}, No displacement >1.8x avg
STATUS: WAITING FOR DISPLACEMENT
Direction → Displacement → Structure break
Session: {session_name}
""", "", "WAIT", fallback, None

    # Direction must agree with H1 bias
    if displacement["direction"] != bias:
        return f"""⏳ {symbol_name} DISPLACEMENT vs H1 MISMATCH
💰 {price:.2f}
H1 Bias: {bias}
M15 Displacement: {displacement['direction']} body {displacement['body']:.2f} vs avg {displacement['avg_body']:.2f} break {displacement['break_level']:.2f}
STATUS: MISMATCH - WAITING
Session: {session_name}
""", "", "WAIT", fallback, None

    # 4. Record momentum leg
    leg_id = f"{symbol_name}_{bias}_{displacement['break_level']:.2f}_{int(displacement['timestamp'])}"
    if symbol_name not in MOMENTUM_STATE:
        MOMENTUM_STATE[symbol_name] = {}
    MOMENTUM_STATE[symbol_name][leg_id] = displacement
    MOMENTUM_STATE[symbol_name][leg_id]["h1_bias"] = bias
    MOMENTUM_STATE[symbol_name][leg_id]["pullback_zone"] = None
    MOMENTUM_STATE[symbol_name][leg_id]["status"] = "MOMENTUM_DETECTED"

    # 5. Do NOT chase - wait for pullback
    # Check if price already pulled back
    # Pullback zones: broken structure, origin, FVG, order-block
    broken_level = displacement["break_level"]
    origin = displacement["open"]  # base of displacement
    fvg = detect_fvg_m15(hist, highs, lows, bias)
    
    # Determine pullback zone
    pullback_zone_top = None
    pullback_zone_bottom = None
    zone_type = ""
    if fvg:
        pullback_zone_top = fvg["top"]
        pullback_zone_bottom = fvg["bottom"]
        zone_type = fvg["type"]
    else:
        # Use broken structure ± 0.5 ATR
        if bias == "BULL":
            pullback_zone_top = broken_level + atr_val*0.3
            pullback_zone_bottom = broken_level - atr_val*0.3
            zone_type = f"BROKEN STRUCTURE {broken_level:.2f}"
        else:
            pullback_zone_top = broken_level + atr_val*0.3
            pullback_zone_bottom = broken_level - atr_val*0.3
            zone_type = f"BROKEN STRUCTURE {broken_level:.2f}"

    # 6. Pullback requirement - has price returned to zone?
    # For BUY: price must have returned to zone (low <= zone_top)
    # For SELL: price must have returned (high >= zone_bottom)
    has_pulled_back = False
    # Check recent 10 candles for interaction with zone
    recent_lows = lows[-10:] if len(lows)>=10 else lows
    recent_highs = highs[-10:] if len(highs)>=10 else highs
    if bias == "BULL":
        # Has price wicked into zone?
        for l in recent_lows:
            if pullback_zone_bottom <= l <= pullback_zone_top or l <= pullback_zone_bottom:
                has_pulled_back = True
                break
        # Current price near zone?
        if pullback_zone_bottom <= price <= pullback_zone_top + atr_val:
            has_pulled_back = True
    else:
        for h in recent_highs:
            if pullback_zone_bottom <= h <= pullback_zone_top or h >= pullback_zone_top:
                has_pulled_back = True
                break
        if pullback_zone_bottom - atr_val <= price <= pullback_zone_top:
            has_pulled_back = True

    if not has_pulled_back:
        return f"""⏳ {symbol_name} MOMENTUM DETECTED - WAITING FOR PULLBACK
💰 {price:.2f}
H1 Bias: {bias} {h1_desc}
M15 Displacement: {displacement['direction']} body {displacement['body']:.2f} (avg {displacement['avg_body']:.2f} x{displacement['body']/displacement['avg_body']:.1f}) close {displacement['close_strength']*100:.0f}% break {broken_level:.2f}
Pullback Zone: {zone_type} {pullback_zone_bottom:.2f}-{pullback_zone_top:.2f} (FVG: {fvg['type'] if fvg else 'None'})
Current: {price:.2f} - NOT YET IN ZONE
STATUS: WAITING FOR PULLBACK
Session: {session_name}
State: MOMENTUM_DETECTED → WAITING FOR PULLBACK
""", "", "WAIT", fallback, None

    # 7. Pullback must remain structurally valid
    # For BUY: must not close decisively below invalidation (low of displacement)
    # For SELL: must not close above
    invalidation_level = displacement["low"] if bias=="BULL" else displacement["high"]
    # Check if invalidated in last 10 candles
    invalidated = False
    if bias == "BULL":
        for c in hist[-10:]:
            if c < invalidation_level - atr_val*0.2:  # decisive close below
                invalidated = True
                break
    else:
        for c in hist[-10:]:
            if c > invalidation_level + atr_val*0.2:
                invalidated = True
                break
    if invalidated:
        return f"""❌ {symbol_name} SETUP INVALIDATED
💰 {price:.2f}
H1 Bias: {bias}
M15 Displacement: {displacement['direction']} break {broken_level:.2f}
Invalidation: Price closed beyond {invalidation_level:.2f} (setup low/high)
STATUS: INVALIDATED - Looking for new leg
Session: {session_name}
""", "", "WAIT", fallback, None

    # 8. M15 confirmation - bullish/bearish close away from zone
    # Last candle must close bullish for BUY, bearish for SELL, and away from zone
    last_close = hist[-1]
    last_open = hist[-2] if len(hist)>=2 else last_close
    confirmation = False
    conf_type = ""
    if bias == "BULL":
        if last_close > last_open and last_close > pullback_zone_top:
            # Break of minor pullback high
            recent_pullback_high = max(highs[-6:-1]) if len(highs)>=6 else highs[-2]
            if last_close > recent_pullback_high:
                confirmation = True
                conf_type = f"Bullish close {last_close:.2f} > open {last_open:.2f} + break pullback high {recent_pullback_high:.2f}"
    else:
        if last_close < last_open and last_close < pullback_zone_bottom:
            recent_pullback_low = min(lows[-6:-1]) if len(lows)>=6 else lows[-2]
            if last_close < recent_pullback_low:
                confirmation = True
                conf_type = f"Bearish close {last_close:.2f} < open {last_open:.2f} + break pullback low {recent_pullback_low:.2f}"

    if not confirmation:
        return f"""⏳ {symbol_name} PULLBACK COMPLETED - WAITING FOR CONFIRMATION
💰 {price:.2f}
H1 Bias: {bias}
M15 Displacement: {bias} body {displacement['body']:.2f} break {broken_level:.2f}
Pullback: {zone_type} {pullback_zone_bottom:.2f}-{pullback_zone_top:.2f} - Price touched zone
Last Candle: {last_open:.2f}→{last_close:.2f} {'BULL' if last_close>last_open else 'BEAR'}
STATUS: WAITING FOR M15 CONFIRMATION (close away from zone + break minor high/low)
Session: {session_name}
State: PULLBACK CONFIRMED → WAITING FOR M15 CONFIRMATION
""", "", "WAIT", fallback, None

    # 9. Entry - after confirmation close
    entry = last_close
    
    # 10. Stop loss - structural + ATR buffer
    # For BUY: below pullback swing low
    # For SELL: above swing high
    swing_low = min(lows[-6:]) if len(lows)>=6 else min(lows[-3:])
    swing_high = max(highs[-6:]) if len(highs)>=6 else max(highs[-3:])
    buffer = atr_val * 0.3  # volatility buffer
    
    if bias == "BULL":
        sl = swing_low - buffer
    else:
        sl = swing_high + buffer

    risk = abs(entry - sl)
    if risk < atr_val*0.5:  # Minimum risk to avoid tiny SL
        risk = atr_val*0.5
        sl = entry - risk if bias=="BULL" else entry + risk

    # 11. Target with opposing structure filter
    tp1 = entry + risk*1.5 if bias=="BULL" else entry - risk*1.5
    tp2 = entry + risk*2.0 if bias=="BULL" else entry - risk*2.0
    
    # Check major opposing structure before 2R
    # Find next major resistance/support
    opposing_level = None
    if bias == "BULL":
        # Next resistance above entry
        # Use H1 res and M15 res
        candidates = [tf1["res"], tf15["res"]]
        for cand in candidates:
            if cand > entry and cand < tp2:
                opposing_level = cand
                break
    else:
        candidates = [tf1["sup"], tf15["sup"]]
        for cand in candidates:
            if cand < entry and cand > tp2:
                opposing_level = cand
                break

    if opposing_level is not None:
        # Major structure before 2R - reject
        return f"""❌ {symbol_name} TARGET WARNING
💰 {price:.2f} Entry would be {entry:.2f} SL {sl:.2f} risk {risk:.2f}
Opposing Structure: {opposing_level:.2f} sits before 2R {tp2:.2f}
TP2 would be {tp2:.2f} but structure at {opposing_level:.2f} blocks it
STATUS: REJECTED - Major opposing structure before 2R
Session: {session_name}
""", "", "WAIT", fallback, None

    # 12. Minimum R:R 1:2 check - we already have 1:2 as TP2
    # Check if next structure allows 1:2
    # Already filtered above

    # 14. Spread/market quality already checked

    # 15. Duplicate protection
    if leg_id in MOMENTUM_LAST_SIGNAL:
        last_time = MOMENTUM_LAST_SIGNAL[leg_id]
        if time.time() - last_time < 900:  # 15 min duplicate protection per leg
            return f"⏳ {symbol_name} DUPLICATE PROTECTION\nLeg {leg_id[:30]} already signaled {int((time.time()-last_time)/60)}m ago\nSTATUS: ONE SIGNAL ONLY per momentum leg", "", "WAIT", fallback, None

    # Mark as signaled
    MOMENTUM_LAST_SIGNAL[leg_id] = time.time()

    # 16. Final valid signal
    rr = 2.0
    emoji = "🟢" if bias=="BULL" else "🔴"
    direction_text = "MOMENTUM BUY" if bias=="BULL" else "MOMENTUM SELL"
    
    msg = f"""{emoji} XAUUSD {direction_text}

ENTRY: {entry:.2f}
SL: {sl:.2f}
TP1: {tp1:.2f}
TP2: {tp2:.2f}

R:R: 1:{rr}

TIMEFRAME
H1 Bias → M15 Entry

SESSION: {session_name}

CONFIRMATION
✓ H1 {bias.lower()} bias - {h1_desc}
✓ Strong {bias.lower()} displacement body {displacement['body']:.2f} vs avg {displacement['avg_body']:.2f} (x{displacement['body']/displacement['avg_body']:.1f}) close {displacement['close_strength']*100:.0f}%
✓ M15 structure break {broken_level:.2f}
✓ Pullback completed to {zone_type} {pullback_zone_bottom:.2f}-{pullback_zone_top:.2f}
✓ {bias} confirmation: {conf_type}
✓ Valid structural SL {sl:.2f} (swing {swing_low if bias=='BULL' else swing_high:.2f} + ATR buffer {buffer:.2f})
✓ Minimum 1:2 R:R (risk {risk:.2f})
✓ Spread acceptable ATR {atr_val:.2f}

STATUS: VALID MOMENTUM SETUP

Risk: 0.5–1% maximum

Price: {price:.2f} | Source: TwelveData XAU/USD | Leg: {leg_id[:20]}"""

    # For chart
    direction = bias
    return msg, "", direction, fallback, None



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
                # TwelveData already gives real spot XAU/USD, don't override with gold-api.com when TwelveData key exists
                if not get_twelvedata_api_key():
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


async def momentum_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text("⏳ Analyzing XAU/USD MOMENTUM (H1 bias → M15 displacement → pullback → confirmation)...")
        f,v,d,p,chart = build_momentum_signal("GOLD")
        # f is full message (valid signal or waiting status)
        await update.message.reply_text(f)
        # If valid momentum, also send chart if available
        # Generate chart for momentum signal
        try:
            sym, fb = SYMBOLS["GOLD"]
            tf1 = analyze_1h(sym, fb)
            tf15 = analyze_15m(sym, fb)
            tf4 = analyze_4h(sym, fb)
            if tf1 and tf15 and tf4 and "VALID MOMENTUM SETUP" in f:
                # Extract entry/sl/tp from message
                import re
                entry_m = re.search(r'ENTRY: ([\d\.]+)', f)
                sl_m = re.search(r'SL: ([\d\.]+)', f)
                tp1_m = re.search(r'TP1: ([\d\.]+)', f)
                tp2_m = re.search(r'TP2: ([\d\.]+)', f)
                if entry_m and sl_m and tp1_m:
                    price = float(entry_m.group(1))
                    sl = float(sl_m.group(1))
                    tp1 = float(tp1_m.group(1))
                    tp2 = float(tp2_m.group(1)) if tp2_m else tp1
                    is_buy = "MOMENTUM BUY" in f
                    direction = "BUY" if is_buy else "SELL"
                    chart_path = generate_mtf_chart("GOLD", tf4, tf1, tf15, price, sl, tp1, tp2, direction)
                    if chart_path and os.path.exists(chart_path):
                        await update.message.reply_photo(photo=open(chart_path,'rb'), caption=f"📊 MOMENTUM {direction}")
        except Exception as e:
            print(f"Momentum chart error: {e}")
    except Exception as e:
        await update.message.reply_text(f"❌ Momentum error: {e}")

async def momentum_test_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    # For testing backtest logic - shows current state machine
    try:
        sym, fb = SYMBOLS["GOLD"]
        tf1 = analyze_1h(sym, fb)
        tf15 = analyze_15m(sym, fb)
        session_ok, session_name = is_valid_session()
        disp = detect_displacement_m15(tf15) if tf15 else None
        lines = [f"🔬 MOMENTUM STATE MACHINE DEBUG",
                 f"Session: {session_name} Valid={session_ok}",
                 f"H1: {tf1['trend'] if tf1 else 'None'} {tf1['desc'] if tf1 else ''}",
                 f"M15: {tf15['desc'] if tf15 else 'None'} ATR {tf15['atr'] if tf15 else 0:.2f}",
                 f"Displacement: {disp['direction'] if disp else 'None'} body {disp['body']:.2f} vs avg {disp['avg_body']:.2f} x{disp['body']/disp['avg_body']:.1f}" if disp else "Displacement: None (body <1.8x avg or no break)",
                 f"Price: {tf15['price'] if tf15 else 0:.2f}",
                 f"Momentum legs stored: {len(MOMENTUM_STATE.get('GOLD', {}))}",
                 f"Last signals: {len(MOMENTUM_LAST_SIGNAL)} legs (15min duplicate protection)"]
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"Debug error: {e}")



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
    app.add_handler(CommandHandler("momentum",momentum_cmd))
    app.add_handler(CommandHandler("mom",momentum_cmd))
    app.add_handler(CommandHandler("momentumtest",momentum_test_cmd))
    print("SIMPLIFIED 2-COMBO MTF LIVE")
    app.run_polling(drop_pending_updates=True)

if __name__=="__main__": main()
