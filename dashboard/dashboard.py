"""
EPG317E — Solar Tracker Dashboard
System Module: Real-time Telemetry, Actuator Control, and Historical Analysis
Target Environment: PythonAnywhere (WSGI Deployment)
"""

import panel as pn
import paho.mqtt.client as mqtt
import pandas as pd
import hvplot.pandas
import threading
import sqlite3
import ssl
from datetime import datetime, timedelta
from collections import deque

# Initialize Panel extension and configure global template constraints
pn.extension("tabulator", sizing_mode="stretch_width", template="fast")

# ─────────────────────────────────────────────────────────────
# SYSTEM CONFIGURATION
# ─────────────────────────────────────────────────────────────
# HiveMQ Cloud broker credentials and TLS parameters
BROKER    = "609a213d79034184b1befa784bd08e2a.s1.eu.hivemq.cloud"
PORT      = 8883
MQTT_USER = "TheCyberAlchemists"
MQTT_PASS = "rWJ6zm@9f5zUCEp"

# System identifiers (Must correlate with ESP32 firmware configuration)
TEAM_ID   = "team01"          
BASE      = f"epg317e/solar/{TEAM_ID}"
DB_FILE   = "solar_data.db"

# MQTT topic definitions for incoming sensor telemetry
SENSOR_TOPICS = {
    "temperature" : f"{BASE}/sensors/temperature",
    "humidity"    : f"{BASE}/sensors/humidity",
    "lux"         : f"{BASE}/sensors/lux",
    "battery"     : f"{BASE}/sensors/battery",
    "servo_pan"   : f"{BASE}/actuators/servo_pan",
    "servo_tilt"  : f"{BASE}/actuators/servo_tilt",
    "tracking"    : f"{BASE}/control/tracking_mode",
}

# MQTT topic definitions for outgoing actuator control commands
COMMAND_TOPICS = {
    "tracking"  : f"{BASE}/control/tracking_mode",
    "led"       : f"{BASE}/control/led",
    "buzzer"    : f"{BASE}/control/buzzer",
    "servo_pan" : f"{BASE}/actuators/servo_pan",
    "servo_tilt": f"{BASE}/actuators/servo_tilt",
    "threshold" : f"{BASE}/control/lux_threshold",
}


# ─────────────────────────────────────────────────────────────
# DATABASE ARCHITECTURE
# ─────────────────────────────────────────────────────────────
def init_db():
    """Initializes the SQLite database schema for persistent data storage."""
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS sensor_data (
                timestamp DATETIME,
                temperature REAL,
                humidity REAL,
                lux REAL,
                battery REAL
            )
        ''')
        conn.commit()

init_db()


# ─────────────────────────────────────────────────────────────
# IN-MEMORY DATA BUFFERS
# ─────────────────────────────────────────────────────────────
# Fixed-length rolling buffers for real-time visualization optimization
MAX_READINGS = 20

readings = {
    "time"        : deque(maxlen=MAX_READINGS),
    "temperature" : deque(maxlen=MAX_READINGS),
    "humidity"    : deque(maxlen=MAX_READINGS),
    "lux"         : deque(maxlen=MAX_READINGS),
    "battery"     : deque(maxlen=MAX_READINGS),
}

def readings_to_dataframe():
    """Casts in-memory queues to a pandas DataFrame for HoloViews integration."""
    return pd.DataFrame({
        "time"        : list(readings["time"]),
        "temperature" : list(readings["temperature"]),
        "humidity"    : list(readings["humidity"]),
        "lux"         : list(readings["lux"]),
        "battery"     : list(readings["battery"]),
    })


# ─────────────────────────────────────────────────────────────
# GLOBAL STATE MANAGEMENT
# ─────────────────────────────────────────────────────────────
# State dictionary maintaining current telemetry and connectivity status
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
# UI CONFIGURATION: STYLING & PALETTES
# ─────────────────────────────────────────────────────────────
PALETTE = {
    "temperature" : "#0F6E56",   
    "humidity"    : "#185FA5",   
    "lux"         : "#BA7517",   
    "battery"     : "#993556",   
}


# ─────────────────────────────────────────────────────────────
# UI COMPONENTS: TELEMETRY INDICATORS
# ─────────────────────────────────────────────────────────────
def make_trend_card(label, color, chart_style="line"):
    """Constructs a composite UI card featuring a dynamic trend indicator."""
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
# UI COMPONENTS: STATIC METRICS
# ─────────────────────────────────────────────────────────────
display_pan  = pn.indicators.Number(name="Pan angle (°)",  value=0, format="{value:.0f}", font_size="28pt")
display_tilt = pn.indicators.Number(name="Tilt angle (°)", value=0, format="{value:.0f}", font_size="28pt")

display_mode = pn.widgets.StaticText(name="Tracking mode", value="—")
display_time = pn.widgets.StaticText(name="Last reading",  value="Waiting for ESP32…")
display_conn = pn.widgets.StaticText(name="Connection",    value="Connecting to broker…")


# ─────────────────────────────────────────────────────────────
# UI COMPONENTS: REAL-TIME VISUALIZATIONS
# ─────────────────────────────────────────────────────────────
live_chart_temp = pn.pane.HoloViews(sizing_mode="stretch_width", height=200)
live_chart_lux  = pn.pane.HoloViews(sizing_mode="stretch_width", height=200)

def refresh_trend_card(trend_widget, sensor_key):
    """Calculates relative rate of change and updates the corresponding trend UI."""
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
    """Updates HoloViews panes with the latest in-memory buffer arrays."""
    df = readings_to_dataframe()
    if len(df) < 2:
        return
    live_chart_temp.object = df.hvplot.line(
        x="time", y="temperature",
        title="Live Temperature",
        xlabel="Time", ylabel="°C",
        color=PALETTE["temperature"], line_width=2,
        responsive=True, height=200,
    )
    live_chart_lux.object = df.hvplot.area(
        x="time", y="lux",
        title="Live Light Intensity",
        xlabel="Time", ylabel="lux",
        color=PALETTE["lux"], alpha=0.5, line_width=2,
        responsive=True, height=200,
    )


# ─────────────────────────────────────────────────────────────
# UI COMPONENTS: HISTORICAL DATA ANALYSIS
# ─────────────────────────────────────────────────────────────
time_range_selector = pn.widgets.RadioButtonGroup(
    name='Historical Range',
    options={'1 Hour': 1, '6 Hours': 6, '24 Hours': 24, '7 Days': 168},
    button_type='success',
    value=1
)

historical_chart_pane = pn.Column(sizing_mode="stretch_width")

def refresh_historical_charts(event=None):
    """Executes a parameterized SQLite query and renders the resulting historical plots."""
    hours = time_range_selector.value
    cutoff_time = datetime.now() - timedelta(hours=hours)
    
    try:
        with sqlite3.connect(DB_FILE) as conn:
            query = f"SELECT * FROM sensor_data WHERE timestamp >= '{cutoff_time.strftime('%Y-%m-%d %H:%M:%S')}'"
            df = pd.read_sql_query(query, conn, parse_dates=['timestamp'])
            
        if len(df) < 2:
            historical_chart_pane.objects = [
                pn.pane.Markdown(f"⏳ *Insufficient historical data collected for the requested {hours}-hour temporal range.*")
            ]
            return

        hist_temp = df.hvplot.line(
            x="timestamp", y="temperature",
            title=f"Historical Temperature ({hours}h)",
            xlabel="Time", ylabel="°C",
            color=PALETTE["temperature"], line_width=2,
            responsive=True, height=250,
        )
        hist_lux = df.hvplot.area(
            x="timestamp", y="lux",
            title=f"Historical Light Intensity ({hours}h)",
            xlabel="Time", ylabel="lux",
            color=PALETTE["lux"], alpha=0.5, line_width=2,
            responsive=True, height=250,
        )
        
        historical_chart_pane.objects = [pn.Row(hist_temp, hist_lux)]
        
    except Exception as e:
        print(f"[SQLite] Query execution failed: {e}")

# Bind historical refresh function to the time selector widget
time_range_selector.param.watch(refresh_historical_charts, 'value')


# ─────────────────────────────────────────────────────────────
# UI COMPONENTS: DATA TABULATION
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
    """Populates the Tabulator widget with the most recent global state values."""
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
# UI COMPONENTS: SYSTEM LOGGING
# ─────────────────────────────────────────────────────────────
incoming_log = pn.widgets.TextAreaInput(
    name="📡 Incoming sensor data",
    value="Awaiting payload from edge device...\n",
    height=200,
    disabled=True,
    sizing_mode="stretch_width",
)

outgoing_log = pn.widgets.TextAreaInput(
    name="📤 Commands sent to ESP32",
    value="Command queue empty.\n",
    height=130,
    disabled=True,
    sizing_mode="stretch_width",
)

MAX_LOG_LINES = 50

def log_incoming(entry):
    lines = incoming_log.value.splitlines()
    incoming_log.value = "\n".join([entry] + lines[:MAX_LOG_LINES]) + "\n"

def log_outgoing(entry):
    lines = outgoing_log.value.splitlines()
    outgoing_log.value = "\n".join([entry] + lines[:MAX_LOG_LINES]) + "\n"

btn_clear_logs = pn.widgets.Button(
    name="🗑 Clear logs", button_type="danger", width=130
)

def on_clear_logs(event):
    incoming_log.value = "Logs purged.\n"
    outgoing_log.value = "Logs purged.\n"

btn_clear_logs.on_click(on_clear_logs)


# ─────────────────────────────────────────────────────────────
# UI COMPONENTS: ACTUATOR CONTROLS
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

def servo_angle_preview(pan, tilt):
    """Generates a dynamic markdown string reflecting proposed servo parameters."""
    return pn.pane.Markdown(
        f"*Transmission preview →* pan **{pan}°** | tilt **{tilt}°**",
        sizing_mode="stretch_width",
    )

servo_preview_pane = pn.bind(servo_angle_preview, pan=sl_pan, tilt=sl_tilt)


# ─────────────────────────────────────────────────────────────
# MQTT NETWORK PROTOCOL HANDLERS
# ─────────────────────────────────────────────────────────────
# API Version handling for backward compatibility with paho-mqtt distributions
try:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
except AttributeError:
    client = mqtt.Client()

def on_connect(c, userdata, flags, reason_code, properties=None):
    """Callback invoked upon successful broker authentication and connection."""
    if reason_code == 0:
        live["connected"] = True
        display_conn.value = f"✅ Connected to HiveMQ Cloud"
        
        # Subscribe to required sensor topics post-connection
        for topic in SENSOR_TOPICS.values():
            c.subscribe(topic)
    else:
        display_conn.value = f"❌ Connection failed (code {reason_code})"

def on_disconnect(c, userdata, disconnect_flags=None, reason_code=None, properties=None):
    """Callback invoked upon broker disconnection."""
    live["connected"] = False
    display_conn.value = "⚠️ Disconnected — attempting protocol retry…"

def on_message(c, userdata, msg):
    """Primary routing callback for processing incoming topic payloads."""
    try:
        payload = msg.payload.decode().strip()
        topic   = msg.topic

        # Update global state corresponding to the received topic
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

        live["last_seen"] = datetime.now().strftime("%H:%M:%S")
        display_time.value = live["last_seen"]
        
        sensor_name = topic.split("/")[-1]
        log_incoming(f"[{live['last_seen']}]  {sensor_name}: {payload}")

        # Execute data storage logic exclusively on temperature payload arrival
        # to prevent redundant row insertion within the database.
        if topic == SENSOR_TOPICS["temperature"]:
            
            # Step 1: Append telemetry to volatile memory buffers
            readings["time"].append(live["last_seen"])
            readings["temperature"].append(live["temperature"])
            readings["humidity"].append(live["humidity"])
            readings["lux"].append(live["lux"])
            readings["battery"].append(live["battery"])

            # Step 2: Execute non-volatile persistent storage insertion
            try:
                with sqlite3.connect(DB_FILE) as conn:
                    c = conn.cursor()
                    c.execute(
                        "INSERT INTO sensor_data (timestamp, temperature, humidity, lux, battery) VALUES (?, ?, ?, ?, ?)",
                        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), live["temperature"], live["humidity"], live["lux"], live["battery"])
                    )
                    conn.commit()
            except Exception as db_err:
                print(f"[SQLite] Insertion fault detected: {db_err}")

            # Step 3: Trigger UI component rendering cycles
            refresh_trend_card(trend_temp, "temperature")
            refresh_trend_card(trend_hum,  "humidity")
            refresh_trend_card(trend_lux,  "lux")
            refresh_trend_card(trend_bat,  "battery")
            refresh_live_charts()
            refresh_historical_charts() 
            refresh_summary_table()

    except Exception as e:
        print(f"[MQTT] Payload parsing exception: {e}")

# Register callback functions with the MQTT client instance
client.on_connect    = on_connect
client.on_disconnect = on_disconnect
client.on_message    = on_message

def connect_to_broker():
    """Initializes secure MQTT client connection on an isolated thread."""
    try:
        # Enforce authentication credentials and TLS client protocols
        client.username_pw_set(MQTT_USER, MQTT_PASS)
        client.tls_set(tls_version=ssl.PROTOCOL_TLS_CLIENT)
        
        client.connect(BROKER, PORT, keepalive=60)
        client.loop_forever()
    except Exception as e:
        display_conn.value = f"❌ MQTT client exception: {e}"

# Dispatch the MQTT network loop to a daemon thread
broker_thread = threading.Thread(target=connect_to_broker, daemon=True)
broker_thread.start()


# ─────────────────────────────────────────────────────────────
# CONTROL EVENT HANDLERS
# ─────────────────────────────────────────────────────────────
def send_command(topic, payload):
    """Transmits structured payload data to designated MQTT topics."""
    if live["connected"]:
        client.publish(topic, str(payload), qos=1)
    else:
        print("[Dashboard] Transmission aborted: Client disconnected.")

def on_tracking_toggle(event):
    val = "ON" if event.new else "OFF"
    send_command(COMMAND_TOPICS["tracking"], val)
    btn_tracking.name = f"🔄 Auto-tracking: {val}"
    log_outgoing(f"[{datetime.now().strftime('%H:%M:%S')}]  tracking_mode → {val}")

def on_led_toggle(event):
    val = "ON" if event.new else "OFF"
    send_command(COMMAND_TOPICS["led"], val)
    btn_led.name = f"💡 LED: {val}"
    log_outgoing(f"[{datetime.now().strftime('%H:%M:%S')}]  led_state → {val}")

def on_buzzer_click(event):
    send_command(COMMAND_TOPICS["buzzer"], "TRIGGER")
    log_outgoing(f"[{datetime.now().strftime('%H:%M:%S')}]  buzzer_actuation → TRIGGER")

def on_send_servo(event):
    send_command(COMMAND_TOPICS["servo_pan"],  sl_pan.value)
    send_command(COMMAND_TOPICS["servo_tilt"], sl_tilt.value)
    log_outgoing(f"[{datetime.now().strftime('%H:%M:%S')}]  servo_vector → pan={sl_pan.value}°, tilt={sl_tilt.value}°")

def on_send_threshold(event):
    send_command(COMMAND_TOPICS["threshold"], sl_threshold.value)
    log_outgoing(f"[{datetime.now().strftime('%H:%M:%S')}]  lux_threshold → {sl_threshold.value} lx")

# Bind control event functions to UI widget parameters
btn_tracking.param.watch(on_tracking_toggle, "value")
btn_led.param.watch(on_led_toggle, "value")
btn_buzzer.on_click(on_buzzer_click)
btn_send_servo.on_click(on_send_servo)
btn_send_threshold.on_click(on_send_threshold)


# ─────────────────────────────────────────────────────────────
# LAYOUT STRUCTURE & COMPOSITION
# ─────────────────────────────────────────────────────────────

# Instantiate the primary content column (Central Workspace)
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

    pn.pane.Markdown("## Live Trends — last 20 readings"),
    pn.Row(live_chart_temp, live_chart_lux),
    
    pn.pane.Markdown("## Historical Data"),
    pn.Row(pn.pane.Markdown("**Select Range:**", margin=(10, 10, 0, 0)), time_range_selector),
    historical_chart_pane,
)

# Instantiate the auxiliary content column (Sidebar Controls)
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
            pn.pane.Markdown("Configure vector parameters, then execute transmission."),
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
            pn.pane.Markdown("Define environmental threshold for autonomous tracking engagement."),
            sl_threshold,
            btn_send_threshold,
            title="🔆 Light Sensitivity Configuration",
            collapsed=False,
            sizing_mode="stretch_width",
        ),
        pn.Spacer(height=10),
        pn.Card(
            incoming_log,
            outgoing_log,
            btn_clear_logs,
            title="📋 MQTT Transmission Log",
            collapsed=False,
            sizing_mode="stretch_width",
        ),
    )
]

# Execute initial database query to populate static historical panes
refresh_historical_charts()

# Combine layout structures into the final Panel Template
dashboard = pn.template.FastListTemplate(
    title="☀️ Solar Tracker Dashboard",
    accent_base_color="#0F6E56",
    header_background="#0F6E56",
    theme="dark",
    theme_toggle=True,
    main_max_width="1400px",
    sidebar=sidebar_content,
    main=[main_content],
)

# Expose the application object for WSGI server deployment
dashboard.servable()
