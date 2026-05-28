#!/usr/bin/env python3
"""
Daily Brief Generator
- Fetches weather from Open-Meteo (free, no API key needed)
- Fetches Google Calendar events
- Generates executive summary via Claude API
- Sends to Discord webhook
"""

import os
import json
import datetime
import requests
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import anthropic
import pickle

# ─────────────────────────────────────────────
# CONFIG (override via environment variables)
# ─────────────────────────────────────────────
DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
ANTHROPIC_API_KEY   = os.environ["ANTHROPIC_API_KEY"]
GOOGLE_TOKEN_JSON   = os.environ.get("GOOGLE_TOKEN_JSON")   # base64 or JSON string of token.json
GOOGLE_CREDS_JSON   = os.environ.get("GOOGLE_CREDS_JSON")   # base64 or JSON string of credentials.json

# Bangkok coordinates
LAT = float(os.environ.get("LATITUDE",  "13.7563"))
LON = float(os.environ.get("LONGITUDE", "100.5018"))
TIMEZONE = "Asia/Bangkok"

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


# ─────────────────────────────────────────────
# WEATHER  (Open-Meteo — free, no key needed)
# ─────────────────────────────────────────────
def get_weather():
    """Return weather summary for today + next 2 days."""
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        f"&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,"
        f"weathercode,windspeed_10m_max"
        f"&hourly=temperature_2m,precipitation_probability,weathercode"
        f"&timezone={TIMEZONE}"
        f"&forecast_days=3"
    )
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()

    daily = data["daily"]
    hourly = data["hourly"]

    # WMO weather code → Thai description
    wmo_map = {
        0: "ท้องฟ้าแจ่มใส ☀️", 1: "แจ่มใสเป็นส่วนมาก 🌤️", 2: "มีเมฆบางส่วน ⛅",
        3: "มีเมฆมาก ☁️", 45: "หมอกลง 🌫️", 48: "หมอกเกาะ 🌫️",
        51: "ฝนปรอย 🌦️", 53: "ฝนปรอยปานกลาง 🌦️", 55: "ฝนปรอยหนัก 🌧️",
        61: "ฝนเบา 🌧️", 63: "ฝนปานกลาง 🌧️", 65: "ฝนหนัก 🌧️",
        80: "ฝนตกเป็นพักๆ 🌦️", 81: "ฝนพักๆ ปานกลาง 🌦️", 82: "ฝนพักๆ หนัก ⛈️",
        95: "พายุฝนฟ้าคะนอง ⛈️", 96: "พายุฝนลูกเห็บ ⛈️", 99: "พายุรุนแรง ⛈️",
    }

    days_summary = []
    today = datetime.date.today()

    for i in range(3):
        date = datetime.date.fromisoformat(daily["time"][i])
        label = ["วันนี้", "พรุ่งนี้", "มะรืนนี้"][i]
        code = daily["weathercode"][i]
        desc = wmo_map.get(code, f"รหัส {code}")
        rain_pct = daily["precipitation_probability_max"][i]
        t_max = daily["temperature_2m_max"][i]
        t_min = daily["temperature_2m_min"][i]
        wind = daily["windspeed_10m_max"][i]

        # Hourly breakdown for today (morning / afternoon / evening)
        hourly_slots = {}
        if i == 0:
            for slot_name, hour_range in [("เช้า(6-9น)", range(6,10)),
                                           ("กลางวัน(11-14น)", range(11,15)),
                                           ("เย็น(17-20น)", range(17,21))]:
                slot_rain = max(
                    hourly["precipitation_probability"][h]
                    for h in hour_range
                    if h < len(hourly["precipitation_probability"])
                )
                hourly_slots[slot_name] = slot_rain

        days_summary.append({
            "label": label,
            "date": date.strftime("%d %b"),
            "description": desc,
            "rain_probability": rain_pct,
            "temp_max": t_max,
            "temp_min": t_min,
            "wind_kmh": wind,
            "hourly_rain": hourly_slots,
        })

    return days_summary


# ─────────────────────────────────────────────
# GOOGLE CALENDAR
# ─────────────────────────────────────────────
def get_calendar_events():
    """Return today's + tomorrow's events from Google Calendar."""
    creds = None

    # Load credentials from environment (GitHub Secrets stores them as JSON strings)
    if GOOGLE_TOKEN_JSON:
        import tempfile, base64
        try:
            token_data = base64.b64decode(GOOGLE_TOKEN_JSON)
        except Exception:
            token_data = GOOGLE_TOKEN_JSON.encode()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
            f.write(token_data)
            token_path = f.name
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise RuntimeError(
                "Google credentials are missing or expired. "
                "Run auth_setup.py locally first to generate token.json, "
                "then add it as GOOGLE_TOKEN_JSON secret."
            )

    service = build("calendar", "v3", credentials=creds)

    bkk_tz = datetime.timezone(datetime.timedelta(hours=7))
    today_start = datetime.datetime.now(bkk_tz).replace(hour=0, minute=0, second=0, microsecond=0)
    two_days_end = today_start + datetime.timedelta(days=2)

    events_result = service.events().list(
        calendarId="primary",
        timeMin=today_start.isoformat(),
        timeMax=two_days_end.isoformat(),
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    raw_events = events_result.get("items", [])
    events_by_day = {"today": [], "tomorrow": []}
    tomorrow_start = today_start + datetime.timedelta(days=1)

    for e in raw_events:
        start = e["start"].get("dateTime", e["start"].get("date"))
        end   = e["end"].get("dateTime",   e["end"].get("date"))

        if "T" in start:
            dt = datetime.datetime.fromisoformat(start)
            time_str = dt.strftime("%H:%M")
        else:
            dt = datetime.datetime.fromisoformat(start)
            time_str = "ทั้งวัน"

        event_info = {
            "title":    e.get("summary", "(ไม่มีชื่อ)"),
            "time":     time_str,
            "location": e.get("location", ""),
            "is_allday": "T" not in start,
        }

        if dt.date() == today_start.date():
            events_by_day["today"].append(event_info)
        else:
            events_by_day["tomorrow"].append(event_info)

    return events_by_day


# ─────────────────────────────────────────────
# CLAUDE — Generate Brief
# ─────────────────────────────────────────────
def generate_brief(weather_data, calendar_data):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    today_str = datetime.datetime.now(
        datetime.timezone(datetime.timedelta(hours=7))
    ).strftime("%A, %d %B %Y")

    prompt = f"""
คุณคือ Personal Executive Assistant ที่พูดภาษาไทย กระชับ และฉลาด

วันนี้คือ {today_str} (Bangkok Time)

--- สภาพอากาศ ---
{json.dumps(weather_data, ensure_ascii=False, indent=2)}

--- ปฏิทินวันนี้ ---
{json.dumps(calendar_data["today"], ensure_ascii=False, indent=2)}

--- ปฏิทินพรุ่งนี้ ---
{json.dumps(calendar_data["tomorrow"], ensure_ascii=False, indent=2)}

กรุณาสร้าง Daily Brief ในรูปแบบนี้:

**🌅 [วันที่] — Daily Brief**

**⚡ ONE SENTENCE SUMMARY**
[ประโยคเดียวที่สรุปวันนี้อย่างฉลาด เช่น "วันนี้ค่อนข้างแน่น ช่วงเช้าเหมาะกับ deep work และควรรีบออกก่อน 8:10 เพราะฝนกับรถติด"]

**🌤️ สภาพอากาศ**
- วันนี้: [อุณหภูมิ สภาพ โอกาสฝน]
- พรุ่งนี้: [อุณหภูมิ สภาพ โอกาสฝน]
- มะรืน: [อุณหภูมิ สภาพ โอกาสฝน]
> ⚠️ [คำเตือนถ้าฝนจะตกช่วงเฉพาะ หรือ skip ถ้าไม่มี]

**📅 Tasks & Events — วันนี้**
[รายการ events ของวันนี้ พร้อมเวลา]
[ถ้าไม่มี event ให้บอกว่า "ไม่มีนัดหมาย — วันว่าง 🎯"]

**📅 Tasks & Events — พรุ่งนี้**
[รายการ events ของพรุ่งนี้]
[ถ้าไม่มี event ให้บอกว่า "ยังไม่มีนัดหมาย"]

**💡 Tips**
[1-2 ข้อแนะนำสั้นๆ ที่ฉลาดและเป็นประโยชน์จริงๆ จากข้อมูลที่มี]

ใช้ภาษาไทยตลอด กระชับ ฉลาด ไม่เยิ่นเย้อ
"""

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


# ─────────────────────────────────────────────
# DISCORD
# ─────────────────────────────────────────────
def send_to_discord(content: str):
    # Discord has 2000 char limit per message — split if needed
    chunks = [content[i:i+1990] for i in range(0, len(content), 1990)]
    for chunk in chunks:
        payload = {"content": chunk}
        r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        r.raise_for_status()
    print("✅ Sent to Discord successfully.")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    print("🌤️  Fetching weather...")
    weather = get_weather()

    print("📅 Fetching calendar...")
    try:
        calendar = get_calendar_events()
    except Exception as e:
        print(f"⚠️  Calendar error: {e}")
        calendar = {"today": [], "tomorrow": []}

    print("🤖 Generating brief with Claude...")
    brief = generate_brief(weather, calendar)

    print("📨 Sending to Discord...")
    send_to_discord(brief)

    print("Done!")
    print("\n--- PREVIEW ---\n")
    print(brief)


if __name__ == "__main__":
    main()