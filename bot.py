import os
import json
import requests
from datetime import datetime

# ── SETTINGS (match your Pine Script inputs) ─────────────────────
MIN_ACCUM_CANDLES = 13       # Min candles to form a zone
INIT_RANGE_PCT    = 0.60     # Zone tightness %
WICK_BUFFER_PCT   = 0.10     # Wick buffer %
MIN_BODY_PTS      = 6.0      # Min breakout candle body size in $
STATE_FILE        = "zone_state.json"

# ── API + TELEGRAM CREDENTIALS ───────────────────────────────────
BOT_TOKEN       = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID         = os.environ["TELEGRAM_CHAT_ID"]
TWELVEDATA_KEY  = os.environ["TWELVEDATA_API_KEY"]

# ── TELEGRAM ─────────────────────────────────────────────────────
def send_telegram(message):
    url  = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    resp = requests.post(url, data={"chat_id": CHAT_ID, "text": message})
    print(f"Telegram response: {resp.status_code} {resp.text}")

# ── LOAD / SAVE ZONE STATE ────────────────────────────────────────
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    default = {
        "zone_high":         None,
        "zone_low":          None,
        "zone_active":       False,
        "alerted_this_zone": False
    }
    save_state(default)
    return default

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# ── FETCH XAUUSD 5-MIN CANDLES FROM TWELVE DATA ──────────────────
def get_candles():
    url    = "https://api.twelvedata.com/time_series"
    params = {
        "symbol":      "XAU/USD",
        "interval":    "5min",
        "outputsize":  60,          # last 60 candles (~5 hours)
        "apikey":      TWELVEDATA_KEY,
        "format":      "JSON"
    }
    resp = requests.get(url, params=params)
    data = resp.json()

    if "values" not in data:
        print(f"Twelve Data error: {data}")
        return None

    candles = []
    for c in reversed(data["values"]):   # reverse so oldest first
        candles.append({
            "open":  float(c["open"]),
            "high":  float(c["high"]),
            "low":   float(c["low"]),
            "close": float(c["close"]),
            "time":  c["datetime"]
        })

    print(f"Fetched {len(candles)} candles. Latest close: {candles[-1]['close']} at {candles[-1]['time']}")
    return candles

# ── MAIN LOGIC ────────────────────────────────────────────────────
def run():
    state   = load_state()
    candles = get_candles()

    if candles is None or len(candles) < MIN_ACCUM_CANDLES + 2:
        print("Not enough candles yet")
        return

    # Exclude the current forming candle — use all but the last one
    completed = candles[:-1]
    lookback  = completed[-MIN_ACCUM_CANDLES:]
    current   = completed[-1]   # most recently closed candle

    zone_high          = state["zone_high"]
    zone_low           = state["zone_low"]
    zone_active        = state["zone_active"]
    alerted_this_zone  = state["alerted_this_zone"]

    # ── ZONE FORMATION ─────────────────────────────────────────────
    if not zone_active:
        h         = max(c["high"]  for c in lookback)
        l         = min(c["low"]   for c in lookback)
        range_pct = (h - l) / l * 100 if l > 0 else 999
        print(f"Zone check: High={h:.2f} Low={l:.2f} Range={range_pct:.3f}%")
        if range_pct <= INIT_RANGE_PCT:
            zone_high         = h
            zone_low          = l
            zone_active       = True
            alerted_this_zone = False
            print(f"✅ Zone formed: High={zone_high:.2f} Low={zone_low:.2f}")

    # ── WICK BUFFER ────────────────────────────────────────────────
    if zone_active and zone_high is not None:
        upper_buffer = zone_high * (WICK_BUFFER_PCT / 100)
        lower_buffer = zone_low  * (WICK_BUFFER_PCT / 100)

        if current["high"] > zone_high and current["high"] <= zone_high + upper_buffer:
            zone_high = current["high"]
            print(f"Zone high adjusted to {zone_high:.2f}")

        if current["low"] < zone_low and current["low"] >= zone_low - lower_buffer:
            zone_low = current["low"]
            print(f"Zone low adjusted to {zone_low:.2f}")

    # ── ZONE INVALIDATION ──────────────────────────────────────────
    if zone_active and zone_high is not None:
        recent = completed[-MIN_ACCUM_CANDLES:]
        recent_closes = [c["close"] for c in recent]

        if min(recent_closes) > zone_high:
            print("Zone invalidated — all closes above zone high")
            zone_active       = False
            zone_high         = None
            zone_low          = None
            alerted_this_zone = False

        elif max(recent_closes) < zone_low:
            print("Zone invalidated — all closes below zone low")
            zone_active       = False
            zone_high         = None
            zone_low          = None
            alerted_this_zone = False

    # ── BREAKOUT DETECTION ─────────────────────────────────────────
    if zone_active and not alerted_this_zone and zone_high is not None:
        o         = current["open"]
        c         = current["close"]
        body_pts  = abs(c - o)

        print(f"Checking breakout — Close={c:.2f} Open={o:.2f} Body=${body_pts:.2f} ZoneHigh={zone_high:.2f} ZoneLow={zone_low:.2f}")

        # BUY signal
        if c > o and c > zone_high and body_pts >= MIN_BODY_PTS:
            msg = (
                f"🟢 XAUUSD BUY SIGNAL\n"
                f"📍 Close above accumulation zone high\n"
                f"💰 Close: {c:.2f}\n"
                f"📊 Zone High: {zone_high:.2f}\n"
                f"📏 Candle Body: ${body_pts:.2f}\n"
                f"⏱ Time: {current['time']} UTC"
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
                f"⏱ Time: {current['time']} UTC"
            )
            send_telegram(msg)
            print("SELL signal sent")
            alerted_this_zone = True

    # ── TEST MESSAGE (remove after confirming it works) ────────────
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
