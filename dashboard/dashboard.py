"""
EPG317E — Solar Tracker Dashboard
Live display + Control Panel with Futuristic UI + Analog Gauges

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
import logging
import queue
import math
from datetime import datetime
from collections import deque
from typing import Optional, Dict, Callable, Tuple, Any
from bokeh.plotting import figure
from bokeh.models import ColumnDataSource

# ─────────────────────────────────────────────────────────────
# LOGGING SETUP
# ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

pn.extension("tabulator", sizing_mode="stretch_width", template="fast")

# ─────────────────────────────────────────────────────────────
# FUTURISTIC COLOR PALETTE & THEME
# ─────────────────────────────────────────────────────────────
DARK_BG = "#0a0e27"
DARKER_BG = "#050810"
ACCENT_CYAN = "#00d9ff"
ACCENT_MAGENTA = "#ff00ff"
ACCENT_LIME = "#00ff41"
ACCENT_PURPLE = "#b224ef"
ACCENT_ORANGE = "#ff6b35"
TEXT_PRIMARY = "#e0e6ff"
TEXT_SECONDARY = "#a0adc7"
BORDER_GLOW = "#00d9ff"

GRADIENT_HEADER = "linear-gradient(135deg, #0a0e27 0%, #1a1f3a 100%)"
GRADIENT_CARD = "linear-gradient(135deg, #0f1535 0%, #1a1f3a 100%)"
GRADIENT_CHART = "linear-gradient(180deg, #0a0e27 0%, #15213e 100%)"

# ─────────────────────────────────────────────────────────────
# CONSTANTS & CONFIGURATION
# ─────────────────────────────────────────────────────────────
BROKER = "broker.hivemq.com"
PORT = 1883
TEAM_ID = "TheCyberAlchemists"
BASE = f"epg317e/solar/{TEAM_ID}"

MESSAGE_QUEUE_TIMEOUT = 0.1
MAX_READINGS = 20
MAX_LOG_LINES = 50

CONNECTION_OK = "⚡ ONLINE"
CONNECTION_FAILED = "⚠️ OFFLINE"
CONNECTION_DISCONNECTED = "🔄 RECONNECTING"
CONNECTION_ERROR = "❌ ERROR"
WAITING_FOR_DATA = "Initializing sensor network..."
WAITING_FOR_ESP32 = "Waiting for ESP32 signal..."
MQTT_KEEPALIVE = 60

SENSOR_BOUNDS = {
    "temperature": (-50, 150),
    "humidity": (0, 100),
    "lux": (0, 100000),
    "servo_h": (0, 360),
    "servo_v": (0, 360),
}

SENSOR_TOPICS = {
    "temperature": f"{BASE}/sensors/temperature",
    "humidity": f"{BASE}/sensors/humidity",
    "lux": f"{BASE}/sensors/lux",
    "servo_h": f"{BASE}/actuators/servo_h",
    "servo_v": f"{BASE}/actuators/servo_v",
}

PALETTE = {
    "temperature": "#ff6b35",
    "humidity": "#00d9ff",
    "lux": "#00ff41",
    "servo": "#ff00ff",
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

.pn-container {
    background: transparent !important;
}

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

.tabulator .tabulator-row:hover {
    background: rgba(0, 217, 255, 0.05) !important;
}

::-webkit-scrollbar {
    width: 8px !important;
    height: 8px !important;
}

::-webkit-scrollbar-track {
    background: rgba(15, 21, 53, 0.4) !important;
    border-radius: 10px !important;
}

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

.pn-indicator-number {
    font-size: 28pt !important;
}
"""

pn.config.raw_css = [CUSTOM_CSS]

# ─────────────────────────────────────────────────────────────
# UTILITY FUNCTIONS
# ─────────────────────────────────────────────────────────────
def get_timestamp() -> str:
    """Get current timestamp in HH:MM:SS format."""
    return datetime.now().strftime("%H:%M:%S")


def validate_sensor_value(sensor_key: str, payload: str) -> Optional[float]:
    """Parse and validate sensor payload."""
    try:
        value = float(payload)
        if sensor_key in SENSOR_BOUNDS:
            min_val, max_val = SENSOR_BOUNDS[sensor_key]
            if not (min_val <= value <= max_val):
                logger.warning(
                    f"Sensor '{sensor_key}' value {value} out of bounds [{min_val}, {max_val}]"
                )
                return None
        return value
    except ValueError as e:
        logger.error(f"Could not parse {sensor_key} payload '{payload}': {e}")
        return None


# ─────────────────────────────────────────────────────────────
# ANALOG GAUGE CREATION (FIXED - Using Bokeh properly)
# ─────────────────────────────────────────────────────────────
def create_analog_gauge_bokeh(value: float, max_value: float, color: str) -> figure:
    """Create a professional analog gauge using Bokeh."""
    p = figure(
        width=320,
        height=180,
        toolbar_location=None,
        tools="",
        min_border=10,
        # max_border=10,  <-- REMOVE THIS LINE
        margin=(5, 5, 5, 5)
    )
    
    p.background_fill_color = None
    p.border_fill_color = None
    p.outline_line_color = None
    p.grid.visible = False
    p.axis.visible = False
    
    # Normalize to 0-180 degrees
    angle = (value / max_value) * math.pi
    
    # Background arc (light)
    angles_bg = [i * (math.pi / 50) for i in range(51)]
    x_bg = [0.75 * math.cos(a) for a in angles_bg]
    y_bg = [0.75 * math.sin(a) for a in angles_bg]
    p.line(x_bg, y_bg, line_width=14, color=ACCENT_CYAN, alpha=0.15)
    
    # Value arc (bright)
    if angle > 0:
        angles_val = [i * (angle / 25) for i in range(26)]
        x_val = [0.75 * math.cos(a) for a in angles_val]
        y_val = [0.75 * math.sin(a) for a in angles_val]
        p.line(x_val, y_val, line_width=14, color=color, alpha=0.95)
    
    # Center dot
    p.circle(x=0, y=0, size=24, fill_color=color, line_color=color, alpha=0.85)
    
    p.x_range.start, p.x_range.end = -1.05, 1.05
    p.y_range.start, p.y_range.end = -0.25, 1.05
    
    return p


# ─────────────────────────────────────────────────────────────
# SENSOR STATE CLASS
# ─────────────────────────────────────────────────────────────
class SensorState:
    """Manages sensor readings, live state, and data buffers."""
    
    def __init__(self, max_readings: int = MAX_READINGS):
        """Initialize sensor state with rolling buffers."""
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
        """Convert rolling buffers to a pandas DataFrame for hvplot charts."""
        return pd.DataFrame({
            "time": list(self.readings["time"]),
            "temperature": list(self.readings["temperature"]),
            "humidity": list(self.readings["humidity"]),
            "lux": list(self.readings["lux"]),
        })
    
    def update_live(self, key: str, value: Any) -> None:
        """Update a live state value."""
        self.live[key] = value
    
    def add_reading_batch(self, timestamp: str) -> None:
        """Add current live values to rolling buffers."""
        self.readings["time"].append(timestamp)
        self.readings["temperature"].append(self.live["temperature"])
        self.readings["humidity"].append(self.live["humidity"])
        self.readings["lux"].append(self.live["lux"])


sensor_state = SensorState()
message_queue: queue.Queue = queue.Queue()


# ─────────────────────────────────────────────────────────────
# ANALOG GAUGE PANES (DYNAMIC)
# ─────────────────────────────────────────────────────────────
analog_temp_pane = pn.pane.Bokeh(create_analog_gauge_bokeh(0, 200, PALETTE["temperature"]), sizing_mode="stretch_width", height=180)
analog_hum_pane = pn.pane.Bokeh(create_analog_gauge_bokeh(0, 100, PALETTE["humidity"]), sizing_mode="stretch_width", height=180)
analog_lux_pane = pn.pane.Bokeh(create_analog_gauge_bokeh(0, 100, PALETTE["lux"]), sizing_mode="stretch_width", height=180)


def update_analog_gauge_display(pane: pn.pane.Bokeh, value: float, max_value: float, color: str) -> None:
    """Update analog gauge display."""
    pane.object = create_analog_gauge_bokeh(value, max_value, color)


# ─────────────────────────────────────────────────────────────
# SENSOR CARDS WITH GAUGES
# ─────────────────────────────────────────────────────────────
def make_sensor_card(title: str, color: str, gauge_pane: pn.pane.Bokeh) -> pn.Card:
    """Create a professional sensor card with analog gauge."""
    card = pn.Card(
        gauge_pane,
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
    return card


card_temp = make_sensor_card("🌡 TEMPERATURE", PALETTE["temperature"], analog_temp_pane)
card_hum = make_sensor_card("💧 HUMIDITY", PALETTE["humidity"], analog_hum_pane)
card_lux = make_sensor_card("☀️ LIGHT INTENSITY", PALETTE["lux"], analog_lux_pane)


# ─────────────────────────────────────────────────────────────
# STATUS DISPLAYS
# ─────────────────────────────────────────────────────────────
display_servo_h = pn.indicators.Number(
    name="HORIZONTAL", value=0, format="{value:.0f}°", font_size="28pt"
)
display_servo_v = pn.indicators.Number(
    name="VERTICAL", value=0, format="{value:.0f}°", font_size="28pt"
)

display_time = pn.widgets.StaticText(name="LAST READING", value=WAITING_FOR_ESP32)
display_conn = pn.widgets.StaticText(name="CONNECTION", value="🔄 Connecting…")

for display in [display_servo_h, display_servo_v, display_time, display_conn]:
    display.styles = {
        "background": GRADIENT_CARD,
        "border": f"1px solid {ACCENT_CYAN}",
        "border-radius": "8px",
        "padding": "16px",
        "color": ACCENT_CYAN,
        "font-size": "14px",
    }


# ─────────────────────────────────────────────────────────────
# LIVE CHARTS
# ─────────────────────────────────────────────────────────────
live_chart_temp = pn.pane.HoloViews(sizing_mode="stretch_width", height=250)
live_chart_lux = pn.pane.HoloViews(sizing_mode="stretch_width", height=250)


def refresh_analog_gauges() -> None:
    """Update all analog gauges with current sensor values."""
    temp = sensor_state.live["temperature"]
    hum = sensor_state.live["humidity"]
    lux = sensor_state.live["lux"]
    
    update_analog_gauge_display(analog_temp_pane, temp + 50, 200, PALETTE["temperature"])
    update_analog_gauge_display(analog_hum_pane, hum, 100, PALETTE["humidity"])
    lux_scaled = min(lux / 1000, 100)
    update_analog_gauge_display(analog_lux_pane, lux_scaled, 100, PALETTE["lux"])


def refresh_live_charts() -> None:
    """Redraw the live hvplot charts."""
    df = sensor_state.to_dataframe()
    if len(df) < 2:
        return
    
    try:
        live_chart_temp.object = df.hvplot.line(
            x="time", y="temperature",
            title="Temperature Trend",
            xlabel="", ylabel="°C",
            color=PALETTE["temperature"], line_width=2,
            responsive=True, height=250,
        )
        live_chart_lux.object = df.hvplot.area(
            x="time", y="lux",
            title="Light Intensity Trend",
            xlabel="", ylabel="lux",
            color=PALETTE["lux"], alpha=0.6, line_width=2,
            responsive=True, height=250,
        )
    except Exception as e:
        logger.error(f"Error refreshing live charts: {e}")


# ─────────────────────────────────────────────────────────────
# SENSOR SUMMARY TABLE
# ─────────────────────────────────────────────────────────────
summary_table = pn.widgets.Tabulator(
    pd.DataFrame({
        "Sensor": ["Temperature", "Humidity", "Light", "Pan", "Tilt"],
        "Reading": ["—"] * 5,
        "Unit": ["°C", "%", "lux", "°", "°"],
    }),
    show_index=False,
    disabled=True,
    widths={"Sensor": 140, "Reading": 120, "Unit": 80},
    sizing_mode="stretch_width",
    height=260,
)


def refresh_summary_table() -> None:
    """Update the summary table."""
    conn_status = "ACTIVE" if sensor_state.live["connected"] else "OFFLINE"
    
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


# ─────────────────────────────────────────────────────────────
# MQTT LOG
# ─────────────────────────────────────────────────────────────
incoming_log = pn.widgets.TextAreaInput(
    name="",
    value=f"Initializing sensor network...\n",
    height=200,
    disabled=True,
    sizing_mode="stretch_width",
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


def log_incoming(entry: str) -> None:
    """Add a new line to the incoming log."""
    lines = incoming_log.value.splitlines()
    incoming_log.value = "\n".join([entry] + lines[:MAX_LOG_LINES]) + "\n"


btn_clear_logs = pn.widgets.Button(name="CLEAR", button_type="danger", width=100)

btn_clear_logs.styles = {
    "background": "linear-gradient(135deg, rgba(255, 0, 0, 0.2) 0%, rgba(255, 0, 0, 0.1) 100%)",
    "border": "1px solid #ff4444",
    "color": "#ff6666",
    "font-size": "12px",
}


def on_clear_logs(event: Any) -> None:
    """Clear the incoming log."""
    incoming_log.value = "Logs cleared.\n"
    logger.info("Logs cleared by user")


btn_clear_logs.on_click(on_clear_logs)


# ─────────────────────────────────────────────────────────────
# MQTT CLIENT SETUP
# ─────────────────────────────────────────────────────────────
try:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
except AttributeError:
    client = mqtt.Client()


def on_connect(c: mqtt.Client, userdata: Any, flags: Any, reason_code: int, 
               properties: Any = None) -> None:
    """Handle MQTT connection event."""
    if reason_code == 0:
        sensor_state.update_live("connected", True)
        display_conn.value = f"⚡ ONLINE"
        logger.info(f"Connected to MQTT broker: {BROKER}")
        
        for topic in SENSOR_TOPICS.values():
            c.subscribe(topic)
            logger.debug(f"Subscribed to: {topic}")
    else:
        sensor_state.update_live("connected", False)
        display_conn.value = f"⚠️ OFFLINE"
        logger.error(f"MQTT connection failed with code {reason_code}")


def on_disconnect(c: mqtt.Client, userdata: Any, disconnect_flags: Any = None, 
                  reason_code: Any = None, properties: Any = None) -> None:
    """Handle MQTT disconnection event."""
    sensor_state.update_live("connected", False)
    display_conn.value = f"🔄 RECONNECTING"
    logger.warning(f"Disconnected from MQTT broker (code {reason_code})")


def on_message(c: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
    """Called every time a new MQTT message arrives."""
    try:
        payload = msg.payload.decode().strip()
        topic = msg.topic
        message_queue.put((topic, payload), block=False)
    except Exception as e:
        logger.error(f"Error queuing MQTT message: {e}")


client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.on_message = on_message


def connect_to_broker() -> None:
    """Start the MQTT connection in a background thread."""
    try:
        client.connect(BROKER, PORT, keepalive=MQTT_KEEPALIVE)
        client.loop_forever()
    except Exception as e:
        display_conn.value = f"❌ ERROR"
        logger.error(f"MQTT connection error: {e}")


broker_thread = threading.Thread(target=connect_to_broker, daemon=True)
broker_thread.start()


# ─────────────────────────────────────────────────────────────
# MESSAGE PROCESSING
# ─────────────────────────────────────────────────────────────
def create_topic_handlers() -> Dict[str, Callable[[str], None]]:
    """Create a dispatch dictionary mapping topics to handler functions."""
    
    def handle_temperature(payload: str) -> None:
        value = validate_sensor_value("temperature", payload)
        if value is not None:
            sensor_state.update_live("temperature", value)
    
    def handle_humidity(payload: str) -> None:
        value = validate_sensor_value("humidity", payload)
        if value is not None:
            sensor_state.update_live("humidity", value)
    
    def handle_lux(payload: str) -> None:
        value = validate_sensor_value("lux", payload)
        if value is not None:
            sensor_state.update_live("lux", value)
    
    def handle_servo_h(payload: str) -> None:
        value = validate_sensor_value("servo_h", payload)
        if value is not None:
            sensor_state.update_live("servo_h", value)
            display_servo_h.value = value
    
    def handle_servo_v(payload: str) -> None:
        value = validate_sensor_value("servo_v", payload)
        if value is not None:
            sensor_state.update_live("servo_v", value)
            display_servo_v.value = value
    
    return {
        SENSOR_TOPICS["temperature"]: handle_temperature,
        SENSOR_TOPICS["humidity"]: handle_humidity,
        SENSOR_TOPICS["lux"]: handle_lux,
        SENSOR_TOPICS["servo_h"]: handle_servo_h,
        SENSOR_TOPICS["servo_v"]: handle_servo_v,
    }


topic_handlers = create_topic_handlers()


def process_queued_messages() -> None:
    """Process all queued MQTT messages on the main thread."""
    try:
        while True:
            topic, payload = message_queue.get(timeout=MESSAGE_QUEUE_TIMEOUT)
            
            if topic in topic_handlers:
                topic_handlers[topic](payload)
            else:
                logger.warning(f"Unknown topic: {topic}")
            
            timestamp = get_timestamp()
            sensor_state.update_live("last_seen", timestamp)
            display_time.value = f"🟢 {timestamp}"
            
            sensor_name = topic.split("/")[-1]
            log_incoming(f"{sensor_name.upper()}: {payload}")
            
            if topic == SENSOR_TOPICS["temperature"]:
                sensor_state.add_reading_batch(timestamp)
                refresh_analog_gauges()
                refresh_live_charts()
                refresh_summary_table()
    
    except queue.Empty:
        pass
    except Exception as e:
        logger.error(f"Error processing queued message: {e}")


pn.state.add_periodic_callback(process_queued_messages, period=100)


# ─────────────────────────────────────────────────────────────
# MAIN LAYOUT
# ─────────────────────────────────────────────────────────────
main_content = pn.Column(
    # Hero Section
    pn.Row(
        pn.pane.Markdown(
            "# ⚡ SOLAR TRACKER COMMAND CENTER",
            styles={
                "color": ACCENT_CYAN,
                "text-shadow": f"0 0 20px {ACCENT_CYAN}",
                "font-weight": "800",
                "text-align": "center",
                "margin": "0",
            }
        ),
        sizing_mode="stretch_width",
        styles={
            "background": GRADIENT_HEADER,
            "border-bottom": f"2px solid {ACCENT_CYAN}",
            "border-radius": "12px",
            "padding": "24px 20px",
            "margin-bottom": "30px",
        }
    ),
    
    # Live Readings Section
    pn.pane.Markdown(
        "**LIVE READINGS**",
        styles={
            "color": ACCENT_CYAN,
            "font-weight": "700",
            "font-size": "16px",
            "margin-bottom": "15px",
        }
    ),
    pn.GridBox(
        card_temp, card_hum, card_lux,
        ncols=3,
        sizing_mode="stretch_width",
        styles={"gap": "20px", "margin-bottom": "30px"},
    ),

    # Panel Orientation Section
    pn.pane.Markdown(
        "**PANEL ORIENTATION**",
        styles={
            "color": ACCENT_CYAN,
            "font-weight": "700",
            "font-size": "16px",
            "margin-bottom": "15px",
        }
    ),
    pn.GridBox(
        display_servo_h, 
        display_servo_v, 
        ncols=2,
        sizing_mode="stretch_width",
        styles={"gap": "20px", "margin-bottom": "30px"},
    ),
    
    # Status Row
    pn.Row(
        display_time,
        display_conn,
        sizing_mode="stretch_width",
        styles={"gap": "20px", "margin-bottom": "30px"},
    ),

    # Sensor Summary Section
    pn.pane.Markdown(
        "**SENSOR SUMMARY**",
        styles={
            "color": ACCENT_CYAN,
            "font-weight": "700",
            "font-size": "16px",
            "margin-bottom": "15px",
        }
    ),
    summary_table,

    # Trends Section
    pn.pane.Markdown(
        "**LIVE TRENDS**",
        styles={
            "color": ACCENT_CYAN,
            "font-weight": "700",
            "font-size": "16px",
            "margin-top": "30px",
            "margin-bottom": "15px",
        }
    ),
    pn.Row(
        live_chart_temp, 
        live_chart_lux,
        sizing_mode="stretch_width",
        styles={"gap": "20px"},
    ),
    
    sizing_mode="stretch_width",
    styles={
        "background": DARK_BG,
        "padding": "30px",
        "border-radius": "12px",
    }
)


# ─────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────
sidebar_content = [
    pn.Column(
        pn.Card(
            pn.pane.Markdown(
                "**System Status**\n\nReal-time telemetry from ESP32 Solar Tracker"
            ),
            title="INFO",
            collapsed=False,
            sizing_mode="stretch_width",
            styles={
                "background": GRADIENT_CARD,
                "border": f"1px solid {ACCENT_CYAN}",
                "border-radius": "8px",
            }
        ),
        pn.Spacer(height=15),
        pn.Card(
            pn.Column(
                incoming_log,
                pn.Row(btn_clear_logs, sizing_mode="stretch_width"),
                sizing_mode="stretch_width",
            ),
            title="TELEMETRY",
            collapsed=False,
            sizing_mode="stretch_width",
            styles={
                "background": GRADIENT_CARD,
                "border": f"1px solid {ACCENT_CYAN}",
                "border-radius": "8px",
            }
        ),
        sizing_mode="stretch_width",
    )
]


# ─────────────────────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────────────────────
dashboard = pn.template.FastListTemplate(
    title="☀️ SOLAR TRACKER",
    accent_base_color=ACCENT_CYAN,
    header_background=DARK_BG,
    theme="dark",
    theme_toggle=False,
    main_max_width="1600px",
    sidebar=sidebar_content,
    main=[main_content],
)

logger.info("✨ Dashboard initialized — Telemetry system online!")
dashboard.show()
