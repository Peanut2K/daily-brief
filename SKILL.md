---
name: daily-brief
description: Executive Daily Brief — ส่งสภาพอากาศ + Google Calendar + AI summary ไปยัง Discord ทุกเช้า
schedule: "0 6 * * *"
---

คุณคือ Personal Executive Assistant

## ขั้นตอน (ทำตามลำดับ)

### 1. ดึง Google Calendar
ใช้ Google Calendar MCP tool ดึง events:
- วันนี้: ตั้งแต่ 00:00 ถึง 23:59 (Bangkok time, UTC+7)
- พรุ่งนี้: วันถัดไปทั้งวัน
เรียง events ตามเวลา บันทึก title, เวลาเริ่ม, เวลาจบ, location (ถ้ามี)

### 2. ดึงสภาพอากาศ
ใช้ bash รัน Python snippet นี้:

```bash
python3 -c "
import urllib.request, json
url = 'https://api.open-meteo.com/v1/forecast?latitude=13.7563&longitude=100.5018&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode,windspeed_10m_max&hourly=precipitation_probability&timezone=Asia%2FBangkok&forecast_days=3'
with urllib.request.urlopen(url) as r:
    print(r.read().decode())
"
```

Parse ผลลัพธ์:
- `daily.weathercode[0,1,2]` → แปลเป็นคำอธิบาย (0=แจ่มใส, 1-2=มีเมฆบ้าง, 3=มีเมฆมาก, 45/48=หมอก, 51-55=ฝนปรอย, 61-65=ฝน, 80-82=ฝนพักๆ, 95+=พายุ)
- `daily.precipitation_probability_max` → % โอกาสฝนแต่ละวัน
- `daily.temperature_2m_max/min` → อุณหภูมิ
- `hourly.precipitation_probability` → index 6-9 = เช้า, 11-14 = กลางวัน, 17-20 = เย็น (ใช้ค่า max ของช่วง)

### 3. ส่ง Discord Embed
รัน Python script นี้ โดยแทนค่าข้อมูลจากขั้นตอน 1-2:

```bash
python3 << 'PYEOF'
import urllib.request, json, datetime, os

WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
if not WEBHOOK:
    print("ERROR: DISCORD_WEBHOOK_URL not set"); exit(1)

# ── แทนค่าเหล่านี้ด้วยข้อมูลจริงที่ดึงมา ──────────────────────────
TODAY_EVENTS = [
    # {"time": "09:00", "title": "Weekly Sync", "location": "Google Meet"},
]
TOMORROW_EVENTS = [
    # {"time": "10:00", "title": "Design Review", "location": ""},
]

WEATHER = [
    # {"label": "วันนี้",    "icon": "🌧️", "desc": "ฝนปานกลาง",  "rain": 75, "tmax": 33, "tmin": 27},
    # {"label": "พรุ่งนี้",  "icon": "⛅",  "desc": "มีเมฆบางส่วน","rain": 30, "tmax": 34, "tmin": 26},
    # {"label": "มะรืนนี้", "icon": "🌧️", "desc": "ฝนเบา",       "rain": 60, "tmax": 32, "tmin": 27},
]

# ชั่วโมงฝน วันนี้ (เช้า/กลางวัน/เย็น เป็น %)
RAIN_MORNING   = 20   # 06-09 น.
RAIN_AFTERNOON = 70   # 11-14 น.
RAIN_EVENING   = 80   # 17-20 น.

ONE_SENTENCE = "สรุปวันนี้จาก AI ที่นี่"
# ─────────────────────────────────────────────────────────────────────

bkk = datetime.timezone(datetime.timedelta(hours=7))
now = datetime.datetime.now(bkk)
date_str = now.strftime("%-d %B %Y").replace(
    "January","มกราคม").replace("February","กุมภาพันธ์").replace("March","มีนาคม"
).replace("April","เมษายน").replace("May","พฤษภาคม").replace("June","มิถุนายน"
).replace("July","กรกฎาคม").replace("August","สิงหาคม").replace("September","กันยายน"
).replace("October","ตุลาคม").replace("November","พฤศจิกายน").replace("December","ธันวาคม")

days_th = ["จันทร์","อังคาร","พุธ","พฤหัส","ศุกร์","เสาร์","อาทิตย์"]
day_th = days_th[now.weekday()]

# Color based on rain probability today
rain_today = WEATHER[0]["rain"] if WEATHER else 0
if rain_today >= 70:
    color = 0x5865F2   # indigo/stormy
elif rain_today >= 40:
    color = 0x57F287   # green/cloudy
else:
    color = 0xFEE75C   # yellow/sunny

# Weather fields
def weather_line(w):
    bar = "█" * (w["rain"] // 10) + "░" * (10 - w["rain"] // 10)
    return f"{w['icon']} **{w['label']}** {w['desc']}\n🌡️ {w['tmax']}°/{w['tmin']}° · 🌧️ {w['rain']}% `{bar}`"

weather_value = "\n\n".join(weather_line(w) for w in WEATHER) if WEATHER else "ไม่สามารถดึงข้อมูลได้"

# Rain hourly breakdown
rain_detail = (
    f"เช้า `{RAIN_MORNING}%` · กลางวัน `{RAIN_AFTERNOON}%` · เย็น `{RAIN_EVENING}%`"
)

# Calendar fields
def fmt_events(events, fallback):
    if not events:
        return fallback
    lines = []
    for e in events:
        loc = f" · 📍{e['location']}" if e.get("location") else ""
        lines.append(f"**{e['time']}** {e['title']}{loc}")
    return "\n".join(lines)

today_value    = fmt_events(TODAY_EVENTS,    "ไม่มีนัดหมาย — วันว่าง 🎯")
tomorrow_value = fmt_events(TOMORROW_EVENTS, "ยังไม่มีนัดหมาย")

payload = {
    "embeds": [{
        "title": f"🌅 Daily Brief · วัน{day_th}ที่ {date_str}",
        "description": f"⚡ **{ONE_SENTENCE}**",
        "color": color,
        "fields": [
            {
                "name": "🌤️ สภาพอากาศ 3 วัน",
                "value": weather_value,
                "inline": False
            },
            {
                "name": "🕐 โอกาสฝนวันนี้",
                "value": rain_detail,
                "inline": False
            },
            {
                "name": f"📅 วันนี้ ({len(TODAY_EVENTS)} นัด)",
                "value": today_value,
                "inline": True
            },
            {
                "name": f"📅 พรุ่งนี้ ({len(TOMORROW_EVENTS)} นัด)",
                "value": tomorrow_value,
                "inline": True
            },
        ],
        "footer": {
            "text": f"Generated {now.strftime('%H:%M')} BKK · Daily Brief by Claude"
        },
        "timestamp": now.isoformat()
    }]
}

data = json.dumps(payload).encode()
req  = urllib.request.Request(WEBHOOK, data=data, headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req) as res:
    print(f"Discord: {res.status}")
PYEOF
```

### 4. สรุป One Sentence
ก่อนรัน Python ในขั้น 3 ให้วิเคราะห์ข้อมูลทั้งหมด แล้วเขียน `ONE_SENTENCE` ที่ฉลาด เช่น:
- ถ้าฝนมาช่วงเย็นและมีนัดนอกออฟฟิศ → "มีนัด 3 อย่าง และฝนจะมาช่วง 17:00 — ควรรีบกลับก่อนหรือนำร่ม"
- ถ้าวันว่าง ฟ้าดี → "วันนี้ไม่มีนัด ท้องฟ้าแจ่มใส — perfect day for deep work หรือออกไปข้างนอก"
- ถ้าแน่นตอนเช้า → "เช้านี้แน่นมาก ถ้ามี deep work ให้ทำก่อน 8:30"

## Environment Variable ที่ต้องการ
- `DISCORD_WEBHOOK_URL` — ตั้งใน Claude Code Desktop: Settings → Environment Variables

## หมายเหตุ
- ใช้ Google Calendar MCP ที่ connected อยู่แล้วใน Desktop app
- ไม่ต้องติดตั้ง library เพิ่ม (ใช้ urllib จาก standard library)
- ถ้า Google Calendar MCP ไม่ตอบสนอง ให้ส่ง Discord โดย note ว่า "Calendar unavailable"
