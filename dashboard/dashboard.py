"""
EPG317E Capstone Project — Solar Tracker Dashboard
--------------------------------------------------
A real-time monitoring and control dashboard for an ESP32-based solar tracking system.
Features:
- Two-way MQTT telemetry (Ingestion & Control)
- SQLite persistent data storage
- Dynamic analog gauges & historical trend charts
- Interactive time-range filtering

Dependencies:
    pip install panel paho-mqtt hvplot pandas bokeh sqlite3

Execution:
    panel serve dashboard.py --show
"""

import math
import queue
import logging
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, Callable, Any

import pandas as pd
import panel as pn
import hvplot.pandas
import paho.mqtt.client as mqtt
from bokeh.plotting import figure

# ─────────────────────────────────────────────────────────────
# SYSTEM INITIALIZATION & LOGGING
# ─────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

pn.extension("tabulator", sizing_mode="stretch_width", template="fast")

# ─────────────────────────────────────────────────────────────
# UI CONFIGURATION & THEME
# ─────────────────────────────────────────────────────────────
DARK_BG = "#0a0e27"
ACCENT_CYAN = "#00d9ff"
ACCENT_LIME = "#00ff41"
ACCENT_ORANGE = "#ff6b35"
ACCENT_YELLOW = "#ffcc00"

GRADIENT_HEADER = "linear-gradient(135deg, #0a0e27 0%, #1a1f3a 100%)"
GRADIENT_CARD = "linear-gradient(135deg, #0f1535 0%, #1a1f3a 100%)"

PALETTE = {
    "temperature": ACCENT_ORANGE,
    "humidity": ACCENT_CYAN,
    "lux": ACCENT_YELLOW,
    "pan": ACCENT_CYAN,
    "tilt": ACCENT_LIME,
    "battery": "#ff00ff"
}

# ─────────────────────────────────────────────────────────────
# NETWORK & TELEMETRY CONFIGURATION
# ─────────────────────────────────────────────────────────────
BROKER = "broker.hivemq.com"
PORT = 1883
TEAM_ID = "TheCyberAlchemists"
BASE = f"epg317e/solar/{TEAM_ID}"

DB_FILE = "solar_data.db"
MESSAGE_QUEUE_TIMEOUT = 0.1
MQTT_KEEPALIVE = 60

# Updated topics to match Capstone Specifications exactly
SENSOR_TOPICS = {
    "temperature": f"{BASE}/sensors/temperature",
    "humidity": f"{BASE}/sensors/humidity",
    "lux": f"{BASE}/sensors/lux",
    "battery": f"{BASE}/sensors/battery",
    "servo_pan": f"{BASE}/actuators/servo_pan",
    "servo_tilt": f"{BASE}/actuators/servo_tilt",
}

CONTROL_TOPICS = {
    "tracking_mode": f"{BASE}/control/tracking_mode",
    "servo_pan": f"{BASE}/control/servo_pan",
    "servo_tilt": f"{BASE}/control/servo_tilt",
    "led": f"{BASE}/control/led",
    "buzzer": f"{BASE}/control/buzzer",
}

# ─────────────────────────────────────────────────────────────
# DATABASE SETUP (SQLite)
# ─────────────────────────────────────────────────────────────
def init_db():
    """Initialises the SQLite database schema if it doesn't exist."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS telemetry (
            timestamp DATETIME PRIMARY KEY,
            temperature REAL,
            humidity REAL,
            lux REAL,
            servo_pan REAL,
            servo_tilt REAL
        )
    ''')
    conn.commit()
    conn.close()
    logger.info("SQLite Database initialized successfully.")

init_db()

# ─────────────────────────────────────────────────────────────
# CUSTOM CSS STYLES
# ─────────────────────────────────────────────────────────────
CUSTOM_CSS = """
:root { --accent-cyan: #00d9ff; --text-primary: #e0e6ff; }
body { background: linear-gradient(135deg, #0a0e27 0%, #1a1f3a 50%, #0f1535 100%) !important; font-family: 'Segoe UI', monospace !important; }
.pn-container { background: transparent !important; }
.pn-card { background: linear-gradient(135deg, #0f1535 0%, #1a1f3a 100%) !important; border: 1px solid rgba(0, 217, 255, 0.3) !important; border-radius: 12px !important; box-shadow: 0 0 20px rgba(0, 217, 255, 0.1) !important; }
.bk-root input, .bk-root select, .bk-root textarea { background-color: rgba(15, 21, 53, 0.7) !important; border: 1px solid rgba(0, 217, 255, 0.3) !important; color: var(--text-primary) !important; }
.bk-slider-parent { color: var(--accent-cyan) !important; }
"""
pn.config.raw_css = [CUSTOM_CSS]

# ─────────────────────────────────────────────────────────────
# DATA MANAGEMENT CLASS
# ─────────────────────────────────────────────────────────────
class SensorState:
    """Manages live state for gauges and handles SQLite interactions."""
    def __init__(self):
        self.live: Dict[str, Any] = {
            "temperature": 0.0, "humidity": 0.0, "lux": 0.0,
            "servo_pan": 90.0, "servo_tilt": 90.0, "battery": 0.0,
            "last_seen": "waiting…", "connected": False,
        }
    
    def update_live(self, key: str, value: float) -> None:
        self.live[key] = value

    def commit_to_db(self, timestamp: str) -> None:
        """Writes the current snapshot of live data to SQLite."""
        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("""
                INSERT INTO telemetry (timestamp, temperature, humidity, lux, servo_pan, servo_tilt)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (timestamp, self.live["temperature"], self.live["humidity"], 
                  self.live["lux"], self.live["servo_pan"], self.live["servo_tilt"]))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Database insert error: {e}")

    def fetch_historical_data(self, hours: int) -> pd.DataFrame:
        """Queries SQLite for data within the selected time window."""
        try:
            conn = sqlite3.connect(DB_FILE)
            cutoff_time = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
            query = f"SELECT * FROM telemetry WHERE timestamp >= '{cutoff_time}' ORDER BY timestamp ASC"
            df = pd.read_sql_query(query, conn, parse_dates=['timestamp'])
            conn.close()
            return df
        except Exception as e:
            logger.error(f"Database query error: {e}")
            return pd.DataFrame()

sensor_state = SensorState()
message_queue: queue.Queue = queue.Queue()

# ─────────────────────────────────────────────────────────────
# UI COMPONENTS: CONTROL PANEL (PUBLISHING TO ESP32)
# ─────────────────────────────────────────────────────────────
control_switch_mode = pn.widgets.Switch(name="Auto-Tracking Mode", value=True)
control_pan = pn.widgets.IntSlider(name="Manual Pan Angle", start=0, end=180, step=1, value=90)
control_tilt = pn.widgets.IntSlider(name="Manual Tilt Angle", start=0, end=180, step=1, value=90)
btn_led = pn.widgets.Button(name="💡 TOGGLE LED", button_type="primary", sizing_mode="stretch_width")
btn_buzzer = pn.widgets.Button(name="🔊 SOUND BUZZER", button_type="warning", sizing_mode="stretch_width")

def publish_command(topic_key: str, payload: str) -> None:
    """Helper to publish commands over MQTT."""
    if sensor_state.live["connected"]:
        client.publish(CONTROL_TOPICS[topic_key], str(payload))
        logger.info(f"Command Sent -> {topic_key}: {payload}")

# Attach callbacks to UI inputs
control_switch_mode.param.watch(lambda e: publish_command("tracking_mode", "AUTO" if e.new else "MANUAL"), 'value')
control_pan.param.watch(lambda e: publish_command("servo_pan", str(e.new)), 'value_throttled')
control_tilt.param.watch(lambda e: publish_command("servo_tilt", str(e.new)), 'value_throttled')
btn_led.on_click(lambda event: publish_command("led", "TOGGLE"))
btn_buzzer.on_click(lambda event: publish_command("buzzer", "TRIGGER"))

# ─────────────────────────────────────────────────────────────
# UI COMPONENTS: VISUALIZATIONS
# ─────────────────────────────────────────────────────────────
def create_analog_gauge(value: float, max_value: float, color: str) -> figure:
    p = figure(width=320, height=180, toolbar_location=None, tools="", min_border=10, margin=(5, 5, 5, 5))
    p.background_fill_color = None; p.border_fill_color = None; p.outline_line_color = None
    p.grid.visible = False; p.axis.visible = False
    
    angle = (value / max_value) * math.pi if max_value > 0 else 0
    
    # Draw arcs
    angles_bg = [i * (math.pi / 50) for i in range(51)]
    p.line([0.75 * math.cos(a) for a in angles_bg], [0.75 * math.sin(a) for a in angles_bg], line_width=14, color=ACCENT_CYAN, alpha=0.15)
    
    if angle > 0:
        angles_val = [i * (angle / 25) for i in range(26)]
        p.line([0.75 * math.cos(a) for a in angles_val], [0.75 * math.sin(a) for a in angles_val], line_width=14, color=color, alpha=0.95)
    
    p.circle(x=0, y=0, size=24, fill_color=color, line_color=color, alpha=0.85)
    p.x_range.start, p.x_range.end = -1.05, 1.05
    p.y_range.start, p.y_range.end = -0.25, 1.05
    return p

# Gauges and Digital Readouts
gauge_temp = pn.pane.Bokeh(create_analog_gauge(0, 100, PALETTE["temperature"]), sizing_mode="stretch_width", height=180)
gauge_hum = pn.pane.Bokeh(create_analog_gauge(0, 100, PALETTE["humidity"]), sizing_mode="stretch_width", height=180)
gauge_pan = pn.pane.Bokeh(create_analog_gauge(0, 180, PALETTE["pan"]), sizing_mode="stretch_width", height=180)
gauge_tilt = pn.pane.Bokeh(create_analog_gauge(0, 180, PALETTE["tilt"]), sizing_mode="stretch_width", height=180)

txt_temp = pn.pane.HTML("<h2 style='text-align:center; margin:0; padding-top:10px; color:#ff6b35;'>0.0 °C</h2>")
txt_hum = pn.pane.HTML("<h2 style='text-align:center; margin:0; padding-top:10px; color:#00d9ff;'>0.0 %</h2>")
txt_pan = pn.pane.HTML("<h2 style='text-align:center; margin:0; padding-top:10px; color:#00d9ff;'>0 °</h2>")
txt_tilt = pn.pane.HTML("<h2 style='text-align:center; margin:0; padding-top:10px; color:#00ff41;'>0 °</h2>")

def make_card(title, color, text_pane, gauge_pane):
    return pn.Card(pn.Column(text_pane, gauge_pane), title=title, sizing_mode="stretch_width", styles={"background": GRADIENT_CARD, "border": f"2px solid {color}", "padding": "10px"})

# Time Range Filter & Charts
time_filter = pn.widgets.RadioButtonGroup(
    name='Historical Range', 
    options={'1 Hour': 1, '6 Hours': 6, '24 Hours': 24, '7 Days': 168}, 
    value=1, button_type='primary', sizing_mode="stretch_width"
)

chart_env = pn.pane.HoloViews(sizing_mode="stretch_width", height=300)
chart_track = pn.pane.HoloViews(sizing_mode="stretch_width", height=300)
display_conn = pn.widgets.StaticText(name="SYSTEM STATUS", value="🔄 Connecting…", sizing_mode="stretch_width")

# ─────────────────────────────────────────────────────────────
# UI REFRESH LOGIC
# ─────────────────────────────────────────────────────────────
def update_ui_components():
    """Updates Gauges and SQLite-backed Charts."""
    # 1. Update Live Gauges
    temp, hum = sensor_state.live["temperature"], sensor_state.live["humidity"]
    pan, tilt = sensor_state.live["servo_pan"], sensor_state.live["servo_tilt"]
    
    txt_temp.object = f"<h2 style='text-align:center; margin:0; padding-top:10px; color:{PALETTE['temperature']};'>{temp:.1f} °C</h2>"
    txt_hum.object = f"<h2 style='text-align:center; margin:0; padding-top:10px; color:{PALETTE['humidity']};'>{hum:.1f} %</h2>"
    txt_pan.object = f"<h2 style='text-align:center; margin:0; padding-top:10px; color:{PALETTE['pan']};'>{pan:.0f} °</h2>"
    txt_tilt.object = f"<h2 style='text-align:center; margin:0; padding-top:10px; color:{PALETTE['tilt']};'>{tilt:.0f} °</h2>"
    
    gauge_temp.object = create_analog_gauge(temp, 100, PALETTE["temperature"])
    gauge_hum.object = create_analog_gauge(hum, 100, PALETTE["humidity"])
    gauge_pan.object = create_analog_gauge(pan, 180, PALETTE["pan"])
    gauge_tilt.object = create_analog_gauge(tilt, 180, PALETTE["tilt"])

    # 2. Update Charts from SQLite Database
    df = sensor_state.fetch_historical_data(hours=time_filter.value)
    if len(df) > 1:
        chart_env.object = df.hvplot.line(x="timestamp", y=["temperature", "humidity"], title="Environment Trends", color=[PALETTE["temperature"], PALETTE["humidity"]], line_width=2, responsive=True, height=300)
        chart_track.object = df.hvplot.step(x="timestamp", y=["servo_pan", "servo_tilt"], title="Solar Tracking History", color=[PALETTE["pan"], PALETTE["tilt"]], line_width=2, responsive=True, height=300)

# Bind the chart refresh to the time filter so it updates instantly when clicked
time_filter.param.watch(lambda e: update_ui_components(), 'value')

# ─────────────────────────────────────────────────────────────
# MQTT COMMUNICATION PROTOCOLS
# ─────────────────────────────────────────────────────────────
try:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
except AttributeError:
    client = mqtt.Client()

def on_connect(c, userdata, flags, rc, properties=None):
    if rc == 0:
        sensor_state.update_live("connected", True)
        display_conn.value = f"⚡ ONLINE - Connected to {BROKER}"
        for topic in SENSOR_TOPICS.values():
            c.subscribe(topic)
    else:
        sensor_state.update_live("connected", False)

def on_message(c, userdata, msg):
    try:
        message_queue.put((msg.topic, msg.payload.decode().strip()), block=False)
    except Exception:
        pass

client.on_connect = on_connect
client.on_message = on_message

threading.Thread(target=lambda: client.connect(BROKER, PORT, MQTT_KEEPALIVE) or client.loop_forever(), daemon=True).start()

# ─────────────────────────────────────────────────────────────
# MESSAGE PROCESSING LOOP
# ─────────────────────────────────────────────────────────────
def process_messages():
    try:
        while True:
            topic, payload = message_queue.get(timeout=MESSAGE_QUEUE_TIMEOUT)
            val = float(payload)
            
            # Map topic back to state keys
            for key, t in SENSOR_TOPICS.items():
                if topic == t:
                    sensor_state.update_live(key, val)
            
            # Trigger Database Commit & UI Update when the 'last' sensor in a batch arrives 
            # (Assuming tilt is reported last by your ESP32 sequence)
            if topic == SENSOR_TOPICS["servo_tilt"]:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                sensor_state.commit_to_db(timestamp)
                update_ui_components()

    except queue.Empty:
        pass
    except ValueError:
        pass

pn.state.add_periodic_callback(process_messages, period=250)

# ─────────────────────────────────────────────────────────────
# LAYOUT ASSEMBLY
# ─────────────────────────────────────────────────────────────
main_content = pn.Column(
    pn.Row(pn.pane.Markdown("# ☀️ SOLAR TRACKER COMMAND CENTER", styles={"color": ACCENT_CYAN, "text-align": "center", "margin": "0"}), styles={"background": GRADIENT_HEADER, "padding": "20px", "border-radius": "12px"}),
    display_conn,
    pn.pane.Markdown("**LIVE SENSOR FEED**", styles={"color": ACCENT_CYAN, "font-weight": "700"}),
    pn.GridBox(make_card("TEMPERATURE", PALETTE["temperature"], txt_temp, gauge_temp), make_card("HUMIDITY", PALETTE["humidity"], txt_hum, gauge_hum), ncols=2, sizing_mode="stretch_width"),
    pn.pane.Markdown("**PANEL ORIENTATION**", styles={"color": ACCENT_CYAN, "font-weight": "700"}),
    pn.GridBox(make_card("PAN ANGLE", PALETTE["pan"], txt_pan, gauge_pan), make_card("TILT ANGLE", PALETTE["tilt"], txt_tilt, gauge_tilt), ncols=2, sizing_mode="stretch_width"),
    pn.pane.Markdown("**DATABASE HISTORICAL TRENDS**", styles={"color": ACCENT_CYAN, "font-weight": "700"}),
    time_filter,
    pn.Column(chart_env, chart_track, sizing_mode="stretch_width"),
    sizing_mode="stretch_width", styles={"background": DARK_BG, "padding": "30px"}
)

sidebar_content = pn.Column(
    pn.Card(
        pn.Column(
            pn.pane.Markdown("**⚙️ TRACKING OVERRIDE**"),
            control_switch_mode,
            pn.layout.Divider(),
            pn.pane.Markdown("**🎯 MANUAL POSITIONING**"),
            control_pan, control_tilt,
            pn.layout.Divider(),
            pn.pane.Markdown("**🚨 ALERTS & SIGNALS**"),
            btn_led, btn_buzzer
        ),
        title="CONTROL PANEL", styles={"background": GRADIENT_CARD, "border": f"1px solid {ACCENT_CYAN}"}
    )
)

dashboard = pn.template.FastListTemplate(
    title="IoT Solar Tracker", accent_base_color=ACCENT_CYAN, header_background=DARK_BG,
    theme="dark", main_max_width="1600px", sidebar=[sidebar_content], main=[main_content]
)
dashboard.show()
