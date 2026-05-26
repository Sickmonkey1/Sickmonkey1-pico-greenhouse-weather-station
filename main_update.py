from PiicoDev_BME280 import PiicoDev_BME280
from PiicoDev_RV3028 import PiicoDev_RV3028
from PiicoDev_SSD1306 import *
from PiicoDev_Buzzer import PiicoDev_Buzzer
from PiicoDev_Unified import sleep_ms

import time
import network
import socket
import machine
import os

try:
    import urequests as requests
except:
    import requests

from secrets import WIFI_NAME, WIFI_PASSWORD, UPDATE_URL

# =========================
# SYSTEM SETTINGS
# =========================

LOG_INTERVAL_MS = 5000
DAY_ROLLOVER_HOUR = 6

TEMP_HIGH_WARNING = 35.0
TEMP_LOW_WARNING = 5.0
HUMIDITY_HIGH_WARNING = 90.0
HUMIDITY_LOW_WARNING = 35.0

BUZZER_ON = True
BUZZER_VOLUME = 2
BUZZER_MUTED = False

PAGE_CHANGE_MS = 10000
BUZZER_REPEAT_MS = 5000
MAX_HISTORY = 20

WEB_CHECK_INTERVAL_MS = 100

DOWNLOADED_UPDATE_FILE = "main_downloaded.py"
BACKUP_FILE = "main_backup.py"

# =========================
# HARDWARE SETUP
# =========================

sensor = PiicoDev_BME280()
rtc = PiicoDev_RV3028()
display = create_PiicoDev_SSD1306()
buzzer = PiicoDev_Buzzer(volume=BUZZER_VOLUME)

# =========================
# GLOBAL VARIABLES
# =========================

current_file = ""
log = None

start_ms = time.ticks_ms()

temp_min = None
temp_max = None
hum_min = None
hum_max = None
pressure_min = None
pressure_max = None

temp_history = []
hum_history = []
pressure_history = []

page = 0
last_page_change = time.ticks_ms()
last_buzzer_time = 0

latest_timestamp = ""
latest_temp = 0
latest_pressure = 0
latest_humidity = 0
latest_status = "STARTING"
weather_prediction = "Collecting data"

last_sample_ms = time.ticks_ms()
last_update_message = "No update checked yet"

# =========================
# OLED HELPERS
# =========================

def oled_message(line1="", line2="", line3="", line4=""):
    display.fill(0)

    if line1:
        display.text(str(line1), 0, 0, 1)
    if line2:
        display.text(str(line2), 0, 16, 1)
    if line3:
        display.text(str(line3), 0, 32, 1)
    if line4:
        display.text(str(line4), 0, 48, 1)

    display.show()

# =========================
# WIFI SETUP
# =========================

oled_message("Connecting", "WiFi...")

wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.connect(WIFI_NAME, WIFI_PASSWORD)

wifi_timeout = 0

while not wlan.isconnected():
    sleep_ms(500)
    wifi_timeout += 1

    if wifi_timeout > 40:
        oled_message("WiFi Failed", "Check details")
        sleep_ms(3000)
        machine.reset()

ip = wlan.ifconfig()[0]

oled_message("WiFi Connected", ip)
sleep_ms(1500)

# =========================
# WEB SERVER SETUP
# =========================

addr = socket.getaddrinfo("0.0.0.0", 80)[0][-1]
server = socket.socket()
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(addr)
server.listen(1)
server.settimeout(0.05)

# =========================
# BUZZER MELODIES
# =========================

def warning_melody():
    notes = [
        (659, 150), (659, 150), (0, 100),
        (659, 150), (0, 100), (523, 150),
        (659, 150), (784, 300),
    ]

    for freq, duration in notes:
        if freq > 0:
            buzzer.tone(freq, duration)
        sleep_ms(duration)

    buzzer.noTone()


def startup_melody():
    notes = [
        (523, 120),
        (659, 120),
        (784, 160),
        (1046, 220),
    ]

    for freq, duration in notes:
        buzzer.tone(freq, duration)
        sleep_ms(duration)

    buzzer.noTone()


startup_melody()

# =========================
# OTA UPDATE FUNCTIONS
# =========================

def file_exists(filename):
    try:
        os.stat(filename)
        return True
    except:
        return False


def download_update():
    global last_update_message

    try:
        oled_message("Checking", "GitHub update")

        response = requests.get(UPDATE_URL)

        if response.status_code == 200:
            new_code = response.text
            response.close()

            if len(new_code) < 500:
                last_update_message = "Update too small"
                oled_message("Update Failed", "File too small")
                return last_update_message

            if "from secrets import" not in new_code:
                last_update_message = "Update missing secrets"
                oled_message("Update Failed", "Bad file")
                return last_update_message

            with open(DOWNLOADED_UPDATE_FILE, "w") as f:
                f.write(new_code)

            last_update_message = "Update downloaded"
            oled_message("Update Saved", DOWNLOADED_UPDATE_FILE)
            return last_update_message

        else:
            code = response.status_code
            response.close()
            last_update_message = "HTTP error " + str(code)
            oled_message("Update Failed", str(code))
            return last_update_message

    except Exception as e:
        last_update_message = "Update error"
        oled_message("Update Error", "Check WiFi/link")
        return last_update_message


def install_update():
    global last_update_message

    try:
        if not file_exists(DOWNLOADED_UPDATE_FILE):
            last_update_message = "No update file"
            oled_message("Install Failed", "No update file")
            return last_update_message

        if file_exists(BACKUP_FILE):
            try:
                os.remove(BACKUP_FILE)
            except:
                pass

        if file_exists("main.py"):
            os.rename("main.py", BACKUP_FILE)

        os.rename(DOWNLOADED_UPDATE_FILE, "main.py")

        last_update_message = "Installed update"
        oled_message("Update Installed", "Rebooting...")
        sleep_ms(2000)
        machine.reset()

    except Exception as e:
        last_update_message = "Install error"

        try:
            if not file_exists("main.py") and file_exists(BACKUP_FILE):
                os.rename(BACKUP_FILE, "main.py")
                last_update_message = "Restored backup"
        except:
            pass

        oled_message("Install Error", "Backup restored")
        return last_update_message


def reboot_pico():
    oled_message("Rebooting", "Pico W...")
    sleep_ms(1000)
    machine.reset()

# =========================
# DATA FUNCTIONS
# =========================

def add_history(temp, hum, pressure):
    temp_history.append(temp)
    hum_history.append(hum)
    pressure_history.append(pressure)

    if len(temp_history) > MAX_HISTORY:
        temp_history.pop(0)
        hum_history.pop(0)
        pressure_history.pop(0)


def update_weather_prediction():
    if len(pressure_history) < 5:
        return "Collecting pressure trend"

    pressure_change = pressure_history[-1] - pressure_history[0]

    if pressure_change <= -2.0:
        return "Pressure falling - storm/rain possible"
    elif pressure_change >= 2.0:
        return "Pressure rising - weather improving"
    else:
        return "Pressure stable"


def get_log_filename(timestamp):
    hour = int(timestamp[11:13])
    date_part = timestamp[0:10]

    if hour < DAY_ROLLOVER_HOUR:
        year = int(timestamp[0:4])
        month = int(timestamp[5:7])
        day = int(timestamp[8:10])

        previous_day = time.localtime(
            time.mktime((year, month, day, 0, 0, 0, 0, 0)) - 86400
        )

        filename = "{:04d}-{:02d}-{:02d}.csv".format(
            previous_day[0],
            previous_day[1],
            previous_day[2]
        )
    else:
        filename = date_part + ".csv"

    return filename


def update_min_max(tempC, humRH, pres_hPa):
    global temp_min, temp_max
    global hum_min, hum_max
    global pressure_min, pressure_max

    if temp_min is None:
        temp_min = tempC
        temp_max = tempC
        hum_min = humRH
        hum_max = humRH
        pressure_min = pres_hPa
        pressure_max = pres_hPa

    temp_min = min(temp_min, tempC)
    temp_max = max(temp_max, tempC)

    hum_min = min(hum_min, humRH)
    hum_max = max(hum_max, humRH)

    pressure_min = min(pressure_min, pres_hPa)
    pressure_max = max(pressure_max, pres_hPa)


def get_status(tempC, humRH):
    if tempC >= TEMP_HIGH_WARNING:
        return "TEMP HIGH"
    elif tempC <= TEMP_LOW_WARNING:
        return "TEMP LOW"
    elif humRH >= HUMIDITY_HIGH_WARNING:
        return "HUMIDITY HIGH"
    elif humRH <= HUMIDITY_LOW_WARNING:
        return "HUMIDITY LOW"
    else:
        return "OK"


def open_log_if_needed(filename, tempC, humRH, pres_hPa):
    global current_file, log
    global temp_min, temp_max
    global hum_min, hum_max
    global pressure_min, pressure_max

    if filename != current_file:
        if log is not None:
            log.close()

        current_file = filename
        log = open(current_file, "a")

        log.write(
            "Timestamp,"
            "TemperatureC,"
            "PressurehPa,"
            "HumidityRH,"
            "TempMin,"
            "TempMax,"
            "HumMin,"
            "HumMax,"
            "PressureMin,"
            "PressureMax,"
            "Status,"
            "Prediction\n"
        )
        log.flush()

        temp_min = tempC
        temp_max = tempC
        hum_min = humRH
        hum_max = humRH
        pressure_min = pres_hPa
        pressure_max = pres_hPa


def write_log(timestamp, tempC, pres_hPa, humRH, status, prediction):
    if log is not None:
        log.write(
            f"{timestamp},"
            f"{tempC:.2f},"
            f"{pres_hPa:.2f},"
            f"{humRH:.2f},"
            f"{temp_min:.2f},"
            f"{temp_max:.2f},"
            f"{hum_min:.2f},"
            f"{hum_max:.2f},"
            f"{pressure_min:.2f},"
            f"{pressure_max:.2f},"
            f"{status},"
            f"{prediction}\n"
        )
        log.flush()

# =========================
# SVG GRAPH FUNCTION
# =========================

def make_svg_graph(data, min_val, max_val, colour):
    if len(data) < 2:
        return ""

    width = 260
    height = 70
    points = ""

    for i, value in enumerate(data):
        x = int(i * width / (len(data) - 1))

        if max_val == min_val:
            y = height // 2
        else:
            y = int(height - ((value - min_val) / (max_val - min_val)) * height)

        points += str(x) + "," + str(y) + " "

    return f"""
<svg width="260" height="70" viewBox="0 0 260 70">
<polyline points="{points}" fill="none" stroke="{colour}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
"""

# =========================
# WEBPAGE
# =========================

def safe_value(value, decimals=1):
    if value is None:
        return "--"

    return f"{value:.{decimals}f}"


def make_webpage():
    status_colour = "#35e58a"

    if latest_status != "OK":
        status_colour = "#ff5c5c"

    uptime_seconds = time.ticks_diff(time.ticks_ms(), start_ms) // 1000
    uptime_minutes = uptime_seconds // 60

    temp_graph = make_svg_graph(temp_history, min(temp_history), max(temp_history), "#ff6b6b") if temp_history else ""
    hum_graph = make_svg_graph(hum_history, min(hum_history), max(hum_history), "#4dabf7") if hum_history else ""
    pressure_graph = make_svg_graph(pressure_history, min(pressure_history), max(pressure_history), "#845ef7") if pressure_history else ""

    update_file_status = "Yes" if file_exists(DOWNLOADED_UPDATE_FILE) else "No"

    return f"""<!DOCTYPE html>
<html>
<head>
<title>Greenhouse Monitor</title>
<meta http-equiv="refresh" content="20">
<meta name="viewport" content="width=device-width, initial-scale=1.0">

<style>
* {{
    box-sizing: border-box;
}}

body {{
    margin: 0;
    font-family: Arial, sans-serif;
    background: linear-gradient(135deg, #dcecff, #7f9fc4);
    color: #15192e;
    display: flex;
    justify-content: center;
    padding: 20px;
}}

.card {{
    width: 380px;
    background: rgba(255,255,255,0.94);
    border-radius: 28px;
    padding: 24px;
    box-shadow: 0 20px 45px rgba(40,60,90,0.25);
    text-align: center;
}}

.title {{
    font-size: 25px;
    font-weight: 700;
}}

.time {{
    font-size: 13px;
    color: #6b7280;
    margin-bottom: 16px;
}}

.main-temp {{
    font-size: 64px;
    font-weight: 300;
    margin-top: 8px;
}}

.subtext {{
    font-size: 14px;
    color: #6b7280;
}}

.grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
    margin-top: 18px;
}}

.box {{
    background: #f4f8ff;
    border-radius: 18px;
    padding: 12px;
}}

.label {{
    font-size: 12px;
    color: #6b7280;
}}

.value {{
    font-size: 20px;
    font-weight: 600;
}}

.status {{
    margin-top: 18px;
    padding: 12px;
    border-radius: 18px;
    background: {status_colour};
    color: white;
    font-weight: 700;
}}

.graphbox {{
    margin-top: 16px;
    background: #f4f8ff;
    border-radius: 18px;
    padding: 12px;
}}

.graph-title {{
    font-weight: 700;
    margin-bottom: 6px;
}}

.button {{
    display: block;
    margin: 10px auto;
    padding: 12px;
    width: 90%;
    border: none;
    border-radius: 16px;
    background: #15192e;
    color: white;
    text-decoration: none;
    font-weight: 700;
    font-size: 15px;
    cursor: pointer;
}}

.button:active {{
    transform: scale(0.98);
}}

.button-muted {{
    background: #ff5c5c;
}}

.button-good {{
    background: #35e58a;
}}

.button-blue {{
    background: #4dabf7;
}}

.button-purple {{
    background: #845ef7;
}}

.button-orange {{
    background: #ff922b;
}}

.message {{
    margin-top: 12px;
    font-size: 13px;
    font-weight: 700;
    color: #15192e;
    min-height: 18px;
}}

.footer {{
    margin-top: 14px;
    font-size: 11px;
    color: #6b7280;
}}
</style>
</head>

<body>
<div class="card">

<div class="title">Greenhouse Monitor</div>
<div class="time">{latest_timestamp}</div>

<div class="main-temp">{latest_temp:.1f}&deg;</div>
<div class="subtext">Temperature</div>

<div class="grid">
    <div class="box">
        <div class="label">Humidity</div>
        <div class="value">{latest_humidity:.1f}%</div>
    </div>

    <div class="box">
        <div class="label">Pressure</div>
        <div class="value">{latest_pressure:.1f}</div>
    </div>

    <div class="box">
        <div class="label">Min Temp</div>
        <div class="value">{safe_value(temp_min)}&deg;C</div>
    </div>

    <div class="box">
        <div class="label">Max Temp</div>
        <div class="value">{safe_value(temp_max)}&deg;C</div>
    </div>

    <div class="box">
        <div class="label">Min Humidity</div>
        <div class="value">{safe_value(hum_min)}%</div>
    </div>

    <div class="box">
        <div class="label">Max Humidity</div>
        <div class="value">{safe_value(hum_max)}%</div>
    </div>
</div>

<div class="status">{latest_status}</div>

<div class="graphbox">
    <div class="graph-title">Temperature Trend</div>
    {temp_graph}
</div>

<div class="graphbox">
    <div class="graph-title">Humidity Trend</div>
    {hum_graph}
</div>

<div class="graphbox">
    <div class="graph-title">Pressure Trend</div>
    {pressure_graph}
</div>

<div class="graphbox">
    <div class="graph-title">Weather Prediction</div>
    <p>{weather_prediction}</p>
</div>

<div class="graphbox">
    <div class="graph-title">System Stats</div>
    <p>IP: {ip}</p>
    <p>Uptime: {uptime_minutes} minutes</p>
    <p>Log File: {current_file}</p>
    <p>Buzzer Muted: {BUZZER_MUTED}</p>
</div>

<div class="graphbox">
    <div class="graph-title">OTA Update</div>
    <p>Downloaded Update: {update_file_status}</p>
    <p>Last Message: {last_update_message}</p>
</div>

<button class="button button-muted" onclick="sendCommand('/mute')">Mute Buzzer</button>
<button class="button button-good" onclick="sendCommand('/unmute')">Unmute Buzzer</button>
<button class="button" onclick="sendCommand('/reset')">Reset Min/Max</button>

<button class="button button-blue" onclick="sendCommand('/checkupdate')">Check / Download Update</button>
<button class="button button-purple" onclick="sendCommand('/installupdate')">Install Update</button>
<button class="button button-orange" onclick="sendCommand('/reboot')">Reboot Pico</button>

<div class="message" id="message"></div>

<div class="footer">Auto refreshes every 20 seconds</div>

</div>

<script>
function sendCommand(path) {{
    document.getElementById("message").innerHTML = "Sending command...";

    fetch(path)
    .then(response => response.text())
    .then(data => {{
        document.getElementById("message").innerHTML = data;

        setTimeout(() => {{
            location.reload();
        }}, 800);
    }})
    .catch(error => {{
        document.getElementById("message").innerHTML = "Command failed";
        console.log(error);
    }});
}}
</script>

</body>
</html>
"""

# =========================
# WEB RESPONSE HELPERS
# =========================

def send_text_response(client, message):
    client.send("HTTP/1.1 200 OK\r\n")
    client.send("Content-Type: text/plain\r\n")
    client.send("Connection: close\r\n\r\n")
    client.send(message)
    client.close()


def send_html_response(client, html):
    client.send("HTTP/1.1 200 OK\r\n")
    client.send("Content-Type: text/html\r\n")
    client.send("Connection: close\r\n\r\n")
    client.sendall(html)
    client.close()

# =========================
# WEB REQUEST HANDLER
# =========================

def check_web_request():
    global BUZZER_MUTED
    global temp_min, temp_max
    global hum_min, hum_max
    global pressure_min, pressure_max
    global last_update_message

    try:
        client, addr = server.accept()
        request = client.recv(1024).decode()

        if "GET /mute" in request:
            BUZZER_MUTED = True
            send_text_response(client, "Buzzer muted")
            return

        elif "GET /unmute" in request:
            BUZZER_MUTED = False
            send_text_response(client, "Buzzer unmuted")
            return

        elif "GET /reset" in request:
            temp_min = latest_temp
            temp_max = latest_temp
            hum_min = latest_humidity
            hum_max = latest_humidity
            pressure_min = latest_pressure
            pressure_max = latest_pressure

            send_text_response(client, "Min/max reset")
            return

        elif "GET /checkupdate" in request:
            message = download_update()
            send_text_response(client, message)
            return

        elif "GET /installupdate" in request:
            send_text_response(client, "Installing update and rebooting")
            sleep_ms(500)
            install_update()
            return

        elif "GET /reboot" in request:
            send_text_response(client, "Rebooting Pico")
            sleep_ms(500)
            reboot_pico()
            return

        else:
            html = make_webpage()
            send_html_response(client, html)
            return

    except OSError:
        pass

    except Exception as e:
        try:
            client.close()
        except:
            pass

# =========================
# OLED DISPLAY
# =========================

def update_oled(tempC, humRH, pres_hPa, status, time_part):
    global page, last_page_change

    now_ms = time.ticks_ms()

    if time.ticks_diff(now_ms, last_page_change) >= PAGE_CHANGE_MS:
        page += 1

        if page > 4:
            page = 0

        last_page_change = now_ms

    display.fill(0)

    if page == 0:
        display.text("LIVE DATA", 0, 0, 1)
        display.text(f"T {tempC:.1f} C", 0, 14, 1)
        display.text(f"H {humRH:.1f} %RH", 0, 28, 1)
        display.text(f"P {pres_hPa:.1f}", 0, 42, 1)
        display.text(time_part, 72, 56, 1)

    elif page == 1:
        display.text("DAILY MIN/MAX", 0, 0, 1)
        display.text(f"Tmin {temp_min:.1f}C", 0, 14, 1)
        display.text(f"Tmax {temp_max:.1f}C", 0, 28, 1)
        display.text(f"Hmin {hum_min:.1f}%", 0, 42, 1)
        display.text(f"Hmax {hum_max:.1f}%", 0, 56, 1)

    elif page == 2:
        display.text("STATUS", 0, 0, 1)
        display.text(status, 0, 14, 1)
        display.text(f"Pmin {pressure_min:.1f}", 0, 28, 1)
        display.text(f"Pmax {pressure_max:.1f}", 0, 42, 1)
        display.text(time_part, 72, 56, 1)

    elif page == 3:
        display.text("WIFI DASHBOARD", 0, 0, 1)
        display.text(ip, 0, 16, 1)
        display.text("Open browser", 0, 34, 1)

    elif page == 4:
        display.text("OTA UPDATE", 0, 0, 1)
        display.text("GitHub ready", 0, 16, 1)
        display.text("Use web page", 0, 34, 1)

    display.show()

# =========================
# SENSOR SAMPLE LOOP
# =========================

def take_sensor_sample():
    global latest_timestamp
    global latest_temp
    global latest_pressure
    global latest_humidity
    global latest_status
    global weather_prediction
    global last_buzzer_time

    try:
        tempC, presPa, humRH = sensor.values()
        pres_hPa = presPa / 100

        timestamp = rtc.timestamp()
        time_part = timestamp[11:19]

        latest_timestamp = timestamp
        latest_temp = tempC
        latest_pressure = pres_hPa
        latest_humidity = humRH

        add_history(tempC, humRH, pres_hPa)
        weather_prediction = update_weather_prediction()

        filename = get_log_filename(timestamp)
        open_log_if_needed(filename, tempC, humRH, pres_hPa)

        update_min_max(tempC, humRH, pres_hPa)

        status = get_status(tempC, humRH)
        latest_status = status

        now_ms = time.ticks_ms()

        if BUZZER_ON and not BUZZER_MUTED and status != "OK":
            if time.ticks_diff(now_ms, last_buzzer_time) >= BUZZER_REPEAT_MS:
                warning_melody()
                last_buzzer_time = now_ms
        else:
            buzzer.noTone()

        write_log(timestamp, tempC, pres_hPa, humRH, status, weather_prediction)

        print(
            f"{timestamp}, "
            f"{tempC:.2f} C, "
            f"{pres_hPa:.2f} hPa, "
            f"{humRH:.2f} %RH, "
            f"{status}, "
            f"Muted: {BUZZER_MUTED}, "
            f"IP: {ip}"
        )

        update_oled(tempC, humRH, pres_hPa, status, time_part)

    except Exception as e:
        latest_status = "SENSOR ERROR"
        oled_message("Sensor Error", "Check wiring")
        print("Sensor error:", e)

# =========================
# MAIN LOOP
# =========================

take_sensor_sample()
last_sample_ms = time.ticks_ms()

while True:
    check_web_request()

    now_ms = time.ticks_ms()

    if time.ticks_diff(now_ms, last_sample_ms) >= LOG_INTERVAL_MS:
        take_sensor_sample()
        last_sample_ms = now_ms

    sleep_ms(WEB_CHECK_INTERVAL_MS)
