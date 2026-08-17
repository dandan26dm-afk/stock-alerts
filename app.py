import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import json
import os
import uuid
from datetime import datetime

st.set_page_config(page_title="Stock Alert Bot", page_icon="📈", layout="wide")

st.title("📈 Stock Alert Bot")
st.caption("נהל רשימת התראות למניות, בדוק אותן ידנית, וקבל התראות בדיסקורד.")

# --- קבצי אחסון מקומיים -----------------------------------------------------
ALERTS_FILE = "alerts.json"
HISTORY_FILE = "history.json"

# הערה חשובה: אחסון בקובץ JSON מקומי עובד מצוין כשמריצים את Streamlit
# על המחשב שלכם או על שרת עם דיסק קבוע. בפלטפורמות ענן מסוימות (כמו
# Streamlit Community Cloud) מערכת הקבצים היא זמנית (ephemeral) ומתאפסת
# בכל דיפלוי/הפעלה מחדש - כלומר הנתונים עלולים להימחק. אם תריצו שם,
# שקלו לגבות את alerts.json מדי פעם, או לעבור לאחסון חיצוני (DB / Gist).


def load_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def save_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_alerts() -> list[dict]:
    return load_json(ALERTS_FILE, [])


def save_alerts(alerts: list[dict]) -> None:
    save_json(ALERTS_FILE, alerts)


def load_history() -> list[dict]:
    return load_json(HISTORY_FILE, [])


def append_history(entry: dict, max_entries: int = 500) -> None:
    history = load_history()
    history.insert(0, entry)  # החדש ביותר בראש הרשימה
    history = history[:max_entries]
    save_json(HISTORY_FILE, history)


# --- Discord Webhook -------------------------------------------------------
# חשוב מבחינת אבטחה: אל תשתילו את כתובת ה-Webhook ישירות בקוד. השתמשו
# בשדה הקלט בסיידבר, במשתנה סביבה DISCORD_WEBHOOK_URL, או ב-Streamlit secrets.
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
    st.caption(f"📄 קובץ התראות: `{ALERTS_FILE}`")
    st.caption(f"📄 קובץ היסטוריה: `{HISTORY_FILE}`")


# --- פונקציות עזר: מניות ודיסקורד -------------------------------------------

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


# מיפוי בין תיאור בעברית (בממשק) לבין קוד תנאי פנימי, זהה לפורמט
# שמשמש גם את check_alert.py ואת ה-WATCHLIST ב-GitHub Actions.
CONDITION_LABELS = {
    "price_above": "מחיר מעל",
    "price_below": "מחיר מתחת",
    "ma_cross_above": "ממוצע נע - חציה מעל",
    "ma_cross_below": "ממוצע נע - חציה מתחת",
}
CONDITION_LABELS_REVERSE = {v: k for k, v in CONDITION_LABELS.items()}
PRICE_CONDITIONS = ("price_above", "price_below")
MA_CONDITIONS = ("ma_cross_above", "ma_cross_below")


def evaluate_condition(symbol: str, condition: dict) -> tuple[bool | None, str]:
    """
    בודק תנאי מול נתונים חיים מ-yfinance.
    מחזיר (met, description). met=None אומר שהבדיקה נכשלה (למשל אין נתונים).
    """
    data = get_stock_data(symbol)
    if data is None:
        return None, f"{symbol}: לא נמצאו נתונים עבור הסימול הזה."

    current_price = float(data["Close"].iloc[-1])
    ctype = condition.get("type")

    if ctype == "price_above":
        target = float(condition["value"])
        met = current_price > target
        desc = f"{symbol}: מחיר נוכחי ${current_price:,.2f}, {'מעל' if met else 'עדיין לא מעל'} היעד ${target:,.2f}"
        return met, desc

    if ctype == "price_below":
        target = float(condition["value"])
        met = current_price < target
        desc = f"{symbol}: מחיר נוכחי ${current_price:,.2f}, {'מתחת' if met else 'עדיין לא מתחת'} ליעד ${target:,.2f}"
        return met, desc

    if ctype in MA_CONDITIONS:
        window = int(condition.get("window", 50))
        if len(data) < window:
            return None, f"{symbol}: אין מספיק נתונים לחישוב ממוצע נע של {window} ימים."
        ma_value = float(data["Close"].rolling(window=window).mean().iloc[-1])
        if ctype == "ma_cross_above":
            met = current_price > ma_value
            desc = f"{symbol}: מחיר ${current_price:,.2f} {'מעל' if met else 'לא מעל'} הממוצע הנע ({window} ימים) של ${ma_value:,.2f}"
        else:
            met = current_price < ma_value
            desc = f"{symbol}: מחיר ${current_price:,.2f} {'מתחת' if met else 'לא מתחת'} לממוצע הנע ({window} ימים) של ${ma_value:,.2f}"
        return met, desc

    return None, f"{symbol}: סוג תנאי לא מוכר ({ctype})."


def condition_to_text(condition: dict) -> str:
    ctype = condition.get("type")
    if ctype in PRICE_CONDITIONS:
        return f"{CONDITION_LABELS.get(ctype, ctype)} ${condition.get('value')}"
    if ctype in MA_CONDITIONS:
        return f"{CONDITION_LABELS.get(ctype, ctype)} ({condition.get('window')} ימים)"
    return str(condition)


def run_check_and_log(alert: dict, send_if_met: bool = True) -> dict:
    """מריץ בדיקה עבור התראה בודדת, שולח לדיסקורד אם צריך, ומחזיר רשומת לוג."""
    symbol = alert["symbol"]
    condition = alert["condition"]
    met, description = evaluate_condition(symbol, condition)

    alert_sent = False
    send_info = ""
    if met and send_if_met:
        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message = f"🚨 **התראת מניה** 🚨\n{description}\n🕒 {timestamp_str}"
        ok, info = send_discord_alert(webhook_url, message)
        alert_sent = ok
        send_info = info

    entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "alert_id": alert.get("id"),
        "symbol": symbol,
        "condition_text": condition_to_text(condition),
        "condition_met": bool(met) if met is not None else False,
        "check_failed": met is None,
        "alert_sent": alert_sent,
        "description": description,
        "send_info": send_info,
    }
    append_history(entry)
    return entry


# --- ממשק: טאבים -------------------------------------------------------------
tab1, tab2 = st.tabs(["📋 ניהול התראות ומעקב", "🗒️ היסטוריית פעולות (Logs)"])

# ============================= טאב 1 =========================================
with tab1:
    alerts = load_alerts()

    st.subheader("➕ הוספת התראה חדשה")
    with st.form("add_alert_form", clear_on_submit=True):
        col1, col2, col3 = st.columns([2, 2, 2])
        with col1:
            new_symbol = st.text_input("סימול מניה (Ticker)", placeholder="TSLA").upper().strip()
        with col2:
            new_type_label = st.selectbox("סוג התראה", list(CONDITION_LABELS.values()))
        new_type = CONDITION_LABELS_REVERSE[new_type_label]
        with col3:
            if new_type in PRICE_CONDITIONS:
                new_value = st.number_input("מחיר יעד ($)", min_value=0.0, value=100.0, step=1.0)
            else:
                new_value = st.number_input("חלון ממוצע נע (ימים)", min_value=2, max_value=250, value=50)

        submitted = st.form_submit_button("➕ הוסף התראה", type="primary", use_container_width=True)
        if submitted:
            if not new_symbol:
                st.warning("יש להזין סימול מניה.")
            else:
                if new_type in PRICE_CONDITIONS:
                    condition = {"type": new_type, "value": float(new_value)}
                else:
                    condition = {"type": new_type, "window": int(new_value)}

                new_alert = {
                    "id": uuid.uuid4().hex[:8],
                    "symbol": new_symbol,
                    "condition": condition,
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                alerts.append(new_alert)
                save_alerts(alerts)
                st.success(f"נוספה התראה עבור {new_symbol}.")
                st.rerun()

    st.divider()
    st.subheader(f"📋 רשימת התראות שמורות ({len(alerts)})")

    if not alerts:
        st.info("אין עדיין התראות שמורות. הוסיפו אחת למעלה כדי להתחיל.")
    else:
        col_check_all, _ = st.columns([1, 3])
        with col_check_all:
            check_all_clicked = st.button(
                "🔍 בדוק את כל ההתראות ושלח לדיסקורד", type="primary", use_container_width=True
            )

        if check_all_clicked:
            with st.spinner("בודק את כל ההתראות..."):
                results = [run_check_and_log(a) for a in alerts]
            met_count = sum(1 for r in results if r["condition_met"])
            sent_count = sum(1 for r in results if r["alert_sent"])
            st.success(f"נבדקו {len(results)} התראות. {met_count} תנאים התקיימו, {sent_count} הודעות נשלחו.")

        st.write("")

        for alert in alerts:
            symbol = alert["symbol"]
            condition = alert["condition"]
            with st.expander(f"📌 {symbol} — {condition_to_text(condition)}", expanded=False):
                col_a, col_b = st.columns([3, 1])

                with col_a:
                    st.caption(f"נוצר בתאריך: {alert.get('created_at', '—')} | מזהה: `{alert['id']}`")

                    # --- עריכה ---
                    with st.form(f"edit_form_{alert['id']}"):
                        e_col1, e_col2, e_col3 = st.columns([2, 2, 2])
                        with e_col1:
                            edit_symbol = st.text_input(
                                "סימול", value=symbol, key=f"sym_{alert['id']}"
                            ).upper().strip()
                        with e_col2:
                            current_label = CONDITION_LABELS[condition["type"]]
                            edit_type_label = st.selectbox(
                                "סוג התראה",
                                list(CONDITION_LABELS.values()),
                                index=list(CONDITION_LABELS.values()).index(current_label),
                                key=f"type_{alert['id']}",
                            )
                        edit_type = CONDITION_LABELS_REVERSE[edit_type_label]
                        with e_col3:
                            if edit_type in PRICE_CONDITIONS:
                                default_val = float(condition.get("value", 100.0))
                                edit_value = st.number_input(
                                    "מחיר יעד ($)", min_value=0.0, value=default_val, step=1.0,
                                    key=f"val_{alert['id']}",
                                )
                            else:
                                default_win = int(condition.get("window", 50))
                                edit_value = st.number_input(
                                    "חלון ממוצע נע (ימים)", min_value=2, max_value=250, value=default_win,
                                    key=f"win_{alert['id']}",
                                )

                        save_col, delete_col, test_col = st.columns(3)
                        save_clicked = save_col.form_submit_button("💾 שמור שינויים", use_container_width=True)
                        delete_clicked = delete_col.form_submit_button(
                            "🗑️ מחק התראה", use_container_width=True
                        )
                        test_clicked = test_col.form_submit_button(
                            "🔍 בדוק עכשיו", use_container_width=True
                        )

                    if save_clicked:
                        if edit_type in PRICE_CONDITIONS:
                            new_condition = {"type": edit_type, "value": float(edit_value)}
                        else:
                            new_condition = {"type": edit_type, "window": int(edit_value)}
                        alert["symbol"] = edit_symbol
                        alert["condition"] = new_condition
                        save_alerts(alerts)
                        st.success("ההתראה עודכנה.")
                        st.rerun()

                    if delete_clicked:
                        alerts = [a for a in alerts if a["id"] != alert["id"]]
                        save_alerts(alerts)
                        st.success("ההתראה נמחקה.")
                        st.rerun()

                    if test_clicked:
                        with st.spinner(f"בודק את {symbol}..."):
                            result = run_check_and_log(alert)
                        st.write(result["description"])
                        if result["check_failed"]:
                            st.warning("הבדיקה נכשלה (ראו הודעה למעלה).")
                        elif result["condition_met"]:
                            if result["alert_sent"]:
                                st.success("✅ התנאי התקיים וההודעה נשלחה לדיסקורד!")
                            else:
                                st.error(f"❌ התנאי התקיים אבל השליחה נכשלה: {result['send_info']}")
                        else:
                            st.info("התנאי עדיין לא התקיים - לא נשלחה הודעה.")

    st.divider()
    st.subheader("📤 ייצוא רשימת ההתראות ל-GitHub Actions")
    st.caption(
        "העתיקו את ה-JSON הבא והדביקו אותו כערך של המשתנה `WATCHLIST` "
        "בטאב Settings → Secrets and variables → Actions → Variables בריפו שלכם."
    )
    if alerts:
        watchlist_export = [
            {"symbol": a["symbol"], "condition": a["condition"]} for a in alerts
        ]
        st.code(json.dumps(watchlist_export, ensure_ascii=False, indent=2), language="json")
    else:
        st.info("אין התראות לייצוא כרגע.")


# ============================= טאב 2 =========================================
with tab2:
    st.subheader("🗒️ היסטוריית פעולות")
    history = load_history()

    col_refresh, col_clear = st.columns([1, 1])
    with col_refresh:
        if st.button("🔄 רענן", use_container_width=True):
            st.rerun()
    with col_clear:
        if st.button("🧹 נקה היסטוריה", use_container_width=True):
            save_json(HISTORY_FILE, [])
            st.success("ההיסטוריה נוקתה.")
            st.rerun()

    if not history:
        st.info("אין עדיין רשומות בהיסטוריה. בצעו בדיקה בטאב הראשון כדי לראות תוצאות כאן.")
    else:
        df = pd.DataFrame(history)
        df_display = df.rename(
            columns={
                "timestamp": "תאריך ושעה",
                "symbol": "סימול",
                "condition_text": "תנאי",
                "condition_met": "תנאי התקיים",
                "check_failed": "הבדיקה נכשלה",
                "alert_sent": "נשלחה הודעה",
                "description": "תיאור",
            }
        )
        columns_order = [
            "תאריך ושעה", "סימול", "תנאי", "תנאי התקיים",
            "נשלחה הודעה", "הבדיקה נכשלה", "תיאור",
        ]
        st.dataframe(
            df_display[columns_order],
            use_container_width=True,
            hide_index=True,
        )
