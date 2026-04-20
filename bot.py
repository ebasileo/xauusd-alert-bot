import os
import json
import requests
import yfinance as yf
from datetime import datetime

# ── SETTINGS (match your Pine Script inputs) ─────────────────────
MIN_ACCUM_CANDLES = 13       # Min candles to form a zone
INIT_RANGE_PCT    = 0.60     # Zone tightness %
WICK_BUFFER_PCT   = 0.10     # Wick buffer %
MIN_BODY_PTS      = 6.0      # Min breakout candle body size in $
STATE_FILE        = "zone_state.json"

# ── TELEGRAM ─────────────────────────────────────────────────────
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]

def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": message})

# ── LOAD / SAVE ZONE STATE ────────────────────────────────────────
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    # First run — create a blank state
    default = {
        "zone_high": None,
        "zone_low": None,
        "zone_active": False,
        "alerted_this_zone": False
    }
    save_state(default)
    return default

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

# ── FETCH XAUUSD 5-MIN CANDLES ────────────────────────────────────
def get_candles():
    ticker = yf.Ticker("GC=F")   # Gold futures — closest free proxy to XAUUSD
    df = ticker.history(period="1d", interval="5m")
    df = df.dropna()
    return df

# ── MAIN LOGIC ────────────────────────────────────────────────────
def run():
    state = load_state()
    df    = get_candles()

    if len(df) < MIN_ACCUM_CANDLES + 2:
        print("Not enough candles yet")
        return

    # Use all completed candles — exclude the current forming one
    completed = df.iloc[:-1]
    lookback  = completed.tail(MIN_ACCUM_CANDLES)
    current   = completed.iloc[-1]   # last fully closed candle

    zone_high          = state["zone_high"]
    zone_low           = state["zone_low"]
    zone_active        = state["zone_active"]
    alerted_this_zone  = state["alerted_this_zone"]

    # ── ZONE FORMATION ─────────────────────────────────────────────
    if not zone_active:
        h         = lookback["High"].max()
        l         = lookback["Low"].min()
        range_pct = (h - l) / l * 100 if l > 0 else 999
        if range_pct <= INIT_RANGE_PCT:
            zone_high         = h
            zone_low          = l
            zone_active       = True
            alerted_this_zone = False
            print(f"Zone formed: High={zone_high:.2f} Low={zone_low:.2f}")

    # ── WICK BUFFER ────────────────────────────────────────────────
    if zone_active and zone_high is not None:
        upper_buffer = zone_high * (WICK_BUFFER_PCT / 100)
        lower_buffer = zone_low  * (WICK_BUFFER_PCT / 100)

        if current["High"] > zone_high and current["High"] <= zone_high + upper_buffer:
            zone_high = current["High"]
            print(f"Zone high adjusted to {zone_high:.2f}")

        if current["Low"] < zone_low and current["Low"] >= zone_low - lower_buffer:
            zone_low = current["Low"]
            print(f"Zone low adjusted to {zone_low:.2f}")

    # ── ZONE INVALIDATION ──────────────────────────────────────────
    if zone_active and zone_high is not None:
        recent_closes = completed.tail(MIN_ACCUM_CANDLES)["Close"]
        if recent_closes.min() > zone_high:
            print("Zone invalidated — all closes above zone high")
            zone_active = False
            zone_high   = None
            zone_low    = None
        elif recent_closes.max() < zone_low:
            print("Zone invalidated — all closes below zone low")
            zone_active = False
            zone_high   = None
            zone_low    = None

    # ── BREAKOUT DETECTION ─────────────────────────────────────────
    if zone_active and not alerted_this_zone and zone_high is not None:
        o = current["Open"]
        c = current["Close"]
        body_pts = abs(c - o)

        # BUY signal
        if c > o and c > zone_high and body_pts >= MIN_BODY_PTS:
            msg = (
                f"🟢 XAUUSD BUY SIGNAL\n"
                f"📍 Close above accumulation zone high\n"
                f"💰 Close: {c:.2f}\n"
                f"📊 Zone High: {zone_high:.2f}\n"
                f"📏 Candle Body: ${body_pts:.2f}\n"
                f"⏱ Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC"
            )
            send_telegram(msg)
            print("BUY signal sent")
            alerted_this_zone = True

        # SELL signal
        elif c < o and c < zone_low and body_pts >= MIN_BODY_PTS:
            msg = (
                f"🔴 XAUUSD SELL SIGNAL\n"
                f"📍 Close below accumulation zone low\n"
                f"💰 Close: {c:.2f}\n"
                f"📊 Zone Low: {zone_low:.2f}\n"
                f"📏 Candle Body: ${body_pts:.2f}\n"
                f"⏱ Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC"
            )
            send_telegram(msg)
            print("SELL signal sent")
            alerted_this_zone = True
            
send_telegram("✅ Bot is running correctly - " + datetime.utcnow().strftime('%H:%M UTC'))

 
    # ── SAVE STATE ─────────────────────────────────────────────────
    save_state({
        "zone_high":         zone_high,
        "zone_low":          zone_low,
        "zone_active":       zone_active,
        "alerted_this_zone": alerted_this_zone
    })

if __name__ == "__main__":
    run()
