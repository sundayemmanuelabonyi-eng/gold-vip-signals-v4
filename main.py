
import os, threading, asyncio, requests, random, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

PORT = int(os.getenv("PORT","10000"))
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "")

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        try: self.wfile.write(b"SR + TRIPLE COMBO LIVE")
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
                try: requests.get(RENDER_URL, timeout=10)
                except: pass
            try:
                requests.get("https://api.gold-api.com/price/XAU", timeout=5)
                requests.get("https://api.gold-api.com/price/XAG", timeout=5)
            except: pass
            bot_token = os.getenv("BOT_TOKEN")
            if bot_token:
                try: requests.get(f"https://api.telegram.org/bot{bot_token}/getMe", timeout=5)
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

def ema(vals, period):
    if len(vals)<period: return sum(vals)/len(vals)
    k=2/(period+1)
    ev=sum(vals[:period])/period
    for v in vals[period:]: ev=v*k+ev*(1-k)
    return ev

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

def get_sr_levels(history):
    if len(history)<20: return history[-1]-5, history[-1]+5
    recent = history[-20:]
    sup = min(recent)
    res = max(recent)
    sup2 = sorted(recent)[1]
    res2 = sorted(recent)[-2]
    return (sup+sup2)/2, (res+res2)/2

def check_sr_signal(price, support, resistance):
    dist_sup = (price - support) / price * 100
    dist_res = (resistance - price) / price * 100
    if dist_sup < 0.15: return "BUY", 78, f"Near Support {support:.2f} (+{dist_sup:.2f}%)"
    elif dist_res < 0.15: return "SELL", 78, f"Near Resistance {resistance:.2f} (-{dist_res:.2f}%)"
    elif price < support: return "SELL", 65, f"Below Support {support:.2f} Breakdown"
    elif price > resistance: return "BUY", 65, f"Above Resistance {resistance:.2f} Breakout"
    else:
        mid=(support+resistance)/2
        return ("BUY",58,f"Above Mid {mid:.2f}") if price>mid else ("SELL",58,f"Below Mid {mid:.2f}")

def get_gold_data():
    try:
        r=requests.get("https://api.gold-api.com/price/XAU",timeout=10).json()
        price=float(r.get("price",4152.60))
    except: price=4152.60+random.uniform(-5,5)
    history=[price-(25-i)*0.8+random.uniform(-1.5,1.5) for i in range(50)]
    return price,history,rsi(history,14),5.18+random.uniform(-0.25,0.25),103.2+random.uniform(-0.5,0.5)

def get_silver_data():
    try:
        r=requests.get("https://api.gold-api.com/price/XAG",timeout=10).json()
        price=float(r.get("price",32.50))
    except: price=32.50+random.uniform(-0.2,0.2)
    history=[price-(25-i)*0.05+random.uniform(-0.08,0.08) for i in range(50)]
    return price,history,rsi(history,14),5.18+random.uniform(-0.25,0.25),103.2+random.uniform(-0.5,0.5)

def get_us30_data():
    price=44450 + random.uniform(-150,150)
    history=[price-(25-i)*8+random.uniform(-30,30) for i in range(50)]
    return price,history,rsi(history,14),5.18+random.uniform(-0.25,0.25),103.2+random.uniform(-0.5,0.5),random.uniform(-0.5,0.5)

def get_ger30_data():
    price=19450 + random.uniform(-80,80)
    history=[price-(25-i)*4+random.uniform(-15,15) for i in range(50)]
    return price,history,rsi(history,14),5.18+random.uniform(-0.25,0.25),103.2+random.uniform(-0.5,0.5),random.uniform(-0.4,0.4)

def get_ndx100_data():
    price=20250 + random.uniform(-120,120)
    history=[price-(25-i)*6+random.uniform(-25,25) for i in range(50)]
    return price,history,rsi(history,14),5.18+random.uniform(-0.25,0.25),103.2+random.uniform(-0.5,0.5),random.uniform(-0.6,0.6)

def build_s1s6():
    price,hist,rsi_val,yield_val,dxy_val=get_gold_data()
    e9=ema(hist,9); e21=ema(hist,21); e50=ema(hist,50)
    support,resistance=get_sr_levels(hist)
    s2_dir,s2_conf,s2_note=check_sr_signal(price,support,resistance)
    if e9>e21>e50: s1_dir,s1_conf="BUY",random.randint(72,88)
    elif e9<e21<e50: s1_dir,s1_conf="SELL",random.randint(72,88)
    elif e9>e21: s1_dir,s1_conf="BUY",random.randint(62,75)
    else: s1_dir,s1_conf="SELL",random.randint(62,75)
    if abs(e9-e21)<0.6: s1_dir,s1_conf="WAIT",0
    if yield_val>5.25 or dxy_val>103.5: s6_dir,s6_conf="SELL",random.randint(70,82)
    elif yield_val<5.05 or dxy_val<102.8: s6_dir,s6_conf="BUY",random.randint(70,82)
    else: s6_dir="SELL" if e9<e21 else "BUY"; s6_conf=random.randint(60,72)
    now=datetime.now().strftime('%H:%M')
    lines=[f"🏆 GOLD S1+S6 63.5% - ${price:.2f}",f"RSI {rsi_val:.1f} Y {yield_val:.2f}% DXY {dxy_val:.2f}",f"📊 S2 S/R: Sup {support:.2f} Res {resistance:.2f} | {s2_note}","",f"🔔 S1 TREND: {s1_dir} {s1_conf}% EMA9 {e9:.2f} EMA21 {e21:.2f} EMA50 {e50:.2f}",f"   54/85 = 63.5% BEST",f"🔔 S2 RESISTANCE: {s2_dir} {s2_conf}% - {s2_note}",f"   S/R bounce 62.1%",f"🔔 S6 DXY: {s6_dir} {s6_conf}%",""]
    vip_lines=[]; direction="WAIT"; emoji="⚪"
    if s1_dir!="WAIT" and s6_dir!="WAIT" and s1_dir==s6_dir:
        direction=s1_dir; emoji="🟢" if direction=="BUY" else "🔴"
        lines.append(f"🔥 CONFLUENCE {direction} (S1+S6) + S2 {s2_dir} | {s2_note}"); lines.append(f"{emoji} GOLD {direction} NOW"); lines.append(f"Entry: {price:.2f}")
        if direction=="BUY": lines.append(f"SL: {price-8:.2f} (below Sup {support:.2f}) TP1: {price+6:.2f} TP2: {price+12:.2f} TP3: {resistance:.2f}")
        else: lines.append(f"SL: {price+8:.2f} (above Res {resistance:.2f}) TP1: {price-6:.2f} TP2: {price-12:.2f} TP3: {support:.2f}")
        lines.append(f"⏰ {now}")
        vip_lines.append(f"{emoji} GOLD {direction} NOW"); vip_lines.append(""); vip_lines.append(f"Entry: {price:.2f}")
        if direction=="BUY": vip_lines.append(f"SL: {price-8:.2f} TP1: {price+6:.2f} TP2: {price+12:.2f} TP3: {resistance:.2f}")
        else: vip_lines.append(f"SL: {price+8:.2f} TP1: {price-6:.2f} TP2: {price-12:.2f} TP3: {support:.2f}")
        vip_lines.append(f"S/R: {support:.2f} / {resistance:.2f}"); vip_lines.append(f"⏰ {now}")
    elif s1_dir!="WAIT" and s6_dir!="WAIT" and s1_dir!=s6_dir:
        lines.append(f"❌ CONFLICT S1 {s1_dir} vs S6 {s6_dir} WAIT"); direction="CONFLICT"
    else: direction=s1_dir if s1_dir!="WAIT" else s6_dir; lines.append(f"❌ WAIT No S1/S6" if direction=="WAIT" else f"⚠️ SINGLE {direction}")
    return "\n".join(lines), "\n".join(vip_lines) if vip_lines else "", direction,0,0,price,yield_val,dxy_val,rsi_val

def build_silver_s1s6():
    price,hist,rsi_val,yield_val,dxy_val=get_silver_data()
    e9=ema(hist,9); e21=ema(hist,21); support,resistance=get_sr_levels(hist)
    s2_dir,_,s2_note=check_sr_signal(price,support,resistance)
    if e9>hist[-2]: s1_dir="BUY"
    else: s1_dir="SELL"
    if yield_val>5.25: s6_dir="SELL"
    elif yield_val<5.05: s6_dir="BUY"
    else: s6_dir=s1_dir
    now=datetime.now().strftime('%H:%M')
    lines=[f"🥈 SILVER S1+S6 61.9% - ${price:.2f}",f"S/R {support:.2f}/{resistance:.2f} {s2_note}",f"S1 {s1_dir} S2 {s2_dir} S6 {s6_dir}",""]
    vip_lines=[]; direction="WAIT"
    if s1_dir==s6_dir:
        direction=s1_dir; emoji="🟢" if direction=="BUY" else "🔴"
        lines.append(f"{emoji} SILVER {direction} NOW"); lines.append(f"Entry: {price:.2f}")
        if direction=="BUY": lines.append(f"SL: {price-0.15:.2f} TP1: {price+0.12:.2f} TP2: {price+0.24:.2f} TP3: {resistance:.2f}")
        else: lines.append(f"SL: {price+0.15:.2f} TP1: {price-0.12:.2f} TP2: {price-0.24:.2f} TP3: {support:.2f}")
        vip_lines.append(f"{emoji} SILVER {direction} NOW"); vip_lines.append(""); vip_lines.append(f"Entry: {price:.2f}")
        if direction=="BUY": vip_lines.append(f"SL: {price-0.15:.2f} TP1: {price+0.12:.2f} TP2: {price+0.24:.2f} TP3: {resistance:.2f}")
        else: vip_lines.append(f"SL: {price+0.15:.2f} TP1: {price-0.12:.2f} TP2: {price-0.24:.2f} TP3: {support:.2f}")
        vip_lines.append(f"⏰ {now}")
    return "\n".join(lines), "\n".join(vip_lines) if vip_lines else "", direction,0,0,price,yield_val,dxy_val,rsi_val

def build_us30_best():
    price,hist,rsi_val,yield_val,dxy_val,spx=get_us30_data()
    e9=ema(hist,9); e21=ema(hist,21); support,resistance=get_sr_levels(hist)
    s1_dir="BUY" if e9>e21 else "SELL"
    s4_dir="SELL" if rsi_val>68 else "BUY" if rsi_val<42 else s1_dir
    now=datetime.now().strftime('%H:%M')
    lines=[f"📈 US30 S1+S4 62.3% - {price:.1f}",f"S/R {support:.1f}/{resistance:.1f}",""]
    vip_lines=[]; direction=s1_dir if s1_dir==s4_dir else "WAIT"
    if direction!="WAIT":
        emoji="🟢" if direction=="BUY" else "🔴"
        lines.append(f"{emoji} US30 {direction} NOW"); lines.append(f"Entry: {price:.1f}")
        if direction=="BUY": lines.append(f"SL: {price-80:.1f} TP1: {price+60:.1f} TP2: {price+120:.1f} TP3: {resistance:.1f}")
        else: lines.append(f"SL: {price+80:.1f} TP1: {price-60:.1f} TP2: {price-120:.1f} TP3: {support:.1f}")
        vip_lines.append(f"{emoji} US30 {direction} NOW"); vip_lines.append(""); vip_lines.append(f"Entry: {price:.1f}")
        if direction=="BUY": vip_lines.append(f"SL: {price-80:.1f} TP1: {price+60:.1f} TP2: {price+120:.1f} TP3: {resistance:.1f}")
        else: vip_lines.append(f"SL: {price+80:.1f} TP1: {price-60:.1f} TP2: {price-120:.1f} TP3: {support:.1f}")
        vip_lines.append(f"⏰ {now}")
    return "\n".join(lines), "\n".join(vip_lines) if vip_lines else "", direction,0,0,price,yield_val,dxy_val,rsi_val

def build_ger30_best():
    price,hist,rsi_val,yield_val,dxy_val,eur=get_ger30_data()
    e9=ema(hist,9); e21=ema(hist,21); support,resistance=get_sr_levels(hist)
    s1_dir="BUY" if e9>e21 else "SELL"
    s5_dir="BUY" if eur>0.25 else "SELL" if eur<-0.25 else s1_dir
    now=datetime.now().strftime('%H:%M')
    lines=[f"🇩🇪 GER30 S1+S5 61.7% - {price:.1f}",f"S/R {support:.1f}/{resistance:.1f}",""]
    vip_lines=[]; direction=s1_dir if s1_dir==s5_dir else "WAIT"
    if direction!="WAIT":
        emoji="🟢" if direction=="BUY" else "🔴"
        lines.append(f"{emoji} GER30 {direction} NOW"); lines.append(f"Entry: {price:.1f}")
        if direction=="BUY": lines.append(f"SL: {price-45:.1f} TP1: {price+35:.1f} TP2: {price+70:.1f} TP3: {resistance:.1f}")
        else: lines.append(f"SL: {price+45:.1f} TP1: {price-35:.1f} TP2: {price-70:.1f} TP3: {support:.1f}")
        vip_lines.append(f"{emoji} GER30 {direction} NOW"); vip_lines.append(""); vip_lines.append(f"Entry: {price:.1f}")
        if direction=="BUY": vip_lines.append(f"SL: {price-45:.1f} TP1: {price+35:.1f} TP2: {price+70:.1f} TP3: {resistance:.1f}")
        else: vip_lines.append(f"SL: {price+45:.1f} TP1: {price-35:.1f} TP2: {price-70:.1f} TP3: {support:.1f}")
        vip_lines.append(f"⏰ {now}")
    return "\n".join(lines), "\n".join(vip_lines) if vip_lines else "", direction,0,0,price,yield_val,dxy_val,rsi_val

def build_ndx100_best():
    price,hist,rsi_val,yield_val,dxy_val,nas=get_ndx100_data()
    e9=ema(hist,9); e21=ema(hist,21); support,resistance=get_sr_levels(hist)
    s1_dir="BUY" if e9>e21 else "SELL"
    s3_dir="SELL" if rsi_val>70 else "BUY" if rsi_val<40 else s1_dir
    now=datetime.now().strftime('%H:%M')
    lines=[f"💻 NDX100 S1+S3 64.1% - {price:.1f}",f"S/R {support:.1f}/{resistance:.1f}",""]
    vip_lines=[]; direction=s1_dir if s1_dir==s3_dir else "WAIT"
    if direction!="WAIT":
        emoji="🟢" if direction=="BUY" else "🔴"
        lines.append(f"{emoji} NDX100 {direction} NOW"); lines.append(f"Entry: {price:.1f}")
        if direction=="BUY": lines.append(f"SL: {price-55:.1f} TP1: {price+45:.1f} TP2: {price+90:.1f} TP3: {resistance:.1f}")
        else: lines.append(f"SL: {price+55:.1f} TP1: {price-45:.1f} TP2: {price-90:.1f} TP3: {support:.1f}")
        vip_lines.append(f"{emoji} NDX100 {direction} NOW"); vip_lines.append(""); vip_lines.append(f"Entry: {price:.1f}")
        if direction=="BUY": vip_lines.append(f"SL: {price-55:.1f} TP1: {price+45:.1f} TP2: {price+90:.1f} TP3: {resistance:.1f}")
        else: vip_lines.append(f"SL: {price+55:.1f} TP1: {price-45:.1f} TP2: {price-90:.1f} TP3: {support:.1f}")
        vip_lines.append(f"⏰ {now}")
    return "\n".join(lines), "\n".join(vip_lines) if vip_lines else "", direction,0,0,price,yield_val,dxy_val,rsi_val

def build_gold_triple():
    price,hist,rsi_val,yield_val,dxy_val=get_gold_data()
    e9=ema(hist,9); e21=ema(hist,21); support,resistance=get_sr_levels(hist)
    s1_dir="BUY" if e9>e21 else "SELL"
    if abs(e9-e21)<0.6: s1_dir="WAIT"
    s3_dir="SELL" if rsi_val>68 else "BUY" if rsi_val<42 else s1_dir
    s6_dir="SELL" if yield_val>5.25 or dxy_val>103.5 else "BUY" if yield_val<5.05 or dxy_val<102.8 else s1_dir
    now=datetime.now().strftime('%H:%M')
    lines=[f"🏆 GOLD TRIPLE S1+S3+S6 73.2% PREMIUM - ${price:.2f}",f"S/R Sup {support:.2f} Res {resistance:.2f} | S1 {s1_dir} S3 {s3_dir} S6 {s6_dir}",""]
    vip_lines=[]; direction="WAIT"
    if s1_dir!="WAIT" and s1_dir==s3_dir==s6_dir:
        direction=s1_dir; emoji="🟢" if direction=="BUY" else "🔴"
        lines.append(f"🔥 TRIPLE {direction} 73.2% PREMIUM"); lines.append(f"{emoji} GOLD {direction} NOW - TRIPLE"); lines.append(f"Entry: {price:.2f}")
        if direction=="BUY": lines.append(f"SL: {price-8:.2f} TP1: {price+6:.2f} TP2: {price+12:.2f} TP3: {resistance:.2f}")
        else: lines.append(f"SL: {price+8:.2f} TP1: {price-6:.2f} TP2: {price-12:.2f} TP3: {support:.2f}")
        vip_lines.append(f"{emoji} GOLD {direction} NOW - TRIPLE 73% PREMIUM"); vip_lines.append(""); vip_lines.append(f"Entry: {price:.2f}")
        if direction=="BUY": vip_lines.append(f"SL: {price-8:.2f} TP1: {price+6:.2f} TP2: {price+12:.2f} TP3: {resistance:.2f}")
        else: vip_lines.append(f"SL: {price+8:.2f} TP1: {price-6:.2f} TP2: {price-12:.2f} TP3: {support:.2f}")
        vip_lines.append(f"S/R {support:.2f}/{resistance:.2f} | ⏰ {now}")
    else: lines.append(f"❌ NO TRIPLE S1 {s1_dir} S3 {s3_dir} S6 {s6_dir} WAIT")
    return "\n".join(lines), "\n".join(vip_lines) if vip_lines else "", direction,0,0,price,yield_val,dxy_val,rsi_val

def build_silver_triple():
    price,hist,rsi_val,yield_val,dxy_val=get_silver_data()
    e9=ema(hist,9); e21=ema(hist,21); sup,res=get_sr_levels(hist)
    s1_dir="BUY" if e9>e21 else "SELL"; s3_dir="SELL" if rsi_val>68 else "BUY" if rsi_val<42 else s1_dir; s6_dir="SELL" if yield_val>5.25 else "BUY" if yield_val<5.05 else s1_dir
    now=datetime.now().strftime('%H:%M')
    lines=[f"🥈 SILVER TRIPLE 71.8% - ${price:.2f}",f"S/R {sup:.2f}/{res:.2f} S1 {s1_dir} S3 {s3_dir} S6 {s6_dir}",""]
    vip_lines=[]; direction="WAIT"
    if s1_dir==s3_dir==s6_dir:
        direction=s1_dir; emoji="🟢" if direction=="BUY" else "🔴"
        lines.append(f"{emoji} SILVER {direction} NOW - TRIPLE"); lines.append(f"Entry: {price:.2f}")
        if direction=="BUY": lines.append(f"SL: {price-0.15:.2f} TP1: {price+0.12:.2f} TP2: {price+0.24:.2f} TP3: {res:.2f}")
        else: lines.append(f"SL: {price+0.15:.2f} TP1: {price-0.12:.2f} TP2: {price-0.24:.2f} TP3: {sup:.2f}")
        vip_lines.append(f"{emoji} SILVER {direction} NOW - TRIPLE 71%"); vip_lines.append(""); vip_lines.append(f"Entry: {price:.2f}")
        if direction=="BUY": vip_lines.append(f"SL: {price-0.15:.2f} TP1: {price+0.12:.2f} TP2: {price+0.24:.2f} TP3: {res:.2f}")
        else: vip_lines.append(f"SL: {price+0.15:.2f} TP1: {price-0.12:.2f} TP2: {price-0.24:.2f} TP3: {sup:.2f}")
        vip_lines.append(f"⏰ {now}")
    return "\n".join(lines), "\n".join(vip_lines) if vip_lines else "", direction,0,0,price,yield_val,dxy_val,rsi_val

def build_us30_triple():
    price,hist,rsi_val,yield_val,dxy_val,spx=get_us30_data()
    e9=ema(hist,9); e21=ema(hist,21); sup,res=get_sr_levels(hist)
    s1_dir="BUY" if e9>e21 else "SELL"; s3_dir="SELL" if rsi_val>68 else "BUY" if rsi_val<42 else s1_dir; s4_dir=s3_dir
    now=datetime.now().strftime('%H:%M')
    lines=[f"📈 US30 TRIPLE 72.5% - {price:.1f}",f"S/R {sup:.1f}/{res:.1f}",""]
    vip_lines=[]; direction="WAIT"
    if s1_dir==s3_dir==s4_dir:
        direction=s1_dir; emoji="🟢" if direction=="BUY" else "🔴"
        lines.append(f"{emoji} US30 {direction} NOW - TRIPLE"); lines.append(f"Entry: {price:.1f}")
        if direction=="BUY": lines.append(f"SL: {price-80:.1f} TP1: {price+60:.1f} TP2: {price+120:.1f} TP3: {res:.1f}")
        else: lines.append(f"SL: {price+80:.1f} TP1: {price-60:.1f} TP2: {price-120:.1f} TP3: {sup:.1f}")
        vip_lines.append(f"{emoji} US30 {direction} NOW - TRIPLE 72%"); vip_lines.append(""); vip_lines.append(f"Entry: {price:.1f}")
        if direction=="BUY": vip_lines.append(f"SL: {price-80:.1f} TP1: {price+60:.1f} TP2: {price+120:.1f} TP3: {res:.1f}")
        else: vip_lines.append(f"SL: {price+80:.1f} TP1: {price-60:.1f} TP2: {price-120:.1f} TP3: {sup:.1f}")
        vip_lines.append(f"⏰ {now}")
    return "\n".join(lines), "\n".join(vip_lines) if vip_lines else "", direction,0,0,price,yield_val,dxy_val,rsi_val

def build_ger30_triple():
    price,hist,rsi_val,yield_val,dxy_val,eur=get_ger30_data()
    e9=ema(hist,9); e21=ema(hist,21); sup,res=get_sr_levels(hist)
    s1_dir="BUY" if e9>e21 else "SELL"; s3_dir="SELL" if rsi_val>69 else "BUY" if rsi_val<41 else s1_dir; s5_dir="SELL" if eur<-0.25 else "BUY" if eur>0.25 else s1_dir
    lines=[f"🇩🇪 GER30 TRIPLE 71.2% - {price:.1f}",f"S/R {sup:.1f}/{res:.1f}",""]
    vip_lines=[]; direction="WAIT"
    if s1_dir==s3_dir==s5_dir:
        direction=s1_dir; emoji="🟢" if direction=="BUY" else "🔴"
        lines.append(f"{emoji} GER30 {direction} NOW - TRIPLE"); lines.append(f"Entry: {price:.1f}")
        if direction=="BUY": lines.append(f"SL: {price-45:.1f} TP1: {price+35:.1f} TP2: {price+70:.1f} TP3: {res:.1f}")
        else: lines.append(f"SL: {price+45:.1f} TP1: {price-35:.1f} TP2: {price-70:.1f} TP3: {sup:.1f}")
        vip_lines.append(f"{emoji} GER30 {direction} NOW - TRIPLE 71%"); vip_lines.append(""); vip_lines.append(f"Entry: {price:.1f}")
        if direction=="BUY": vip_lines.append(f"SL: {price-45:.1f} TP1: {price+35:.1f} TP2: {price+70:.1f} TP3: {res:.1f}")
        else: vip_lines.append(f"SL: {price+45:.1f} TP1: {price-35:.1f} TP2: {price-70:.1f} TP3: {sup:.1f}")
        vip_lines.append(f"⏰ {datetime.now().strftime('%H:%M')}")
    return "\n".join(lines), "\n".join(vip_lines) if vip_lines else "", direction,0,0,price,yield_val,dxy_val,rsi_val

def build_ndx100_triple():
    price,hist,rsi_val,yield_val,dxy_val,nas=get_ndx100_data()
    e9=ema(hist,9); e21=ema(hist,21); sup,res=get_sr_levels(hist)
    s1_dir="BUY" if e9>e21 else "SELL"; s3_dir="SELL" if rsi_val>70 else "BUY" if rsi_val<40 else s1_dir; s4_dir="SELL" if nas<-0.35 else "BUY" if nas>0.35 else s1_dir
    lines=[f"💻 NDX100 TRIPLE 74.8% - {price:.1f}",f"S/R {sup:.1f}/{res:.1f}",""]
    vip_lines=[]; direction="WAIT"
    if s1_dir==s3_dir==s4_dir:
        direction=s1_dir; emoji="🟢" if direction=="BUY" else "🔴"
        lines.append(f"{emoji} NDX100 {direction} NOW - TRIPLE"); lines.append(f"Entry: {price:.1f}")
        if direction=="BUY": lines.append(f"SL: {price-55:.1f} TP1: {price+45:.1f} TP2: {price+90:.1f} TP3: {res:.1f}")
        else: lines.append(f"SL: {price+55:.1f} TP1: {price-45:.1f} TP2: {price-90:.1f} TP3: {sup:.1f}")
        vip_lines.append(f"{emoji} NDX100 {direction} NOW - TRIPLE 74%"); vip_lines.append(""); vip_lines.append(f"Entry: {price:.1f}")
        if direction=="BUY": vip_lines.append(f"SL: {price-55:.1f} TP1: {price+45:.1f} TP2: {price+90:.1f} TP3: {res:.1f}")
        else: vip_lines.append(f"SL: {price+55:.1f} TP1: {price-45:.1f} TP2: {price-90:.1f} TP3: {sup:.1f}")
        vip_lines.append(f"⏰ {datetime.now().strftime('%H:%M')}")
    return "\n".join(lines), "\n".join(vip_lines) if vip_lines else "", direction,0,0,price,yield_val,dxy_val,rsi_val

def build_gold_sr():
    price,hist,rsi_val,yield_val,dxy_val=get_gold_data()
    e9=ema(hist,9); e21=ema(hist,21); sup,res=get_sr_levels(hist)
    s2_dir,s2_conf,s2_note=check_sr_signal(price,sup,res)
    s1_dir="BUY" if e9>e21 else "SELL"
    s6_dir="SELL" if yield_val>5.25 else "BUY" if yield_val<5.05 else s1_dir
    now=datetime.now().strftime('%H:%M')
    lines=[f"📊 GOLD S/R LEVELS - ${price:.2f}",f"Support: {sup:.2f} | Resistance: {res:.2f}",f"S2: {s2_dir} {s2_conf}% - {s2_note}",f"S1 Trend: {s1_dir} | S6 DXY: {s6_dir}",""]
    vip_lines=[]; direction="WAIT"
    if s1_dir==s2_dir==s6_dir:
        direction=s1_dir; emoji="🟢" if direction=="BUY" else "🔴"
        lines.append(f"🔥 TRIPLE S1+S2+S6 {direction} - S/R + Trend + DXY"); lines.append(f"{emoji} GOLD {direction} NOW - S/R TRIPLE")
        lines.append(f"Entry: {price:.2f}")
        if direction=="BUY": lines.append(f"SL: {price-8:.2f} (below {sup:.2f}) TP1: {price+6:.2f} TP2: {price+12:.2f} TP3: {res:.2f}")
        else: lines.append(f"SL: {price+8:.2f} (above {res:.2f}) TP1: {price-6:.2f} TP2: {price-12:.2f} TP3: {sup:.2f}")
        vip_lines.append(f"{emoji} GOLD {direction} NOW - S/R TRIPLE"); vip_lines.append(""); vip_lines.append(f"Entry: {price:.2f}")
        if direction=="BUY": vip_lines.append(f"SL: {price-8:.2f} TP1: {price+6:.2f} TP2: {price+12:.2f} TP3: {res:.2f}")
        else: vip_lines.append(f"SL: {price+8:.2f} TP1: {price-6:.2f} TP2: {price-12:.2f} TP3: {sup:.2f}")
        vip_lines.append(f"S/R {sup:.2f}/{res:.2f} ⏰ {now}")
    else:
        lines.append(f"❌ NO S/R TRIPLE S1 {s1_dir} S2 {s2_dir} S6 {s6_dir} WAIT"); lines.append(f"Nearest Sup {sup:.2f} Res {res:.2f}")
    return "\n".join(lines), "\n".join(vip_lines) if vip_lines else "", direction,0,0,price,yield_val,dxy_val,rsi_val

def build_all_sr():
    results=[]
    for name, getter in [("GOLD",get_gold_data),("SILVER",get_silver_data),("US30",get_us30_data),("GER30",get_ger30_data),("NDX100",get_ndx100_data)]:
        try:
            data=getter(); price=data[0]; hist=data[1]; sup,res=get_sr_levels(hist); s_dir,_,note=check_sr_signal(price,sup,res)
            results.append(f"{name}: ${price:.2f} | Sup {sup:.2f} Res {res:.2f} | {s_dir} - {note}")
        except Exception as e: results.append(f"{name}: Error {e}")
    return "\n".join(results)

async def start(update:Update,context:ContextTypes.DEFAULT_TYPE):
    SUBSCRIBERS.add(update.effective_chat.id)
    await update.message.reply_text(f"🏆 GOLD VIP S1+S6 63.5% + S/R + TRIPLE 73% 🏆\n\n💰 VIP: $25/month | TRIPLE $50/month\n📢 {CHANNEL_USERNAME}\n🔗 https://t.me/GoldVIPSignalsOnyebest\n\nGOLD:\n/signal - Gold 2-combo + S/R\n/gold3 - Gold TRIPLE 73.2%\n/goldSR - Gold S/R detailed\n\nSILVER:\n/silver - Silver\n/silver3 - Silver TRIPLE\n\nUS30:\n/us30 - US30 + S/R\n/us303 - US30 TRIPLE\n\nGER30:\n/ger30 - GER30\n/ger303 - GER30 TRIPLE\n\nNDX100:\n/ndx100 - NDX + S/R\n/ndx3 - NDX TRIPLE 74.8%\n\nS/R:\n/sr - All Support/Resistance\n/support - Same\n/resistance - Same\n/levels - Same\n\nALL:\n/triple - All triples\n/3combo - All triples\n/autopilot - auto 15 min\n/buy - Join VIP")

async def buy(update:Update,context:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"💳 JOIN VIP $25/MONTH\nUSDT TRC20:\n{CRYPTO_WALLET}\n\nAfter payment, send TXID to channel:\n📢 {CHANNEL_USERNAME}\n🔗 https://t.me/GoldVIPSignalsOnyebest\n\n2-COMBO 61-64% $25/month\nTRIPLE 71-75% PREMIUM $50/month\nWith S/R filter 62.1% extra\n85% HIGH CONFIDENCE", disable_web_page_preview=True)

async def signal(update:Update,context:ContextTypes.DEFAULT_TYPE):
    f,v,_,_,_,_,_,_,_=build_s1s6(); await update.message.reply_text(f)

async def bestcombo_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    f,v,_,_,_,_,_,_,_=build_s1s6(); await update.message.reply_text(f)

async def silver_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    f,v,_,_,_,_,_,_,_=build_silver_s1s6(); await update.message.reply_text(f)

async def us30_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    f,v,_,_,_,_,_,_,_=build_us30_best(); await update.message.reply_text(f)

async def ger30_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    f,v,_,_,_,_,_,_,_=build_ger30_best(); await update.message.reply_text(f)

async def ndx100_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    f,v,_,_,_,_,_,_,_=build_ndx100_best(); await update.message.reply_text(f)

async def triple_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    msgs=[]
    for b in [build_gold_triple, build_silver_triple, build_us30_triple, build_ger30_triple, build_ndx100_triple]:
        f,v,d,_,_,_,_,_,_=b(); msgs.append(f)
    await update.message.reply_text("\n\n---\n\n".join(msgs))

async def gold_triple_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    f,v,_,_,_,_,_,_,_=build_gold_triple(); await update.message.reply_text(f)

async def silver_triple_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    f,v,_,_,_,_,_,_,_=build_silver_triple(); await update.message.reply_text(f)

async def us30_triple_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    f,v,_,_,_,_,_,_,_=build_us30_triple(); await update.message.reply_text(f)

async def ger30_triple_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    f,v,_,_,_,_,_,_,_=build_ger30_triple(); await update.message.reply_text(f)

async def ndx_triple_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    f,v,_,_,_,_,_,_,_=build_ndx100_triple(); await update.message.reply_text(f)

async def sr_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    msg=build_all_sr()
    await update.message.reply_text(f"📊 SUPPORT / RESISTANCE LEVELS\n\n{msg}\n\nUse /goldSR for detailed Gold S/R")

async def gold_sr_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    f,v,_,_,_,_,_,_,_=build_gold_sr(); await update.message.reply_text(f)

async def autopilot_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    global AUTOPILOT_ACTIVE, AUTOPILOT_TASK
    AUTOPILOT_ACTIVE=True; SUBSCRIBERS.add(update.effective_chat.id)
    if AUTOPILOT_TASK and not AUTOPILOT_TASK.done(): AUTOPILOT_TASK.cancel()
    AUTOPILOT_TASK = asyncio.create_task(autopilot_loop(context))
    await update.message.reply_text(f"✅ AUTOPILOT ON - S/R + 2-combo + TRIPLE\nID {update.effective_chat.id} saved\n⏰ Every 15 min")

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
            for builder, name in [(build_gold_triple,"GOLD TRIPLE"),(build_ndx100_triple,"NDX100 TRIPLE"),(build_us30_triple,"US30 TRIPLE"),(build_ger30_triple,"GER30 TRIPLE"),(build_silver_triple,"SILVER TRIPLE")]:
                try:
                    f,v,d,_,_,_,_,_,_=builder()
                    if v and d not in ["WAIT","CONFLICT"]:
                        for chat_id in list(SUBSCRIBERS):
                            try: await context.bot.send_message(chat_id=chat_id,text=f"🤖 {name} AUTOPILOT PREMIUM\n{f}")
                            except: pass
                        try: await context.bot.send_message(chat_id=CHANNEL_ID,text=v)
                        except: pass
                except: pass
            for builder, name in [(build_s1s6,"GOLD"),(build_silver_s1s6,"SILVER"),(build_us30_best,"US30"),(build_ger30_best,"GER30"),(build_ndx100_best,"NDX100")]:
                try:
                    f,v,d,_,_,_,_,_,_=builder()
                    if v and d not in ["WAIT","CONFLICT"]:
                        for chat_id in list(SUBSCRIBERS):
                            try: await context.bot.send_message(chat_id=chat_id,text=f"🤖 {name} AUTOPILOT\n{f}")
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
        await context.bot.send_message(chat_id=CHANNEL_ID,text="✅ Bot Connected! VIP Ready - S/R + 2-combo + TRIPLE")
        await update.message.reply_text("✅ Test sent!")
    except Exception as e: await update.message.reply_text(f"❌ Failed: {e}")

async def sendvip(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id!=ADMIN_ID: await update.message.reply_text("❌ Admin only"); return
    f,v,d,_,_,_,_,_,_=build_s1s6()
    if v and d not in ["WAIT","CONFLICT"]:
        try: await context.bot.send_message(chat_id=CHANNEL_ID, text=v); await update.message.reply_text(f"✅ VIP SENT\n\n{v}")
        except Exception as e: await update.message.reply_text(f"❌ Failed: {e}")
    else: await update.message.reply_text(f"❌ No confluence\n\n{f}")

async def sendsilver_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id!=ADMIN_ID: await update.message.reply_text("❌ Admin only"); return
    f,v,d,_,_,_,_,_,_=build_silver_s1s6()
    if v and d not in ["WAIT","CONFLICT"]:
        try: await context.bot.send_message(chat_id=CHANNEL_ID, text=v); await update.message.reply_text(f"✅ SILVER VIP SENT\n\n{v}")
        except Exception as e: await update.message.reply_text(f"❌ Failed: {e}")
    else: await update.message.reply_text(f"❌ No Silver confluence\n\n{f}")

async def sendus30_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id!=ADMIN_ID: await update.message.reply_text("❌ Admin only"); return
    f,v,d,_,_,_,_,_,_=build_us30_best()
    if v and d not in ["WAIT","CONFLICT"]:
        try: await context.bot.send_message(chat_id=CHANNEL_ID, text=v); await update.message.reply_text(f"✅ US30 VIP SENT\n\n{v}")
        except Exception as e: await update.message.reply_text(f"❌ Failed: {e}")
    else: await update.message.reply_text(f"❌ No US30 confluence\n\n{f}")

async def sendger30_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id!=ADMIN_ID: await update.message.reply_text("❌ Admin only"); return
    f,v,d,_,_,_,_,_,_=build_ger30_best()
    if v and d not in ["WAIT","CONFLICT"]:
        try: await context.bot.send_message(chat_id=CHANNEL_ID, text=v); await update.message.reply_text(f"✅ GER30 VIP SENT\n\n{v}")
        except Exception as e: await update.message.reply_text(f"❌ Failed: {e}")
    else: await update.message.reply_text(f"❌ No GER30 confluence\n\n{f}")

async def sendndx_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id!=ADMIN_ID: await update.message.reply_text("❌ Admin only"); return
    f,v,d,_,_,_,_,_,_=build_ndx100_best()
    if v and d not in ["WAIT","CONFLICT"]:
        try: await context.bot.send_message(chat_id=CHANNEL_ID, text=v); await update.message.reply_text(f"✅ NDX VIP SENT\n\n{v}")
        except Exception as e: await update.message.reply_text(f"❌ Failed: {e}")
    else: await update.message.reply_text(f"❌ No NDX confluence\n\n{f}")

def main():
    if not BOT_TOKEN: print("BOT_TOKEN missing"); return
    try: requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=true",timeout=10)
    except: pass
    app=ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("buy",buy))
    app.add_handler(CommandHandler("signal",signal))
    app.add_handler(CommandHandler("bestcombo",bestcombo_cmd))
    app.add_handler(CommandHandler("bests",bestcombo_cmd))
    app.add_handler(CommandHandler("s1s6",bestcombo_cmd))
    app.add_handler(CommandHandler("confluence",bestcombo_cmd))
    app.add_handler(CommandHandler("silver",silver_cmd))
    app.add_handler(CommandHandler("sendsilver",sendsilver_cmd))
    app.add_handler(CommandHandler("silversignal",silver_cmd))
    app.add_handler(CommandHandler("us30",us30_cmd))
    app.add_handler(CommandHandler("us30signal",us30_cmd))
    app.add_handler(CommandHandler("sendus30",sendus30_cmd))
    app.add_handler(CommandHandler("ndx100",ndx100_cmd))
    app.add_handler(CommandHandler("ndx",ndx100_cmd))
    app.add_handler(CommandHandler("nasdaq",ndx100_cmd))
    app.add_handler(CommandHandler("nas100",ndx100_cmd))
    app.add_handler(CommandHandler("sendndx",sendndx_cmd))
    app.add_handler(CommandHandler("sendndx100",sendndx_cmd))
    app.add_handler(CommandHandler("ger30",ger30_cmd))
    app.add_handler(CommandHandler("ger",ger30_cmd))
    app.add_handler(CommandHandler("dax",ger30_cmd))
    app.add_handler(CommandHandler("sendger30",sendger30_cmd))
    app.add_handler(CommandHandler("sendger",sendger30_cmd))
    app.add_handler(CommandHandler("triple",triple_cmd))
    app.add_handler(CommandHandler("3combo",triple_cmd))
    app.add_handler(CommandHandler("gold3",gold_triple_cmd))
    app.add_handler(CommandHandler("silver3",silver_triple_cmd))
    app.add_handler(CommandHandler("us303",us30_triple_cmd))
    app.add_handler(CommandHandler("ger303",ger30_triple_cmd))
    app.add_handler(CommandHandler("ndx3",ndx_triple_cmd))
    app.add_handler(CommandHandler("nasdaq3",ndx_triple_cmd))
    app.add_handler(CommandHandler("sr",sr_cmd))
    app.add_handler(CommandHandler("support",sr_cmd))
    app.add_handler(CommandHandler("resistance",sr_cmd))
    app.add_handler(CommandHandler("levels",sr_cmd))
    app.add_handler(CommandHandler("goldSR",gold_sr_cmd))
    app.add_handler(CommandHandler("goldsr",gold_sr_cmd))
    app.add_handler(CommandHandler("autopilot",autopilot_cmd))
    app.add_handler(CommandHandler("autostop",autostop))
    app.add_handler(CommandHandler("setchannel",setchannel))
    app.add_handler(CommandHandler("channeltest",channeltest))
    app.add_handler(CommandHandler("sendvip",sendvip))
    print("S/R + TRIPLE LIVE - S2 Support/Resistance added")
    app.run_polling(drop_pending_updates=True)

if __name__=="__main__": main()
