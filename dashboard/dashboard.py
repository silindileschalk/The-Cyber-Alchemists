"""
Solar Tracker Dashboard & Telemetry System
------------------------------------------
A real-time monitoring and control dashboard for an ESP32-based solar tracking system.
Features include live MQTT telemetry ingestion, dynamic analog gauges, rolling data
trend visualizations, and system status logging.

Dependencies:
    pip install panel paho-mqtt hvplot pandas bokeh

Execution:
    panel serve dashboard.py --show
"""

import math
import queue
import logging
import threading
from datetime import datetime
from collections import deque
from typing import Optional, Dict, Callable, Any

import pandas as pd
import panel as pn
import hvplot.pandas
import paho.mqtt.client as mqtt
from bokeh.plotting import figure

# ─────────────────────────────────────────────────────────────
# SYSTEM INITIALIZATION & LOGGING
# ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize the Panel template globally
pn.extension("tabulator", sizing_mode="stretch_width", template="fast")

# ─────────────────────────────────────────────────────────────
# UI CONFIGURATION & THEME
# ─────────────────────────────────────────────────────────────
DARK_BG = "#0a0e27"
DARKER_BG = "#050810"
ACCENT_CYAN = "#00d9ff"
ACCENT_LIME = "#00ff41"

GRADIENT_HEADER = "linear-gradient(135deg, #0a0e27 0%, #1a1f3a 100%)"
GRADIENT_CARD = "linear-gradient(135deg, #0f1535 0%, #1a1f3a 100%)"
GRADIENT_CHART = "linear-gradient(180deg, #0a0e27 0%, #15213e 100%)"

PALETTE = {
    "temperature": "#ff6b35",
    "humidity": "#00d9ff",
    "lux": "#00ff41",
    "servo": "#ff00ff",
}

# ─────────────────────────────────────────────────────────────
# NETWORK & TELEMETRY CONFIGURATION
# ─────────────────────────────────────────────────────────────
BROKER = "broker.hivemq.com"
PORT = 1883
TEAM_ID = "TheCyberAlchemists"
BASE = f"epg317e/solar/{TEAM_ID}"

MQTT_KEEPALIVE = 60
MESSAGE_QUEUE_TIMEOUT = 0.1
MAX_READINGS = 20
MAX_LOG_LINES = 50

WAITING_FOR_ESP32 = "Waiting for ESP32 signal..."

# Expected operating ranges to filter out sensor anomalies
SENSOR_BOUNDS = {
    "temperature": (-50, 150),
    "humidity": (0, 100),
    "lux": (0, 100000),
    "servo_h": (0, 360),
    "servo_v": (0, 360),
}

# MQTT topic definitions for ingestion
SENSOR_TOPICS = {
    "temperature": f"{BASE}/sensors/temperature",
    "humidity": f"{BASE}/sensors/humidity",
    "lux": f"{BASE}/sensors/lux",
    "servo_h": f"{BASE}/actuators/servo_h",
    "servo_v": f"{BASE}/actuators/servo_v",
}

# ─────────────────────────────────────────────────────────────
# CUSTOM CSS STYLES
# ─────────────────────────────────────────────────────────────
CUSTOM_CSS = """
:root {
    --primary-bg: #0a0e27;
    --secondary-bg: #0f1535;
    --accent-cyan: #00d9ff;
    --text-primary: #e0e6ff;
    --text-secondary: #a0adc7;
}
body {
    background: linear-gradient(135deg, #0a0e27 0%, #1a1f3a 50%, #0f1535 100%) !important;
    background-attachment: fixed !important;
    font-family: 'Segoe UI', 'Courier New', monospace !important;
}
.pn-container { background: transparent !important; }
.bk-root .bk-btn {
    border-radius: 8px !important;
    border: 1px solid var(--accent-cyan) !important;
    background: linear-gradient(135deg, rgba(0, 217, 255, 0.1) 0%, rgba(0, 217, 255, 0.05) 100%) !important;
    color: var(--accent-cyan) !important;
    font-weight: 600 !important;
    transition: all 0.3s ease !important;
    text-transform: uppercase !important;
    font-size: 12px !important;
    letter-spacing: 1px !important;
}
.bk-root .bk-btn:hover {
    border-color: var(--accent-cyan) !important;
    box-shadow: 0 0 20px rgba(0, 217, 255, 0.8), inset 0 0 20px rgba(0, 217, 255, 0.2) !important;
    background: linear-gradient(135deg, rgba(0, 217, 255, 0.2) 0%, rgba(0, 217, 255, 0.1) 100%) !important;
}
.pn-card {
    background: linear-gradient(135deg, #0f1535 0%, #1a1f3a 100%) !important;
    border: 1px solid rgba(0, 217, 255, 0.3) !important;
    border-radius: 12px !important;
    box-shadow: 0 0 20px rgba(0, 217, 255, 0.1), inset 0 0 15px rgba(0, 217, 255, 0.05) !important;
}
.pn-title {
    color: var(--text-primary) !important;
    font-weight: 700 !important;
    text-shadow: 0 0 10px rgba(0, 217, 255, 0.5) !important;
    letter-spacing: 2px !important;
    font-size: 14px !important;
}
.bk-root label {
    color: var(--text-primary) !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    font-size: 12px !important;
    letter-spacing: 1px !important;
}
.bk-root input, .bk-root select, .bk-root textarea {
    background-color: rgba(15, 21, 53, 0.7) !important;
    border: 1px solid rgba(0, 217, 255, 0.3) !important;
    border-radius: 6px !important;
    color: var(--text-primary) !important;
    font-family: 'Courier New', monospace !important;
}
.bk-root input:focus, .bk-root select:focus, .bk-root textarea:focus {
    border-color: var(--accent-cyan) !important;
    box-shadow: 0 0 15px rgba(0, 217, 255, 0.6), inset 0 0 10px rgba(0, 217, 255, 0.1) !important;
    outline: none !important;
}
.pn-tabulator {
    background: linear-gradient(135deg, rgba(15, 21, 53, 0.8) 0%, rgba(26, 31, 58, 0.8) 100%) !important;
    border: 1px solid rgba(0, 217, 255, 0.2) !important;
    border-radius: 8px !important;
}
.tabulator .tabulator-header {
    background: linear-gradient(135deg, rgba(0, 217, 255, 0.1) 0%, rgba(0, 217, 255, 0.05) 100%) !important;
    border-bottom: 2px solid rgba(0, 217, 255, 0.3) !important;
}
.tabulator .tabulator-header .tabulator-col {
    color: var(--accent-cyan) !important;
    font-weight: 700 !important;
    text-transform: uppercase !important;
    font-size: 11px !important;
    letter-spacing: 1px !important;
}
.tabulator .tabulator-row {
    background: transparent !important;
    border-bottom: 1px solid rgba(0, 217, 255, 0.1) !important;
}
.tabulator .tabulator-row .tabulator-cell {
    color: var(--text-primary) !important;
    padding: 12px 10px !important;
    font-size: 13px !important;
}
.tabulator .tabulator-row:hover { background: rgba(0, 217, 255, 0.05) !important; }
::-webkit-scrollbar { width: 8px !important; height: 8px !important; }
::-webkit-scrollbar-track { background: rgba(15, 21, 53, 0.4) !important; border-radius: 10px !important; }
::-webkit-scrollbar-thumb {
    background: linear-gradient(180deg, var(--accent-cyan), var(--accent-cyan)) !important;
    border-radius: 10px !important;
    box-shadow: 0 0 10px rgba(0, 217, 255, 0.6) !important;
}
::-webkit-scrollbar-thumb:hover {
    background: linear-gradient(180deg, #00ffff, #00d9ff) !important;
    box-shadow: 0 0 15px rgba(0, 217, 255, 1) !important;
}
.pn-header {
    background: linear-gradient(135deg, #0a0e27 0%, #1a1f3a 100%) !important;
    border-bottom: 2px solid rgba(0, 217, 255, 0.3) !important;
    box-shadow: 0 4px 20px rgba(0, 217, 255, 0.1) !important;
}
.pn-header h1 {
    color: var(--accent-cyan) !important;
    font-weight: 800 !important;
    text-shadow: 0 0 20px rgba(0, 217, 255, 0.8), 0 0 40px rgba(0, 217, 255, 0.4) !important;
    letter-spacing: 3px !important;
}
.pn-sidebar {
    background: linear-gradient(180deg, #0a0e27 0%, #0f1535 100%) !important;
    border-right: 1px solid rgba(0, 217, 255, 0.2) !important;
}
.pn-indicator-number { font-size: 28pt !important; }
"""
pn.config.raw_css = [CUSTOM_CSS]

# ─────────────────────────────────────────────────────────────
# UTILITY FUNCTIONS
# ─────────────────────────────────────────────────────────────
def get_timestamp() -> str:
    """Returns the current system time formatted as HH:MM:SS."""
    return datetime.now().strftime("%H:%M:%S")

def validate_sensor_value(sensor_key: str, payload: str) -> Optional[float]:
    """
    Parses and sanitizes incoming MQTT payloads.
    Returns the float value if within defined operational bounds, otherwise None.
    """
    try:
        value = float(payload)
        if sensor_key in SENSOR_BOUNDS:
            min_val, max_val = SENSOR_BOUNDS[sensor_key]
            if not (min_val <= value <= max_val):
                logger.warning(f"Sensor '{sensor_key}' bounds violation: {value}")
                return None
        return value
    except ValueError as e:
        logger.error(f"Failed to parse {sensor_key} payload '{payload}': {e}")
        return None

# ─────────────────────────────────────────────────────────────
# VISUALIZATION COMPONENTS
# ─────────────────────────────────────────────────────────────
def create_analog_gauge_bokeh(value: float, max_value: float, color: str) -> figure:
    """
    Generates an analog half-circle gauge using Bokeh line geometries.
    Calculates arcs using trigonometric functions for a clean, futuristic look.
    """
    p = figure(
        width=320, height=180,
        toolbar_location=None, tools="",
        min_border=10, margin=(5, 5, 5, 5)
    )
    
    # Disable default grid/axis formatting for a clean UI
    p.background_fill_color = None
    p.border_fill_color = None
    p.outline_line_color = None
    p.grid.visible = False
    p.axis.visible = False
    
    # Normalize input value to radians (0 to Pi)
    angle = (value / max_value) * math.pi
    
    # Draw background arc (dimmed)
    angles_bg = [i * (math.pi / 50) for i in range(51)]
    x_bg = [0.75 * math.cos(a) for a in angles_bg]
    y_bg = [0.75 * math.sin(a) for a in angles_bg]
    p.line(x_bg, y_bg, line_width=14, color=ACCENT_CYAN, alpha=0.15)
    
    # Draw active value arc (bright)
    if angle > 0:
        angles_val = [i * (angle / 25) for i in range(26)]
        x_val = [0.75 * math.cos(a) for a in angles_val]
        y_val = [0.75 * math.sin(a) for a in angles_val]
        p.line(x_val, y_val, line_width=14, color=color, alpha=0.95)
    
    # Draw center anchor point
    p.circle(x=0, y=0, size=24, fill_color=color, line_color=color, alpha=0.85)
    
    # Lock coordinate ranges to prevent auto-scaling distortion
    p.x_range.start, p.x_range.end = -1.05, 1.05
    p.y_range.start, p.y_range.end = -0.25, 1.05
    
    return p

# ─────────────────────────────────────────────────────────────
# DATA MANAGEMENT
# ─────────────────────────────────────────────────────────────
class SensorState:
    """
    Maintains the current state of the solar tracker.
    Utilizes rolling deques to prevent memory overflow during continuous operation.
    """
    def __init__(self, max_readings: int = MAX_READINGS):
        self.max_readings = max_readings
        self.readings: Dict[str, deque] = {
            "time": deque(maxlen=max_readings),
            "temperature": deque(maxlen=max_readings),
            "humidity": deque(maxlen=max_readings),
            "lux": deque(maxlen=max_readings),
        }
        self.live: Dict[str, Any] = {
            "temperature": 0.0,
            "humidity": 0.0,
            "lux": 0.0,
            "servo_h": 90.0,
            "servo_v": 90.0,
            "last_seen": "waiting…",
            "connected": False,
        }
    
    def to_dataframe(self) -> pd.DataFrame:
        """Exports historical rolling buffers as a DataFrame for hvplot rendering."""
        return pd.DataFrame({
            "time": list(self.readings["time"]),
            "temperature": list(self.readings["temperature"]),
            "humidity": list(self.readings["humidity"]),
            "lux": list(self.readings["lux"]),
        })
    
    def update_live(self, key: str, value: Any) -> None:
        """Safely mutates the current live state mapping."""
        self.live[key] = value
    
    def add_reading_batch(self, timestamp: str) -> None:
        """Commits the current live values to the historical buffers."""
        self.readings["time"].append(timestamp)
        self.readings["temperature"].append(self.live["temperature"])
        self.readings["humidity"].append(self.live["humidity"])
        self.readings["lux"].append(self.live["lux"])

# Instantiate global state and thread-safe messaging queue
sensor_state = SensorState()
message_queue: queue.Queue = queue.Queue()

# ─────────────────────────────────────────────────────────────
# UI WIDGET INITIALIZATION
# ─────────────────────────────────────────────────────────────

# 1. Analog Gauge Panes
analog_temp_pane = pn.pane.Bokeh(create_analog_gauge_bokeh(0, 200, PALETTE["temperature"]), sizing_mode="stretch_width", height=180)
analog_hum_pane = pn.pane.Bokeh(create_analog_gauge_bokeh(0, 100, PALETTE["humidity"]), sizing_mode="stretch_width", height=180)
analog_lux_pane = pn.pane.Bokeh(create_analog_gauge_bokeh(0, 100, PALETTE["lux"]), sizing_mode="stretch_width", height=180)

# 2. Digital Readout Panes
digital_temp = pn.pane.HTML("<h2 style='text-align: center; margin: 0; padding-top: 10px; font-size: 28px; color: #ff6b35;'>0.0 °C</h2>", sizing_mode="stretch_width")
digital_hum = pn.pane.HTML("<h2 style='text-align: center; margin: 0; padding-top: 10px; font-size: 28px; color: #00d9ff;'>0.0 %</h2>", sizing_mode="stretch_width")
digital_lux = pn.pane.HTML("<h2 style='text-align: center; margin: 0; padding-top: 10px; font-size: 28px; color: #00ff41;'>0 lux</h2>", sizing_mode="stretch_width")

def update_analog_gauge_display(pane: pn.pane.Bokeh, value: float, max_value: float, color: str) -> None:
    pane.object = create_analog_gauge_bokeh(value, max_value, color)

def make_sensor_card(title: str, color: str, digital_pane: pn.pane.HTML, gauge_pane: pn.pane.Bokeh) -> pn.Card:
    """Assembles the digital readout and analog gauge into a styled UI card."""
    return pn.Card(
        pn.Column(digital_pane, gauge_pane, sizing_mode="stretch_width"),
        title=title,
        sizing_mode="stretch_width",
        styles={
            "background": GRADIENT_CARD,
            "border": f"2px solid {color}",
            "border-radius": "12px",
            "box-shadow": f"0 0 25px {color}55, inset 0 0 15px {color}11",
            "padding": "20px",
        }
    )

card_temp = make_sensor_card("🌡 TEMPERATURE", PALETTE["temperature"], digital_temp, analog_temp_pane)
card_hum = make_sensor_card("💧 HUMIDITY", PALETTE["humidity"], digital_hum, analog_hum_pane)
card_lux = make_sensor_card("☀️ LIGHT INTENSITY", PALETTE["lux"], digital_lux, analog_lux_pane)

# 3. Status Indicators
display_servo_h = pn.indicators.Number(name="HORIZONTAL", value=0, format="{value:.0f}°", font_size="28pt", sizing_mode="stretch_width")
display_servo_v = pn.indicators.Number(name="VERTICAL", value=0, format="{value:.0f}°", font_size="28pt", sizing_mode="stretch_width")
display_time = pn.widgets.StaticText(name="LAST READING", value=WAITING_FOR_ESP32, sizing_mode="stretch_width")
display_conn = pn.widgets.StaticText(name="CONNECTION", value="🔄 Connecting…", sizing_mode="stretch_width")

# Apply uniform styling to status displays
for display in [display_servo_h, display_servo_v, display_time, display_conn]:
    display.styles = {
        "background": GRADIENT_CARD,
        "border": f"1px solid {ACCENT_CYAN}",
        "border-radius": "8px",
        "padding": "16px",
        "color": ACCENT_CYAN,
        "font-size": "14px",
    }

# 4. Trend Charts
live_chart_temp = pn.pane.HoloViews(sizing_mode="stretch_width", height=250)
live_chart_lux = pn.pane.HoloViews(sizing_mode="stretch_width", height=250)

# 5. Data Table
summary_table = pn.widgets.Tabulator(
    pd.DataFrame({
        "Sensor": ["Temperature", "Humidity", "Light", "Pan", "Tilt"],
        "Reading": ["—"] * 5,
        "Unit": ["°C", "%", "lux", "°", "°"],
    }),
    show_index=False, disabled=True,
    widths={"Sensor": 140, "Reading": 120, "Unit": 80},
    sizing_mode="stretch_width", height=260,
)

# 6. Telemetry Log
incoming_log = pn.widgets.TextAreaInput(
    name="", value=f"Initializing sensor network...\n",
    height=200, disabled=True, sizing_mode="stretch_width",
)
incoming_log.styles = {
    "background": GRADIENT_CHART,
    "border": f"1px solid {ACCENT_CYAN}",
    "border-radius": "8px",
    "color": ACCENT_LIME,
    "font-family": "'Courier New', monospace",
    "font-size": "12px",
    "font-weight": "500",
}

btn_clear_logs = pn.widgets.Button(name="CLEAR", button_type="danger", width=100)
btn_clear_logs.styles = {
    "background": "linear-gradient(135deg, rgba(255, 0, 0, 0.2) 0%, rgba(255, 0, 0, 0.1) 100%)",
    "border": "1px solid #ff4444", "color": "#ff6666", "font-size": "12px",
}

def on_clear_logs(event: Any) -> None:
    incoming_log.value = "Logs cleared.\n"
    logger.info("Logs cleared by user")
btn_clear_logs.on_click(on_clear_logs)


# ─────────────────────────────────────────────────────────────
# UI UPDATE ROUTINES
# ─────────────────────────────────────────────────────────────
def refresh_analog_gauges() -> None:
    """Synchronizes digital readouts and analog gauges with current state memory."""
    temp = sensor_state.live["temperature"]
    hum = sensor_state.live["humidity"]
    lux = sensor_state.live["lux"]
    
    digital_temp.object = f"<h2 style='text-align: center; margin: 0; padding-top: 10px; font-size: 28px; color: {PALETTE['temperature']};'>{temp:.1f} °C</h2>"
    digital_hum.object = f"<h2 style='text-align: center; margin: 0; padding-top: 10px; font-size: 28px; color: {PALETTE['humidity']};'>{hum:.1f} %</h2>"
    digital_lux.object = f"<h2 style='text-align: center; margin: 0; padding-top: 10px; font-size: 28px; color: {PALETTE['lux']};'>{lux:.0f} lux</h2>"
    
    update_analog_gauge_display(analog_temp_pane, temp + 50, 200, PALETTE["temperature"])
    update_analog_gauge_display(analog_hum_pane, hum, 100, PALETTE["humidity"])
    
    # Scale lux down for the 0-100 gauge visualization
    lux_scaled = min(lux / 1000, 100)
    update_analog_gauge_display(analog_lux_pane, lux_scaled, 100, PALETTE["lux"])

def refresh_live_charts() -> None:
    """Rebuilds the hvplot trend charts using the latest data buffers."""
    df = sensor_state.to_dataframe()
    if len(df) < 2: return
    
    try:
        live_chart_temp.object = df.hvplot.line(
            x="time", y="temperature", title="Temperature Trend",
            xlabel="", ylabel="°C", color=PALETTE["temperature"], 
            line_width=2, responsive=True, height=250,
        )
        live_chart_lux.object = df.hvplot.area(
            x="time", y="lux", title="Light Intensity Trend",
            xlabel="", ylabel="lux", color=PALETTE["lux"], 
            alpha=0.6, line_width=2, responsive=True, height=250,
        )
    except Exception as e:
        logger.error(f"Render pipeline failure: {e}")

def refresh_summary_table() -> None:
    """Updates the textual summary DataFrame."""
    summary_table.value = pd.DataFrame({
        "Sensor": ["Temperature", "Humidity", "Light", "Pan", "Tilt"],
        "Reading": [
            f"{sensor_state.live['temperature']:.1f}",
            f"{sensor_state.live['humidity']:.0f}",
            f"{sensor_state.live['lux']:.0f}",
            f"{sensor_state.live['servo_h']:.0f}",
            f"{sensor_state.live['servo_v']:.0f}",
        ],
        "Unit": ["°C", "%", "lux", "°", "°"],
    })

def log_incoming(entry: str) -> None:
    """Prepends a new telemetry log to the text area, enforcing the maximum line limit."""
    lines = incoming_log.value.splitlines()
    incoming_log.value = "\n".join([entry] + lines[:MAX_LOG_LINES]) + "\n"


# ─────────────────────────────────────────────────────────────
# MQTT COMMUNICATION PROTOCOLS
# ─────────────────────────────────────────────────────────────
try:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
except AttributeError:
    client = mqtt.Client()

def on_connect(c: mqtt.Client, userdata: Any, flags: Any, reason_code: int, properties: Any = None) -> None:
    if reason_code == 0:
        sensor_state.update_live("connected", True)
        display_conn.value = f"⚡ ONLINE"
        logger.info(f"Broker connection established: {BROKER}")
        for topic in SENSOR_TOPICS.values():
            c.subscribe(topic)
    else:
        sensor_state.update_live("connected", False)
        display_conn.value = f"⚠️ OFFLINE"
        logger.error(f"MQTT connection rejected. Code: {reason_code}")

def on_disconnect(c: mqtt.Client, userdata: Any, disconnect_flags: Any = None, reason_code: Any = None, properties: Any = None) -> None:
    sensor_state.update_live("connected", False)
    display_conn.value = f"🔄 RECONNECTING"
    logger.warning(f"Broker connection lost. Code: {reason_code}")

def on_message(c: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
    """Callback for incoming packets. Routes payloads to the processing queue."""
    try:
        message_queue.put((msg.topic, msg.payload.decode().strip()), block=False)
    except Exception as e:
        logger.error(f"Queue ingestion error: {e}")

client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.on_message = on_message

def connect_to_broker() -> None:
    """Initiates the persistent MQTT loop in a daemon thread."""
    try:
        client.connect(BROKER, PORT, keepalive=MQTT_KEEPALIVE)
        client.loop_forever()
    except Exception as e:
        display_conn.value = f"❌ ERROR"
        logger.error(f"Fatal broker error: {e}")

broker_thread = threading.Thread(target=connect_to_broker, daemon=True)
broker_thread.start()


# ─────────────────────────────────────────────────────────────
# MAIN EVENT LOOP & DISPATCH
# ─────────────────────────────────────────────────────────────
def create_topic_handlers() -> Dict[str, Callable[[str], None]]:
    """Maps incoming MQTT topics to their respective validation and state-update functions."""
    def handle_temperature(payload: str) -> None:
        if (v := validate_sensor_value("temperature", payload)) is not None:
            sensor_state.update_live("temperature", v)
    def handle_humidity(payload: str) -> None:
        if (v := validate_sensor_value("humidity", payload)) is not None:
            sensor_state.update_live("humidity", v)
    def handle_lux(payload: str) -> None:
        if (v := validate_sensor_value("lux", payload)) is not None:
            sensor_state.update_live("lux", v)
    def handle_servo_h(payload: str) -> None:
        if (v := validate_sensor_value("servo_h", payload)) is not None:
            sensor_state.update_live("servo_h", v)
            display_servo_h.value = v
    def handle_servo_v(payload: str) -> None:
        if (v := validate_sensor_value("servo_v", payload)) is not None:
            sensor_state.update_live("servo_v", v)
            display_servo_v.value = v

    return {
        SENSOR_TOPICS["temperature"]: handle_temperature,
        SENSOR_TOPICS["humidity"]: handle_humidity,
        SENSOR_TOPICS["lux"]: handle_lux,
        SENSOR_TOPICS["servo_h"]: handle_servo_h,
        SENSOR_TOPICS["servo_v"]: handle_servo_v,
    }

topic_handlers = create_topic_handlers()

def process_queued_messages() -> None:
    """
    Main Panel periodic callback. Drains the thread-safe message queue,
    updates state, and triggers UI redraws as required.
    """
    try:
        while True:
            topic, payload = message_queue.get(timeout=MESSAGE_QUEUE_TIMEOUT)
            
            if topic in topic_handlers:
                topic_handlers[topic](payload)
            else:
                logger.warning(f"Unmapped topic received: {topic}")
            
            # Update telemetry logs and timestamp
            timestamp = get_timestamp()
            sensor_state.update_live("last_seen", timestamp)
            display_time.value = f"🟢 {timestamp}"
            
            sensor_name = topic.split("/")[-1]
            log_incoming(f"{sensor_name.upper()}: {payload}")
            
            # Batch UI updates to occur only when a full cycle (temperature) arrives
            if topic == SENSOR_TOPICS["temperature"]:
                sensor_state.add_reading_batch(timestamp)
                refresh_analog_gauges()
                refresh_live_charts()
                refresh_summary_table()
                
    except queue.Empty:
        pass
    except Exception as e:
        logger.error(f"Event loop execution error: {e}")

# Register the core event loop with Panel
pn.state.add_periodic_callback(process_queued_messages, period=100)


# ─────────────────────────────────────────────────────────────
# LAYOUT ASSEMBLY
# ─────────────────────────────────────────────────────────────
# Markdown header style dictionary
SECTION_HEADER_STYLE = {
    "color": ACCENT_CYAN, "font-weight": "700",
    "font-size": "16px", "margin-bottom": "15px",
}

main_content = pn.Column(
    # Hero Section
    pn.Row(
        pn.pane.Markdown(
            "# ⚡ SOLAR TRACKER COMMAND CENTER",
            styles={"color": ACCENT_CYAN, "text-shadow": f"0 0 20px {ACCENT_CYAN}", "font-weight": "800", "text-align": "center", "margin": "0"}
        ),
        sizing_mode="stretch_width",
        styles={"background": GRADIENT_HEADER, "border-bottom": f"2px solid {ACCENT_CYAN}", "border-radius": "12px", "padding": "24px 20px", "margin-bottom": "30px"}
    ),
    
    # 1. Primary Sensors
    pn.pane.Markdown("**LIVE READINGS**", styles=SECTION_HEADER_STYLE),
    pn.GridBox(
        card_temp, card_hum, card_lux,
        ncols=3, sizing_mode="stretch_width",
        styles={"gap": "20px", "margin-bottom": "30px"},
    ),

    # 2. Actuator Status
    pn.pane.Markdown("**PANEL ORIENTATION**", styles=SECTION_HEADER_STYLE),
    pn.Row(
        display_servo_h, display_servo_v, 
        sizing_mode="stretch_width",
        styles={"gap": "20px", "margin-bottom": "30px"},
    ),
    
    # 3. Connection & Timestamp
    pn.Row(
        display_time, display_conn,
        sizing_mode="stretch_width",
        styles={"gap": "20px", "margin-bottom": "30px"},
    ),

    # 4. Tabular Summary
    pn.pane.Markdown("**SENSOR SUMMARY**", styles=SECTION_HEADER_STYLE),
    summary_table,

    # 5. Historical Trends
    pn.pane.Markdown("**LIVE TRENDS**", styles={"color": ACCENT_CYAN, "font-weight": "700", "font-size": "16px", "margin-top": "30px", "margin-bottom": "15px"}),
    pn.Row(live_chart_temp, live_chart_lux, sizing_mode="stretch_width", styles={"gap": "20px"}),
    
    sizing_mode="stretch_width",
    styles={"background": DARK_BG, "padding": "30px", "border-radius": "12px"}
)

sidebar_content = [
    pn.Column(
        pn.Card(
            pn.pane.Markdown("**System Status**\n\nReal-time telemetry from ESP32 Solar Tracker"),
            title="INFO", collapsed=False, sizing_mode="stretch_width",
            styles={"background": GRADIENT_CARD, "border": f"1px solid {ACCENT_CYAN}", "border-radius": "8px"}
        ),
        pn.Spacer(height=15),
        pn.Card(
            pn.Column(incoming_log, pn.Row(btn_clear_logs, sizing_mode="stretch_width"), sizing_mode="stretch_width"),
            title="TELEMETRY", collapsed=False, sizing_mode="stretch_width",
            styles={"background": GRADIENT_CARD, "border": f"1px solid {ACCENT_CYAN}", "border-radius": "8px"}
        ),
        sizing_mode="stretch_width",
    )
]

dashboard = pn.template.FastListTemplate(
    title="☀️ SOLAR TRACKER",
    accent_base_color=ACCENT_CYAN,
    header_background=DARK_BG,
    theme="dark", theme_toggle=False, main_max_width="1600px",
    sidebar=sidebar_content, main=[main_content],
)

logger.info("✨ Dashboard initialized — Telemetry system online!")
dashboard.show()
