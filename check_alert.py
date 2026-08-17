"""
check_alert.py
---------------
סקריפט עצמאי (לא Streamlit) שנועד לרוץ אוטומטית ב-GitHub Actions.
בודק תנאי מחיר/ממוצע נע עבור מניה אחת (או כמה, ראו WATCHLIST למטה)
ושולח התראה לדיסקורד אם התנאי מתקיים.

כל ההגדרות מגיעות ממשתני סביבה (Environment Variables), כדי שלא יהיה
שום סוד (webhook) מוטבע בקוד. ב-GitHub Actions מגדירים אותם כ-Secrets.
"""

import os
import sys
import json
import requests
import yfinance as yf
from datetime import datetime, timezone


def send_discord_alert(webhook_url: str, message: str) -> bool:
    if not webhook_url:
        print("שגיאה: לא הוגדר DISCORD_WEBHOOK_URL.")
        return False
    try:
        resp = requests.post(webhook_url, json={"content": message}, timeout=15)
        if resp.status_code in (200, 204):
            print("ההודעה נשלחה בהצלחה לדיסקורד.")
            return True
        print(f"שליחה נכשלה: {resp.status_code} - {resp.text}")
        return False
    except requests.RequestException as e:
        print(f"שגיאת רשת בשליחה לדיסקורד: {e}")
        return False


def check_one(symbol: str, condition: dict, webhook_url: str) -> None:
    """
    condition לדוגמה:
      {"type": "price_above", "value": 300}
      {"type": "price_below", "value": 100}
      {"type": "ma_cross_above", "window": 50}
      {"type": "ma_cross_below", "window": 50}
    """
    ticker = yf.Ticker(symbol)
    hist = ticker.history(period="6mo")

    if hist.empty:
        print(f"[{symbol}] לא נמצאו נתונים - מדלג.")
        return

    current_price = float(hist["Close"].iloc[-1])
    ctype = condition.get("type")
    met = False
    description = ""

    if ctype == "price_above":
        target = float(condition["value"])
        met = current_price > target
        description = f"{symbol}: מחיר נוכחי ${current_price:,.2f} מעל היעד ${target:,.2f}"

    elif ctype == "price_below":
        target = float(condition["value"])
        met = current_price < target
        description = f"{symbol}: מחיר נוכחי ${current_price:,.2f} מתחת ליעד ${target:,.2f}"

    elif ctype in ("ma_cross_above", "ma_cross_below"):
        window = int(condition.get("window", 50))
        if len(hist) < window:
            print(f"[{symbol}] אין מספיק נתונים לחישוב ממוצע נע של {window} ימים - מדלג.")
            return
        ma_value = float(hist["Close"].rolling(window=window).mean().iloc[-1])
        if ctype == "ma_cross_above":
            met = current_price > ma_value
            description = (
                f"{symbol}: מחיר ${current_price:,.2f} מעל הממוצע הנע "
                f"({window} ימים) של ${ma_value:,.2f}"
            )
        else:
            met = current_price < ma_value
            description = (
                f"{symbol}: מחיר ${current_price:,.2f} מתחת לממוצע הנע "
                f"({window} ימים) של ${ma_value:,.2f}"
            )
    else:
        print(f"[{symbol}] סוג תנאי לא מוכר: {ctype}")
        return

    print(f"[{symbol}] {description} | תנאי מתקיים: {met}")

    if met:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        message = f"🚨 **התראת מניה** 🚨\n{description}\n🕒 {timestamp}"
        send_discord_alert(webhook_url, message)


def build_watchlist_from_env() -> list[dict]:
    """
    שתי דרכים להגדיר את רשימת המעקב:

    1) WATCHLIST - JSON שמתאר כמה מניות בבת אחת, לדוגמה:
       [
         {"symbol": "TSLA", "condition": {"type": "price_above", "value": 300}},
         {"symbol": "NVDA", "condition": {"type": "ma_cross_below", "window": 50}}
       ]

    2) אם WATCHLIST לא מוגדר, נופלים חזרה למשתנים פשוטים למניה אחת:
       SYMBOL, CONDITION_TYPE, CONDITION_VALUE, MA_WINDOW
    """
    watchlist_json = os.environ.get("WATCHLIST")
    if watchlist_json:
        try:
            return json.loads(watchlist_json)
        except json.JSONDecodeError as e:
            print(f"שגיאה בפענוח WATCHLIST JSON: {e}")
            sys.exit(1)

    symbol = os.environ.get("SYMBOL", "TSLA").upper().strip()
    condition_type = os.environ.get("CONDITION_TYPE", "price_above")
    condition: dict = {"type": condition_type}

    if condition_type in ("price_above", "price_below"):
        condition["value"] = float(os.environ.get("CONDITION_VALUE", "100"))
    elif condition_type in ("ma_cross_above", "ma_cross_below"):
        condition["window"] = int(os.environ.get("MA_WINDOW", "50"))
    else:
        print(f"CONDITION_TYPE לא מוכר: {condition_type}")
        sys.exit(1)

    return [{"symbol": symbol, "condition": condition}]


def main() -> None:
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not webhook_url:
        print("שגיאה קריטית: משתנה הסביבה DISCORD_WEBHOOK_URL לא מוגדר. עוצר.")
        sys.exit(1)

    watchlist = build_watchlist_from_env()
    print(f"בודק {len(watchlist)} פריט/ים...")

    for item in watchlist:
        check_one(item["symbol"].upper().strip(), item["condition"], webhook_url)


if __name__ == "__main__":
    main()
