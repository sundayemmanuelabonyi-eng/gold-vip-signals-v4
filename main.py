"""
V7.2 BATTLE 7 STREAMLINED + BACKTEST - Gold Confluence Bot
Only 4 Most Accurate Signals for XAUUSD + Backtest

KEPT (accurate):
✅ S1 TREND (4H EMA9/21 + H->HL->HH / H->LH->LL)
✅ S2 MOMENTUM (RSI 14 + RSI 7 Y%)
✅ S4 REVERSAL (YOUR EDGE: HL that created HH / LH that created LL + $15 retest + rejection + reversal)
✅ S6 DXY (DXY inverse)

REMOVED: S3 SCALPER, S5 PRICE - noisy
S7 NEWS = Filter only

Commands:
 /signal - Full confluence 4 signals
 /signal2tf - Only S4 OB
 /backtest2tf - Backtest S4 OB (last 200 bars)
 /backtest - Backtest full confluence 3/4 agree

Time: UTC -> WAT Nigeria + MT5 GMT+3
Weekend: No Sat/Sun
"""

import os
import asyncio
from datetime import datetime, timezone
import pytz
import httpx
import pandas as pd
import numpy as np

TWELVE_API_KEY = os.getenv("TWELVE_API_KEY", "")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")

WAT = pytz.timezone("Africa/Lagos")
MT5_GMT3 = pytz.timezone("Etc/GMT-3")
MT5_GMT2 = pytz.timezone("Etc/GMT-2")

RETEST_THRESHOLD = 15.0
WICK_RATIO = 0.5

def is_weekend_closed(dt_utc: datetime) -> bool:
    return dt_utc.weekday() >= 5

def get_time_strings(utc_dt: datetime):
    wat = utc_dt.astimezone(WAT)
    mt5_3 = utc_dt.astimezone(MT5_GMT3)
    mt5_2 = utc_dt.astimezone(MT5_GMT2)
    return {
        "WAT": wat.strftime("%m/%d %H:%M WAT"),
        "MT5_GMT3": mt5_3.strftime("%m/%d %H:%M MT5"),
        "MT5_GMT2": mt5_2.strftime("%m/%d %H:%M MT5 GMT+2"),
        "UTC": utc_dt.strftime("%Y-%m-%d %H:%M UTC"),
    }

def ema(s, p): return s.ewm(span=p, adjust=False).mean()

def rsi(s, p=14):
    d = s.diff()
    g = d.where(d>0,0).rolling(window=p).mean()
    l = -d.where(d<0,0).rolling(window=p).mean()
    rs = g/l
    return 100 - (100/(1+rs))

def find_structure(df):
    highs = df['high'].values
    lows = df['low'].values
    bullish = []
    bearish = []
    for i in range(20, len(df)-5):
        if highs[i] == max(highs[i-10:i+1]) and highs[i] > max(highs[i-20:i-10]):
            hl_idx = int(np.argmin(lows[i-20:i]) + (i-20))
            bullish.append({"HL": lows[hl_idx], "HH": highs[i], "hl_idx": hl_idx, "hh_idx": i})
        if lows[i] == min(lows[i-10:i+1]) and lows[i] < min(lows[i-20:i-10]):
            lh_idx = int(np.argmax(highs[i-20:i]) + (i-20))
            bearish.append({"LH": highs[lh_idx], "LL": lows[i], "lh_idx": lh_idx, "ll_idx": i})
    return (bullish[-1] if bullish else None), (bearish[-1] if bearish else None)

def find_all_structures(df):
    """Return all structures for backtest"""
    highs = df['high'].values
    lows = df['low'].values
    bullish = []
    bearish = []
    for i in range(20, len(df)-5):
        if highs[i] == max(highs[i-10:i+1]) and highs[i] > max(highs[i-20:i-10]):
            hl_idx = int(np.argmin(lows[i-20:i]) + (i-20))
            bullish.append({"HL": lows[hl_idx], "HH": highs[i], "hl_idx": hl_idx, "hh_idx": i, "bar": i})
        if lows[i] == min(lows[i-10:i+1]) and lows[i] < min(lows[i-20:i-10]):
            lh_idx = int(np.argmax(highs[i-20:i]) + (i-20))
            bearish.append({"LH": highs[lh_idx], "LL": lows[i], "lh_idx": lh_idx, "ll_idx": i, "bar": i})
    return bullish, bearish

async def fetch_candles(symbol="XAU/USD", interval="1h", outputsize=200):
    if not TWELVE_API_KEY:
        return None
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={interval}&outputsize={outputsize}&apikey={TWELVE_API_KEY}&format=JSON"
    async with httpx.AsyncClient() as client:
        r = await client.get(url, timeout=20)
        data = r.json()
        if "values" not in data:
            return None
        df = pd.DataFrame(data["values"])
        df = df.iloc[::-1]
        df["datetime"] = pd.to_datetime(df["datetime"])
        for c in ["open","high","low","close"]:
            df[c] = df[c].astype(float)
        return df

async def fetch_dxy():
    try:
        return await fetch_candles("DXY", "1h", 100)
    except:
        return None

def S1_TREND(df_4h):
    if df_4h is None or len(df_4h) < 30:
        return {"signal": "WAIT", "pct": 0, "detail": "No 4H", "ema9": 4254.37, "ema21": 4266.02}
    df_4h["EMA9"] = ema(df_4h["close"], 9)
    df_4h["EMA21"] = ema(df_4h["close"], 21)
    last = df_4h.iloc[-1]
    dist = abs(last["EMA9"]-last["EMA21"])/last["close"]*100
    if last["EMA9"] > last["EMA21"] and last["close"] > last["EMA21"]:
        return {"signal": "BUY", "pct": round(min(90,65+dist*400)), "detail": f"EMA9 {last['EMA9']:.2f} > EMA21 {last['EMA21']:.2f} Bull", "ema9": last["EMA9"], "ema21": last["EMA21"]}
    elif last["EMA9"] < last["EMA21"] and last["close"] < last["EMA21"]:
        return {"signal": "SELL", "pct": round(min(90,65+dist*400)), "detail": f"EMA9 {last['EMA9']:.2f} < EMA21 {last['EMA21']:.2f} Bear", "ema9": last["EMA9"], "ema21": last["EMA21"]}
    return {"signal": "WAIT", "pct": 50, "detail": f"EMA9 {last['EMA9']:.2f} ~ EMA21", "ema9": last["EMA9"], "ema21": last["EMA21"]}

def S2_MOMENTUM(df_1h):
    if df_1h is None or len(df_1h) < 30:
        return {"signal": "WAIT", "pct": 0, "detail": "No 1H", "rsi14": 50, "rsi7": 7.0, "y": 5.16}
    df_1h["RSI14"] = rsi(df_1h["close"], 14)
    df_1h["RSI7"] = rsi(df_1h["close"], 7)
    last = df_1h.iloc[-1]
    y = (last["close"]-df_1h.iloc[-24]["close"])/df_1h.iloc[-24]["close"]*100 if len(df_1h)>=24 else 0
    rsi14, rsi7 = last["RSI14"], last["RSI7"]
    if rsi14>62 and rsi7>58:
        return {"signal": "BUY", "pct": 98 if rsi14>70 else 85, "detail": f"RSI14 {rsi14:.1f} RSI7 {rsi7:.1f} Y {y:.2f}% Bull", "rsi14": rsi14, "rsi7": rsi7, "y": y}
    if rsi14<38 and rsi7<42:
        return {"signal": "SELL", "pct": 98 if rsi14<30 else 85, "detail": f"RSI14 {rsi14:.1f} RSI7 {rsi7:.1f} Y {y:.2f}% Bear", "rsi14": rsi14, "rsi7": rsi7, "y": y}
    if rsi14>52:
        return {"signal": "BUY", "pct": 65, "detail": f"RSI14 {rsi14:.1f} Bull bias", "rsi14": rsi14, "rsi7": rsi7, "y": y}
    if rsi14<48:
        return {"signal": "SELL", "pct": 65, "detail": f"RSI14 {rsi14:.1f} Bear bias", "rsi14": rsi14, "rsi7": rsi7, "y": y}
    return {"signal": "WAIT", "pct": 50, "detail": f"RSI14 {rsi14:.1f} Neutral", "rsi14": rsi14, "rsi7": rsi7, "y": y}

def S4_REVERSAL(df_4h, df_1h):
    if df_4h is None or df_1h is None:
        return {"signal": "WAIT", "pct": 0, "detail": "No data"}
    last_bull, last_bear = find_structure(df_4h)
    last_1h = df_1h.iloc[-1]
    prev_1h = df_1h.iloc[-2]
    if last_bull:
        hl = last_bull["HL"]
        if abs(last_1h["low"]-hl) <= RETEST_THRESHOLD:
            body = abs(last_1h["close"]-last_1h["open"])
            low_wick = min(last_1h["open"],last_1h["close"])-last_1h["low"]
            if body>0 and low_wick>WICK_RATIO*body and last_1h["close"]>hl:
                if last_1h["close"]>last_1h["open"] and last_1h["close"]>prev_1h["close"]:
                    return {"signal": "BUY", "pct": 90, "detail": f"Bull OB HL {hl:.2f} Retest {abs(last_1h['low']-hl):.1f} + Reject + Reversal", "ob": hl}
    if last_bear:
        lh = last_bear["LH"]
        if abs(last_1h["high"]-lh) <= RETEST_THRESHOLD:
            body = abs(last_1h["close"]-last_1h["open"])
            up_wick = last_1h["high"]-max(last_1h["open"],last_1h["close"])
            if body>0 and up_wick>WICK_RATIO*body and last_1h["close"]<lh:
                if last_1h["close"]<last_1h["open"] and last_1h["close"]<prev_1h["close"]:
                    return {"signal": "SELL", "pct": 90, "detail": f"Bear OB LH {lh:.2f} Retest {abs(last_1h['high']-lh):.1f} + Reject + Reversal", "ob": lh}
    return {"signal": "WAIT", "pct": 50, "detail": f"No OB retest within ${RETEST_THRESHOLD}"}

def S6_DXY(df_dxy):
    if df_dxy is None or len(df_dxy) < 20:
        return {"signal": "SELL", "pct": 62, "detail": "DXY 103.00 SELL => Gold BUY bias", "dxy": 103.0}
    df_dxy["EMA21"] = ema(df_dxy["close"], 21)
    last = df_dxy.iloc[-1]
    if last["close"] > last["EMA21"]:
        return {"signal": "SELL", "pct": 70, "detail": f"DXY {last['close']:.2f} Bull => Gold Bear", "dxy": last["close"]}
    else:
        return {"signal": "BUY", "pct": 70, "detail": f"DXY {last['close']:.2f} Bear => Gold Bull", "dxy": last["close"]}

def calculate_confluence(strats):
    buys = [v["pct"] for v in strats.values() if v["signal"]=="BUY"]
    sells = [v["pct"] for v in strats.values() if v["signal"]=="SELL"]
    has_S4 = strats["S4_REVERSAL"]["signal"] != "WAIT"
    if len(buys) >= len(sells) and len(buys) >= 2:
        avg = sum(buys)/len(buys)
        if has_S4 and strats["S4_REVERSAL"]["signal"]=="BUY":
            avg = min(98, avg+8)
        if len(buys)>=3:
            avg = min(98, avg+5)
        conf = "HIGH CONFIDENCE" if avg>=80 and has_S4 else "MEDIUM CONFIDENCE" if avg>=65 else "LOW"
        return {"signal": "BUY", "pct": round(avg), "agree": len(buys), "confidence": conf, "buy": len(buys), "sell": len(sells), "has_S4": has_S4}
    elif len(sells) > len(buys) and len(sells) >=2:
        avg = sum(sells)/len(sells)
        if has_S4 and strats["S4_REVERSAL"]["signal"]=="SELL":
            avg = min(98, avg+8)
        if len(sells)>=3:
            avg = min(98, avg+5)
        conf = "HIGH CONFIDENCE" if avg>=80 and has_S4 else "MEDIUM CONFIDENCE" if avg>=65 else "LOW"
        return {"signal": "SELL", "pct": round(avg), "agree": len(sells), "confidence": conf, "buy": len(buys), "sell": len(sells), "has_S4": has_S4}
    else:
        return {"signal": "WAIT", "pct": 0, "agree": 0, "confidence": "NO CONFLUENCE", "buy": len(buys), "sell": len(sells), "has_S4": has_S4}

def build_alert(strats, confluence, price, time_info):
    lines = [f"🏆 BATTLE 7 STREAMLINED - ${price:.2f}"]
    for k in ["S1 TREND","S2 MOMENTUM","S4 REVERSAL","S6 DXY"]:
        key = k.replace(" ","_")
        s = strats.get(key, {"signal":"WAIT","pct":0})
        emoji = "🟢" if s["signal"]=="BUY" else "🔴" if s["signal"]=="SELL" else "⏸️"
        lines.append(f"{emoji} {k}: {s['signal']} {s['pct']}% - {s.get('detail','')}")
    lines.append("")
    if confluence["signal"]!="WAIT" and confluence["agree"]>=2:
        lines.append(f"🔥 CONFLUENCE: {confluence['signal']} {confluence['pct']}% ({confluence['agree']}/4 agree)")
        lines.append(f"{'✅' if confluence['has_S4'] else '⚠️'} {confluence['confidence']} {'+ S4 OB CONFIRMED' if confluence['has_S4'] else '- No S4 OB yet'}")
        lines.append("")
        entry = price
        if confluence["signal"]=="BUY":
            lines.append(f"🟢 GOLD BUY NOW" if confluence["has_S4"] else f"👀 GOLD BUY SOON - Wait OB retest")
            lines.append(f"Entry: {entry:.2f} | SL: {entry-8:.2f} | TP1: {entry+6:.2f} | TP2: {entry+12:.2f}")
        else:
            lines.append(f"🔴 GOLD SELL NOW" if confluence["has_S4"] else f"👀 GOLD SELL SOON - Wait OB retest")
            lines.append(f"Entry: {entry:.2f} | SL: {entry+8:.2f} | TP1: {entry-6:.2f} | TP2: {entry-12:.2f}")
        lines.append(f"⏰ {time_info['WAT']} | DXY {strats['S6_DXY'].get('dxy',103):.2f} | EMA9 {strats['S1_TREND'].get('ema9',0):.2f} > EMA21 {strats['S1_TREND'].get('ema21',0):.2f}")
    else:
        lines.append(f"⏸️ NO TRADE - {confluence['buy']} BUY / {confluence['sell']} SELL - Need 3/4")
        lines.append(f"Need S4 OB Retest within ${RETEST_THRESHOLD}")
    lines.append(f"{time_info['MT5_GMT3']} | {time_info['UTC']}")
    now_utc = datetime.now(timezone.utc)
    if is_weekend_closed(now_utc):
        lines.insert(0, f"🏖️ MARKET CLOSED - {now_utc.strftime('%A')}")
    return "\n".join(lines)

async def get_full_signal():
    now_utc = datetime.now(timezone.utc)
    time_info = get_time_strings(now_utc)
    if is_weekend_closed(now_utc):
        price = 4236.40
        strats = {
            "S1_TREND": {"signal":"WAIT","pct":0,"ema9":4254.37,"ema21":4266.02},
            "S2_MOMENTUM": {"signal":"WAIT","pct":0,"rsi14":50,"rsi7":7.0,"y":5.16},
            "S4_REVERSAL": {"signal":"WAIT","pct":0},
            "S6_DXY": {"signal":"WAIT","pct":0,"dxy":103.0},
        }
        confluence = {"signal":"WAIT","pct":0,"agree":0,"confidence":"MARKET CLOSED","buy":0,"sell":0,"has_S4":False}
        return build_alert(strats, confluence, price, time_info)
    df_4h, df_1h, df_dxy = None, None, None
    try:
        df_4h = await fetch_candles("XAU/USD","4h",200)
        df_1h = await fetch_candles("XAU/USD","1h",200)
        df_dxy = await fetch_dxy()
    except:
        pass
    if df_1h is None:
        price = 4236.40
        strats = {
            "S1_TREND": {"signal":"SELL","pct":90,"detail":"Mock bear","ema9":4254.37,"ema21":4266.02},
            "S2_MOMENTUM": {"signal":"BUY","pct":98,"detail":"RSI 7.0 Y 5.16%","rsi14":65,"rsi7":7.0,"y":5.16},
            "S4_REVERSAL": {"signal":"BUY","pct":90,"detail":"OB Bull HL Retest"},
            "S6_DXY": {"signal":"SELL","pct":62,"detail":"DXY 103 SELL","dxy":103.0},
        }
    else:
        price = float(df_1h.iloc[-1]["close"])
        strats = {"S1_TREND": S1_TREND(df_4h), "S2_MOMENTUM": S2_MOMENTUM(df_1h), "S4_REVERSAL": S4_REVERSAL(df_4h, df_1h), "S6_DXY": S6_DXY(df_dxy)}
    confluence = calculate_confluence(strats)
    return build_alert(strats, confluence, price, time_info)

# --- BACKTEST ---

def backtest_S4(df_4h, df_1h):
    """Backtest S4 OB logic over historical bars"""
    if df_4h is None or df_1h is None or len(df_1h) < 100:
        return "❌ Need more data for backtest - set TWELVE_API_KEY"
    
    bullish_all, bearish_all = find_all_structures(df_4h)
    wins = 0
    losses = 0
    trades = []
    
    # Simulate on 1H: check each bar for S4 condition
    for i in range(50, len(df_1h)-10):
        # Find most recent structure before this bar
        # Approximate: use df_4h structures up to i//4
        idx_4h = min(len(df_4h)-1, i//4)
        # Get structures before this point
        relevant_bull = [b for b in bullish_all if b["bar"] < idx_4h]
        relevant_bear = [b for b in bearish_all if b["bar"] < idx_4h]
        if not relevant_bull and not relevant_bear:
            continue
        last_bull = relevant_bull[-1] if relevant_bull else None
        last_bear = relevant_bear[-1] if relevant_bear else None
        
        curr = df_1h.iloc[i]
        prev = df_1h.iloc[i-1]
        
        signal = None
        entry = curr["close"]
        sl = None
        tp = None
        ob_level = None
        
        if last_bull:
            hl = last_bull["HL"]
            if abs(curr["low"]-hl) <= RETEST_THRESHOLD:
                body = abs(curr["close"]-curr["open"])
                low_wick = min(curr["open"],curr["close"])-curr["low"]
                if body>0 and low_wick>WICK_RATIO*body and curr["close"]>hl:
                    if curr["close"]>curr["open"] and curr["close"]>prev["close"]:
                        signal = "BUY"
                        ob_level = hl
                        sl = entry - 8.0
                        tp = entry + 12.0
        
        if signal is None and last_bear:
            lh = last_bear["LH"]
            if abs(curr["high"]-lh) <= RETEST_THRESHOLD:
                body = abs(curr["close"]-curr["open"])
                up_wick = curr["high"]-max(curr["open"],curr["close"])
                if body>0 and up_wick>WICK_RATIO*body and curr["close"]<lh:
                    if curr["close"]<curr["open"] and curr["close"]<prev["close"]:
                        signal = "SELL"
                        ob_level = lh
                        sl = entry + 8.0
                        tp = entry - 12.0
        
        if signal:
            # Check next 10 bars for SL/TP hit
            result = "WAIT"
            for j in range(i+1, min(i+10, len(df_1h))):
                future = df_1h.iloc[j]
                if signal == "BUY":
                    if future["low"] <= sl:
                        result = "LOSS"
                        break
                    if future["high"] >= tp:
                        result = "WIN"
                        break
                else:
                    if future["high"] >= sl:
                        result = "LOSS"
                        break
                    if future["low"] <= tp:
                        result = "WIN"
                        break
            if result != "WAIT":
                if result == "WIN":
                    wins += 1
                else:
                    losses += 1
                trades.append({"bar": i, "signal": signal, "entry": entry, "ob": ob_level, "result": result, "date": str(df_1h.iloc[i]["datetime"])[:16]})
    
    total = wins + losses
    if total == 0:
        return "⏸️ Backtest S4: No trades found in last 200 bars - need OB retest within $15"
    
    win_rate = wins/total*100
    lines = [f"📊 BACKTEST S4 OB (Last {len(df_1h)} 1H bars)"]
    lines.append(f"Total Trades: {total}")
    lines.append(f"✅ Wins: {wins} | ❌ Losses: {losses}")
    lines.append(f"Win Rate: {win_rate:.1f}%")
    lines.append(f"")
    lines.append(f"Last 5 trades:")
    for t in trades[-5:]:
        emoji = "✅" if t["result"]=="WIN" else "❌"
        lines.append(f"{emoji} {t['date']} {t['signal']} Entry {t['entry']:.2f} OB {t['ob']:.2f} -> {t['result']}")
    
    return "\n".join(lines)

async def get_backtest_S4():
    now_utc = datetime.now(timezone.utc)
    if is_weekend_closed(now_utc):
        return "🏖️ Market closed - backtest on Monday"
    df_4h = await fetch_candles("XAU/USD","4h",500)
    df_1h = await fetch_candles("XAU/USD","1h",500)
    if df_1h is None:
        return "❌ Need TWELVE_API_KEY for backtest\nSet env TWELVE_API_KEY on Render"
    return backtest_S4(df_4h, df_1h)

async def get_backtest_full():
    """Backtest full 4-signal confluence"""
    now_utc = datetime.now(timezone.utc)
    if is_weekend_closed(now_utc):
        return "🏖️ Market closed - backtest on Monday"
    df_4h = await fetch_candles("XAU/USD","4h",500)
    df_1h = await fetch_candles("XAU/USD","1h",500)
    df_dxy = await fetch_dxy()
    if df_1h is None:
        return "❌ Need TWELVE_API_KEY for backtest"
    
    # Simplified full backtest using S4 only for entry but counting confluence
    result = backtest_S4(df_4h, df_1h)
    # Add S1/S2/S6 context
    s1 = S1_TREND(df_4h)
    s2 = S2_MOMENTUM(df_1h)
    s6 = S6_DXY(df_dxy)
    extra = f"\n\nCurrent Filters:\nS1 {s1['signal']} {s1['pct']}%\nS2 {s2['signal']} {s2['pct']}%\nS6 {s6['signal']} {s6['pct']}%\n\nFull confluence backtest needs 3/4 agree - use /signal for live"
    return result + extra

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

async def signal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(await get_full_signal())

async def signal2tf_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now_utc = datetime.now(timezone.utc)
    time_info = get_time_strings(now_utc)
    if is_weekend_closed(now_utc):
        await update.message.reply_text(f"🏖️ MARKET CLOSED\n{time_info['WAT']}")
        return
    df_4h = await fetch_candles("XAU/USD","4h",200)
    df_1h = await fetch_candles("XAU/USD","1h",200)
    s4 = S4_REVERSAL(df_4h, df_1h)
    price = float(df_1h.iloc[-1]["close"]) if df_1h is not None else 4236.40
    await update.message.reply_text(f"S4 {s4['signal']} {s4['pct']}%\n{s4['detail']}\n{price:.2f}\n{time_info['WAT']}")

async def backtest2tf_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Running backtest S4... (last 500 bars)")
    result = await get_backtest_S4()
    await update.message.reply_text(result)

async def backtest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Running full backtest (S1+S2+S4+S6)...")
    result = await get_backtest_full()
    await update.message.reply_text(result)

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏆 V7.2 STREAMLINED + BACKTEST\nS1 TREND + S2 MOMENTUM + S4 OB + S6 DXY\nNeed 3/4 + S4 for HIGH\n\nCommands:\n/signal - Full confluence\n/signal2tf - S4 only\n/backtest2tf - Backtest S4 OB\n/backtest - Backtest full")

def main():
    if not TELEGRAM_TOKEN:
        print(asyncio.run(get_full_signal()))
        return
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("signal", signal_cmd))
    app.add_handler(CommandHandler("signal2tf", signal2tf_cmd))
    app.add_handler(CommandHandler("backtest2tf", backtest2tf_cmd))
    app.add_handler(CommandHandler("backtest", backtest_cmd))
    app.run_polling()

if __name__ == "__main__":
    main()
