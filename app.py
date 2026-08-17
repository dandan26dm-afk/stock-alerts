import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from datetime import datetime

st.set_page_config(page_title="Stock Alert Bot", page_icon="📈", layout="centered")

st.title("📈 Stock Alert Bot")
st.caption("עקוב אחרי מניה, הגדר תנאי מחיר, וקבל התראה בדיסקורד.")

# --- Discord Webhook -------------------------------------------------------
# חשוב מבחינת אבטחה: אל תשתילו את כתובת ה-Webhook ישירות בקוד, בטח לא אם
# אתם מעלים את הקוד ל-GitHub או משתפים אותו. כל מי שיש לו את הכתובת יכול
# לשלוח הודעות לערוץ שלכם. השתמשו במקום זה באחת מהאפשרויות הבאות:
#   1. שדה קלט בממשק (ברירת המחדל כאן) - נשמר רק בזיכרון של הסשן.
#   2. משתנה סביבה: DISCORD_WEBHOOK_URL
#   3. Streamlit secrets (st.secrets["discord_webhook"]) בקובץ .streamlit/secrets.toml
import os

default_webhook = os.environ.get("DISCORD_WEBHOOK_URL", "")
try:
    default_webhook = st.secrets.get("discord_webhook", default_webhook)
except Exception:
    pass

with st.sidebar:
    st.header("⚙️ הגדרות")
    webhook_url = st.text_input(
        "Discord Webhook URL",
        value=default_webhook,
        type="password",
        help="הדביקו כאן את כתובת ה-Webhook של ערוץ הדיסקורד שלכם.",
    )

    st.divider()
    symbol = st.text_input("סימול מניה (Ticker)", value="TSLA").upper().strip()

    condition_type = st.radio(
        "סוג התנאי",
        ["מחיר יעד", "ממוצע נע (Moving Average)"],
    )

    target_price = None
    ma_window = None
    ma_direction = None

    if condition_type == "מחיר יעד":
        col1, col2 = st.columns(2)
        with col1:
            direction = st.selectbox("כיוון", ["מעל", "מתחת"])
        with col2:
            target_price = st.number_input("מחיר יעד ($)", min_value=0.0, value=100.0, step=1.0)
    else:
        ma_window = st.number_input("חלון ממוצע נע (ימים)", min_value=2, max_value=250, value=50)
        ma_direction = st.selectbox(
            "תנאי", ["המחיר הנוכחי חוצה מעל הממוצע הנע", "המחיר הנוכחי חוצה מתחת לממוצע הנע"]
        )


def send_discord_alert(webhook_url: str, message: str) -> tuple[bool, str]:
    """שולח הודעה לדיסקורד דרך Webhook. מחזיר (הצלחה, טקסט_תגובה)."""
    if not webhook_url:
        return False, "לא הוגדרה כתובת Webhook."
    try:
        resp = requests.post(webhook_url, json={"content": message}, timeout=10)
        if resp.status_code in (200, 204):
            return True, "נשלח בהצלחה"
        return False, f"שגיאה מהשרת: {resp.status_code} - {resp.text}"
    except requests.RequestException as e:
        return False, f"שגיאת רשת: {e}"


def get_stock_data(ticker: str, period: str = "6mo") -> pd.DataFrame | None:
    try:
        data = yf.Ticker(ticker).history(period=period)
        if data.empty:
            return None
        return data
    except Exception:
        return None


st.subheader(f"נתונים עבור {symbol or '—'}")

data = get_stock_data(symbol) if symbol else None

if data is None:
    st.warning("לא נמצאו נתונים עבור הסימול הזה. ודאו שהקלדתם סימול תקין (למשל TSLA, NVDA, AAPL).")
else:
    current_price = float(data["Close"].iloc[-1])
    st.metric("מחיר נוכחי", f"${current_price:,.2f}")

    ma_value = None
    if condition_type == "ממוצע נע (Moving Average)" and ma_window:
        if len(data) >= ma_window:
            ma_value = float(data["Close"].rolling(window=int(ma_window)).mean().iloc[-1])
            st.metric(f"ממוצע נע {ma_window} ימים", f"${ma_value:,.2f}")
        else:
            st.info("אין מספיק היסטוריית מחירים כדי לחשב את הממוצע הנע המבוקש.")

    st.line_chart(data["Close"])

    st.divider()

    def check_condition() -> tuple[bool, str]:
        """בודק אם התנאי מתקיים ומחזיר (מתקיים?, תיאור)."""
        if condition_type == "מחיר יעד":
            if direction == "מעל":
                met = current_price > target_price
                desc = f"{symbol} נסחרת ב-${current_price:,.2f}, {'מעל' if met else 'עדיין לא מעל'} היעד ${target_price:,.2f}"
            else:
                met = current_price < target_price
                desc = f"{symbol} נסחרת ב-${current_price:,.2f}, {'מתחת' if met else 'עדיין לא מתחת'} ליעד ${target_price:,.2f}"
            return met, desc
        else:
            if ma_value is None:
                return False, "אין מספיק נתונים לחישוב הממוצע הנע."
            if ma_direction == "המחיר הנוכחי חוצה מעל הממוצע הנע":
                met = current_price > ma_value
                desc = f"{symbol}: מחיר ${current_price:,.2f} {'מעל' if met else 'לא מעל'} הממוצע הנע ({ma_window} ימים) של ${ma_value:,.2f}"
            else:
                met = current_price < ma_value
                desc = f"{symbol}: מחיר ${current_price:,.2f} {'מתחת' if met else 'לא מתחת'} לממוצע הנע ({ma_window} ימים) של ${ma_value:,.2f}"
            return met, desc

    if st.button("🔍 בדוק תנאי ושלח התראה לדיסקורד", type="primary", use_container_width=True):
        met, description = check_condition()
        st.write(description)

        if met:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = f"🚨 **התראת מניה** 🚨\n{description}\n🕒 {timestamp}"
            ok, info = send_discord_alert(webhook_url, message)
            if ok:
                st.success("✅ התנאי התקיים וההודעה נשלחה לדיסקורד!")
            else:
                st.error(f"❌ התנאי התקיים אבל שליחת ההודעה נכשלה: {info}")
        else:
            st.info("התנאי עדיין לא התקיים - לא נשלחה הודעה.")

    st.divider()
    if st.button("📨 שלח הודעת בדיקה לדיסקורד (בלי תנאי)"):
        ok, info = send_discord_alert(
            webhook_url, f"👋 הודעת בדיקה מ-Stock Alert Bot עבור {symbol}."
        )
        if ok:
            st.success("הודעת הבדיקה נשלחה בהצלחה!")
        else:
            st.error(f"שליחה נכשלה: {info}")

st.divider()
st.caption(
    "💡 טיפ: כדי להריץ בדיקות אוטומטיות (למשל כל 5 דקות) בלי לפתוח את הדפדפן, "
    "אפשר להריץ סקריפט נפרד (לא Streamlit) בלולאה עם cron / Task Scheduler, "
    "שמייבא את get_stock_data ו-send_discord_alert מהקובץ הזה."
)
