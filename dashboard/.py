"""
EPG317E — Solar Tracker Dashboard
Live display + Control Panel

Requirements:
    pip install panel paho-mqtt hvplot pandas

Run (do NOT use the VS Code play button):
    panel serve dashboard.py --show
"""

import panel as pn
import paho.mqtt.client as mqtt
import pandas as pd
import hvplot.pandas
import threading
from datetime import datetime
from collections import deque

pn.extension("tabulator", sizing_mode="stretch_width", template="fast")

# ─────────────────────────────────────────────────────────────
# CONFIGURATION  ← change these two lines to match your team
# ─────────────────────────────────────────────────────────────
BROKER  = "broker.hivemq.com"
PORT    = 1883
TEAM_ID = "team01"          # e.g. "team03"
BASE    = f"epg317e/solar/{TEAM_ID}"

# Topics the ESP32 publishes sensor readings to
SENSOR_TOPICS = {
    "temperature" : f"{BASE}/sensors/temperature",
    "humidity"    : f"{BASE}/sensors/humidity",
    "lux"         : f"{BASE}/sensors/lux",
    "battery"     : f"{BASE}/sensors/battery",
    "servo_pan"   : f"{BASE}/actuators/servo_pan",
    "servo_tilt"  : f"{BASE}/actuators/servo_tilt",
    "tracking"    : f"{BASE}/control/tracking_mode",
}

# Topics the dashboard publishes commands to
COMMAND_TOPICS = {
    "tracking"  : f"{BASE}/control/tracking_mode",
    "led"       : f"{BASE}/control/led",
    "buzzer"    : f"{BASE}/control/buzzer",
    "servo_pan" : f"{BASE}/actuators/servo_pan",
    "servo_tilt": f"{BASE}/actuators/servo_tilt",
    "threshold" : f"{BASE}/control/lux_threshold",
}


# ─────────────────────────────────────────────────────────────
# ROLLING HISTORY  — keeps the last 20 readings for each sensor
# Works like the tips/CO2 DataFrames from the class examples,
# but filled live from MQTT instead of from a CSV file.
# ─────────────────────────────────────────────────────────────
MAX_READINGS = 20

readings = {
    "time"        : deque(maxlen=MAX_READINGS),
    "temperature" : deque(maxlen=MAX_READINGS),
    "humidity"    : deque(maxlen=MAX_READINGS),
    "lux"         : deque(maxlen=MAX_READINGS),
    "battery"     : deque(maxlen=MAX_READINGS),
}

def readings_to_dataframe():
    """Convert the rolling buffers to a pandas DataFrame for hvplot charts."""
    return pd.DataFrame({
        "time"        : list(readings["time"]),
        "temperature" : list(readings["temperature"]),
        "humidity"    : list(readings["humidity"]),
        "lux"         : list(readings["lux"]),
        "battery"     : list(readings["battery"]),
    })


# ─────────────────────────────────────────────────────────────
# LIVE STATE  — always holds the most recent value from the ESP32
# ─────────────────────────────────────────────────────────────
live = {
    "temperature" : 0.0,
    "humidity"    : 0.0,
    "lux"         : 0.0,
    "battery"     : 0.0,
    "servo_pan"   : 90.0,
    "servo_tilt"  : 45.0,
    "tracking"    : "unknown",
    "last_seen"   : "waiting…",
    "connected"   : False,
}


# ─────────────────────────────────────────────────────────────
# COLOUR SCHEME  — one colour per sensor, used consistently
# across cards, charts, and the MQTT log
# ─────────────────────────────────────────────────────────────
PALETTE = {
    "temperature" : "#0F6E56",   # deep teal
    "humidity"    : "#185FA5",   # ocean blue
    "lux"         : "#BA7517",   # warm amber
    "battery"     : "#993556",   # berry pink
}


# ─────────────────────────────────────────────────────────────
# SENSOR TREND CARDS
# Each card shows: current value, % change since last reading,
# and a mini sparkline chart — built with pn.indicators.Trend
# wrapped in a styled pn.Card (same pattern as the CO2 class example).
# ─────────────────────────────────────────────────────────────
def make_trend_card(label, color, chart_style="line"):
    """
    Build one sensor card.
    Returns the Trend widget (so we can update it later)
    and the Card container (so we can place it in the layout).
    """
    trend = pn.indicators.Trend(
        name=label,
        data={"x": [0], "y": [0]},
        value=0,
        value_change=0,
        plot_type=chart_style,
        plot_color=color,
        height=180,
        sizing_mode="stretch_width",
    )
    card = pn.Card(
        trend,
        hide_header=True,
        sizing_mode="stretch_width",
        styles={
            "border"        : f"2px solid {color}",
            "border-radius" : "12px",
            "box-shadow"    : f"0 4px 16px {color}33",
            "padding"       : "10px",
        },
    )
    return trend, card

trend_temp, card_temp = make_trend_card("🌡 Temperature (°C)", PALETTE["temperature"], "line")
trend_hum,  card_hum  = make_trend_card("💧 Humidity (%)",     PALETTE["humidity"],    "area")
trend_lux,  card_lux  = make_trend_card("☀️ Light (lux)",      PALETTE["lux"],         "bar")
trend_bat,  card_bat  = make_trend_card("🔋 Battery (V)",      PALETTE["battery"],     "step")


# ─────────────────────────────────────────────────────────────
# STATUS DISPLAYS  — servo angles and connection info
# ─────────────────────────────────────────────────────────────
display_pan  = pn.indicators.Number(name="Pan angle (°)",  value=0, format="{value:.0f}", font_size="28pt")
display_tilt = pn.indicators.Number(name="Tilt angle (°)", value=0, format="{value:.0f}", font_size="28pt")

display_mode = pn.widgets.StaticText(name="Tracking mode", value="—")
display_time = pn.widgets.StaticText(name="Last reading",  value="Waiting for ESP32…")
display_conn = pn.widgets.StaticText(name="Connection",    value="Connecting to broker…")


# ─────────────────────────────────────────────────────────────
# LIVE CHARTS  — last 20 readings as hvplot line/area charts
# Same .hvplot.line() pattern used in the CO2 & tips class examples,
# but the DataFrame is rebuilt from live MQTT data each time.
# ─────────────────────────────────────────────────────────────
live_chart_temp = pn.pane.HoloViews(sizing_mode="stretch_width", height=200)
live_chart_lux  = pn.pane.HoloViews(sizing_mode="stretch_width", height=200)

def refresh_trend_card(trend_widget, sensor_key):
    """Update a Trend card's sparkline and value from the latest readings buffer."""
    buf = list(readings[sensor_key])
    if len(buf) < 2:
        return
    current  = buf[-1]
    previous = buf[-2]
    pct_change = (current - previous) / abs(previous) if previous != 0 else 0.0
    trend_widget.data         = {"x": list(range(len(buf))), "y": buf}
    trend_widget.value        = round(current, 2)
    trend_widget.value_change = round(pct_change, 4)

def refresh_live_charts():
    """Redraw the temperature and lux hvplot charts from the current readings buffer."""
    df = readings_to_dataframe()
    if len(df) < 2:
        return
    live_chart_temp.object = df.hvplot.line(
        x="time", y="temperature",
        title="Temperature over time",
        xlabel="Time", ylabel="°C",
        color=PALETTE["temperature"], line_width=2,
        responsive=True, height=200,
    )
    live_chart_lux.object = df.hvplot.area(
        x="time", y="lux",
        title="Light intensity over time",
        xlabel="Time", ylabel="lux",
        color=PALETTE["lux"], alpha=0.5, line_width=2,
        responsive=True, height=200,
    )


# ─────────────────────────────────────────────────────────────
# SENSOR SUMMARY TABLE
# A Tabulator table that shows all sensors in one place.
# Created once and updated in-place via .value = new_df
# (same pattern as update_tables() in the solar performance class example).
# ─────────────────────────────────────────────────────────────
summary_table = pn.widgets.Tabulator(
    pd.DataFrame({
        "Sensor"      : ["Temperature", "Humidity", "Light", "Battery", "Pan", "Tilt", "Tracking"],
        "Reading"     : ["—"] * 7,
        "Unit"        : ["°C", "%", "lux", "V", "°", "°", "—"],
        "Last updated": ["—"] * 7,
    }),
    show_index=False,
    disabled=True,
    widths={"Sensor": 120, "Reading": 90, "Unit": 55, "Last updated": 100},
    sizing_mode="stretch_width",
    height=280,
)

def refresh_summary_table():
    """Push the latest live values into the summary table."""
    now = live["last_seen"]
    summary_table.value = pd.DataFrame({
        "Sensor"      : ["Temperature", "Humidity", "Light", "Battery", "Pan", "Tilt", "Tracking"],
        "Reading"     : [
            f"{live['temperature']:.1f}",
            f"{live['humidity']:.0f}",
            f"{live['lux']:.0f}",
            f"{live['battery']:.2f}",
            f"{live['servo_pan']:.0f}",
            f"{live['servo_tilt']:.0f}",
            live["tracking"].upper(),
        ],
        "Unit"        : ["°C", "%", "lux", "V", "°", "°", "—"],
        "Last updated": [now] * 7,
    })


# ─────────────────────────────────────────────────────────────
# MQTT LOG  — scrolling live feed of incoming messages
# and outgoing commands, inspired by the SensorAlertSystem
# event log from the param/panel class example (section 4.2).
# ─────────────────────────────────────────────────────────────
incoming_log = pn.widgets.TextAreaInput(
    name="📡 Incoming sensor data",
    value="Waiting for data from ESP32...\n",
    height=200,
    disabled=True,
    sizing_mode="stretch_width",
)

outgoing_log = pn.widgets.TextAreaInput(
    name="📤 Commands sent to ESP32",
    value="No commands sent yet.\n",
    height=130,
    disabled=True,
    sizing_mode="stretch_width",
)

MAX_LOG_LINES = 50

def log_incoming(entry):
    """Add a new line at the top of the incoming log."""
    lines = incoming_log.value.splitlines()
    incoming_log.value = "\n".join([entry] + lines[:MAX_LOG_LINES]) + "\n"

def log_outgoing(entry):
    """Add a new line at the top of the outgoing log."""
    lines = outgoing_log.value.splitlines()
    outgoing_log.value = "\n".join([entry] + lines[:MAX_LOG_LINES]) + "\n"

btn_clear_logs = pn.widgets.Button(
    name="🗑 Clear logs", button_type="danger", width=130
)

def on_clear_logs(event):
    incoming_log.value = "Logs cleared.\n"
    outgoing_log.value = "Logs cleared.\n"

btn_clear_logs.on_click(on_clear_logs)


# ─────────────────────────────────────────────────────────────
# CONTROL WIDGETS  — buttons and sliders in the sidebar
# ─────────────────────────────────────────────────────────────
btn_tracking = pn.widgets.Toggle(
    name="🔄 Auto-tracking: OFF", value=False,
    button_type="success", width=210,
)
btn_led = pn.widgets.Toggle(
    name="💡 LED: OFF", value=False,
    button_type="default", width=210,
)
btn_buzzer = pn.widgets.Button(
    name="🔔 Trigger Buzzer", button_type="warning", width=210,
)

# Servo sliders — defined before pn.bind() below
sl_pan = pn.widgets.IntSlider(
    name="Pan angle (°)", start=0, end=180, value=90, step=1,
)
sl_tilt = pn.widgets.IntSlider(
    name="Tilt angle (°)", start=0, end=90, value=45, step=1,
)
sl_threshold = pn.widgets.IntSlider(
    name="Lux threshold", start=100, end=2000, value=500, step=10,
)

btn_send_servo = pn.widgets.Button(
    name="📡 Send to ESP32", button_type="primary", width=210,
)
btn_send_threshold = pn.widgets.Button(
    name="📡 Send to ESP32", button_type="primary", width=210,
)

# Live servo angle preview using pn.bind()
# Same pattern as bound_plot = pn.bind(...) in the solar performance monitor class example.
# The Markdown text re-renders automatically whenever either slider moves.
def servo_angle_preview(pan, tilt):
    return pn.pane.Markdown(
        f"*Will send →* pan **{pan}°** | tilt **{tilt}°**",
        sizing_mode="stretch_width",
    )

servo_preview_pane = pn.bind(servo_angle_preview, pan=sl_pan, tilt=sl_tilt)


# ─────────────────────────────────────────────────────────────
# MQTT CLIENT SETUP
# Uses CallbackAPIVersion.VERSION2 (paho-mqtt ≥ 2.0) to avoid
# the deprecation warning on newer Python installs.
# Falls back to the old API if running an older version of paho.
# ─────────────────────────────────────────────────────────────
try:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
except AttributeError:
    client = mqtt.Client()

def on_connect(c, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        live["connected"] = True
        display_conn.value = f"✅ Connected to {BROKER}"
        for topic in SENSOR_TOPICS.values():
            c.subscribe(topic)
    else:
        display_conn.value = f"❌ Connection failed (code {reason_code})"

def on_disconnect(c, userdata, disconnect_flags=None, reason_code=None, properties=None):
    live["connected"] = False
    display_conn.value = "⚠️ Disconnected — retrying…"

def on_message(c, userdata, msg):
    """
    Called every time a new MQTT message arrives from the ESP32.
    Updates the shared live state, then refreshes all dashboard widgets.
    """
    try:
        payload = msg.payload.decode().strip()
        topic   = msg.topic

        # Update the matching live state value
        if topic == SENSOR_TOPICS["temperature"]:
            live["temperature"] = float(payload)
        elif topic == SENSOR_TOPICS["humidity"]:
            live["humidity"] = float(payload)
        elif topic == SENSOR_TOPICS["lux"]:
            live["lux"] = float(payload)
        elif topic == SENSOR_TOPICS["battery"]:
            live["battery"] = float(payload)
        elif topic == SENSOR_TOPICS["servo_pan"]:
            live["servo_pan"] = float(payload)
            display_pan.value = float(payload)
        elif topic == SENSOR_TOPICS["servo_tilt"]:
            live["servo_tilt"] = float(payload)
            display_tilt.value = float(payload)
        elif topic == SENSOR_TOPICS["tracking"]:
            live["tracking"] = payload
            display_mode.value = payload.upper()

        # Timestamp and log the incoming message
        live["last_seen"] = datetime.now().strftime("%H:%M:%S")
        display_time.value = live["last_seen"]
        sensor_name = topic.split("/")[-1]
        log_incoming(f"[{live['last_seen']}]  {sensor_name}: {payload}")

        # On each temperature reading, update all charts and the summary table.
        # Temperature is used as the "sync" signal because the ESP32 sends all
        # sensors together — temperature always arrives last in the sequence.
        if topic == SENSOR_TOPICS["temperature"]:
            readings["time"].append(live["last_seen"])
            readings["temperature"].append(live["temperature"])
            readings["humidity"].append(live["humidity"])
            readings["lux"].append(live["lux"])
            readings["battery"].append(live["battery"])

            refresh_trend_card(trend_temp, "temperature")
            refresh_trend_card(trend_hum,  "humidity")
            refresh_trend_card(trend_lux,  "lux")
            refresh_trend_card(trend_bat,  "battery")
            refresh_live_charts()
            refresh_summary_table()

    except Exception as e:
        print(f"[MQTT] Could not parse message: {e}")

client.on_connect    = on_connect
client.on_disconnect = on_disconnect
client.on_message    = on_message

def connect_to_broker():
    """Start the MQTT connection in a background thread so the dashboard stays responsive."""
    try:
        client.connect(BROKER, PORT, keepalive=60)
        client.loop_forever()
    except Exception as e:
        display_conn.value = f"❌ MQTT error: {e}"

broker_thread = threading.Thread(target=connect_to_broker, daemon=True)
broker_thread.start()


# ─────────────────────────────────────────────────────────────
# CONTROL CALLBACKS
# Using .param.watch() and .on_click() — same as section 6
# of the param/panel class notes (standalone widgets + events).
# ─────────────────────────────────────────────────────────────
def send_command(topic, payload):
    """Publish a command to the ESP32. Warns if not connected."""
    if live["connected"]:
        client.publish(topic, str(payload), qos=1)
    else:
        print("[Dashboard] Not connected — command not sent")

def on_tracking_toggle(event):
    val = "ON" if event.new else "OFF"
    send_command(COMMAND_TOPICS["tracking"], val)
    btn_tracking.name = f"🔄 Auto-tracking: {val}"
    log_outgoing(f"[{datetime.now().strftime('%H:%M:%S')}]  tracking mode → {val}")

def on_led_toggle(event):
    val = "ON" if event.new else "OFF"
    send_command(COMMAND_TOPICS["led"], val)
    btn_led.name = f"💡 LED: {val}"
    log_outgoing(f"[{datetime.now().strftime('%H:%M:%S')}]  LED → {val}")

def on_buzzer_click(event):
    send_command(COMMAND_TOPICS["buzzer"], "TRIGGER")
    log_outgoing(f"[{datetime.now().strftime('%H:%M:%S')}]  buzzer → TRIGGER")

def on_send_servo(event):
    send_command(COMMAND_TOPICS["servo_pan"],  sl_pan.value)
    send_command(COMMAND_TOPICS["servo_tilt"], sl_tilt.value)
    log_outgoing(f"[{datetime.now().strftime('%H:%M:%S')}]  servo → pan={sl_pan.value}°  tilt={sl_tilt.value}°")

def on_send_threshold(event):
    send_command(COMMAND_TOPICS["threshold"], sl_threshold.value)
    log_outgoing(f"[{datetime.now().strftime('%H:%M:%S')}]  lux threshold → {sl_threshold.value} lx")

btn_tracking.param.watch(on_tracking_toggle, "value")
btn_led.param.watch(on_led_toggle, "value")
btn_buzzer.on_click(on_buzzer_click)
btn_send_servo.on_click(on_send_servo)
btn_send_threshold.on_click(on_send_threshold)


# ─────────────────────────────────────────────────────────────
# LAYOUT — main content area
# ─────────────────────────────────────────────────────────────
main_content = pn.Column(
    pn.pane.Markdown("## Live Sensor Readings"),
    pn.GridBox(
        card_temp, card_hum, card_lux, card_bat,
        ncols=4,
        sizing_mode="stretch_width",
        styles={"gap": "16px"},
    ),

    pn.pane.Markdown("## Solar Panel Orientation"),
    pn.GridBox(display_pan, display_tilt, ncols=2),
    pn.Row(
        pn.Column(pn.pane.Markdown("**Tracking mode**"), display_mode),
        pn.Column(pn.pane.Markdown("**Last reading**"),  display_time),
        pn.Column(pn.pane.Markdown("**Broker status**"), display_conn),
    ),

    pn.pane.Markdown("## All Sensors at a Glance"),
    summary_table,

    pn.pane.Markdown("## Trends — last 20 readings"),
    pn.Row(live_chart_temp, live_chart_lux),
)


# ─────────────────────────────────────────────────────────────
# LAYOUT — sidebar (controls + logs)
# Using pn.Card sections — same structure as the sidebar in
# the solar performance monitor class example.
# ─────────────────────────────────────────────────────────────
sidebar_content = [
    pn.Column(
        pn.Card(
            btn_tracking,
            btn_led,
            btn_buzzer,
            title="⚡ Tracking & Actuators",
            collapsed=False,
            sizing_mode="stretch_width",
        ),
        pn.Spacer(height=10),
        pn.Card(
            pn.pane.Markdown("Drag to adjust, then click send."),
            sl_pan,
            sl_tilt,
            servo_preview_pane,
            btn_send_servo,
            title="🎮 Manual Servo Control",
            collapsed=False,
            sizing_mode="stretch_width",
        ),
        pn.Spacer(height=10),
        pn.Card(
            pn.pane.Markdown("Auto-tracking activates when light exceeds this value."),
            sl_threshold,
            btn_send_threshold,
            title="🔆 Light Sensitivity",
            collapsed=False,
            sizing_mode="stretch_width",
        ),
        pn.Spacer(height=10),
        pn.Card(
            incoming_log,
            outgoing_log,
            btn_clear_logs,
            title="📋 MQTT Log",
            collapsed=False,
            sizing_mode="stretch_width",
        ),
    )
]


# ─────────────────────────────────────────────────────────────
# DASHBOARD TEMPLATE
# ─────────────────────────────────────────────────────────────
dashboard = pn.template.FastListTemplate(
    title="☀️Solar Tracker Dashboard",
    accent_base_color="#0F6E56",
    header_background="#0F6E56",
    theme="dark",
    theme_toggle=True,
    main_max_width="1400px",
    sidebar=sidebar_content,
    main=[main_content],
)

dashboard.show()
