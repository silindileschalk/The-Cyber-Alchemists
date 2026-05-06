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
from bokeh.models import Circle, AnnularWedge

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
DARK_BG = "#0a0e27"          # Deep navy-black
DARKER_BG = "#050810"        # Ultra-dark for contrast
ACCENT_CYAN = "#00d9ff"      # Neon cyan
ACCENT_MAGENTA = "#ff00ff"   # Neon magenta
ACCENT_LIME = "#00ff41"      # Neon lime
ACCENT_PURPLE = "#b224ef"    # Deep purple
ACCENT_ORANGE = "#ff6b35"    # Warm orange
TEXT_PRIMARY = "#e0e6ff"     # Light blue-white
TEXT_SECONDARY = "#a0adc7"   # Muted blue
BORDER_GLOW = "#00d9ff"      # Cyan glow

# Custom gradient backgrounds
GRADIENT_HEADER = "linear-gradient(135deg, #0a0e27 0%, #1a1f3a 100%)"
GRADIENT_CARD = "linear-gradient(135deg, #0f1535 0%, #1a1f3a 100%)"
GRADIENT_CHART = "linear-gradient(180deg, #0a0e27 0%, #15213e 100%)"

# ─────────────────────────────────────────────────────────────
# CONSTANTS & CONFIGURATION
# ─────────────────────────────────────────────────────────────
# MQTT Configuration
BROKER = "broker.hivemq.com"
PORT = 1883
TEAM_ID = "TheCyberAlchemists"
BASE = f"epg317e/solar/{TEAM_ID}"

# Message Queue Configuration
MESSAGE_QUEUE_TIMEOUT = 0.1  # seconds

# Data Configuration
MAX_READINGS = 20
MAX_LOG_LINES = 50

# Connection States
CONNECTION_OK = "⚡ ONLINE"
CONNECTION_FAILED = "⚠️ OFFLINE"
CONNECTION_DISCONNECTED = "🔄 RECONNECTING"
CONNECTION_ERROR = "❌ ERROR"
WAITING_FOR_DATA = "Initializing sensor network..."
WAITING_FOR_ESP32 = "Waiting for ESP32 signal..."
MQTT_KEEPALIVE = 60

# Sensor Bounds for Validation
SENSOR_BOUNDS = {
    "temperature": (-50, 150),
    "humidity": (0, 100),
    "lux": (0, 100000),
    "servo_h": (0, 360),
    "servo_v": (0, 360),
}

# Topics the ESP32 publishes sensor readings to
SENSOR_TOPICS = {
    "temperature": f"{BASE}/sensors/temperature",
    "humidity": f"{BASE}/sensors/humidity",
    "lux": f"{BASE}/sensors/lux",
    "servo_h": f"{BASE}/actuators/servo_h",
    "servo_v": f"{BASE}/actuators/servo_v",
}

# Futuristic Colour Scheme
PALETTE = {
    "temperature": "#ff6b35",   # Warm orange
    "humidity": "#00d9ff",      # Neon cyan
    "lux": "#00ff41",           # Neon lime
    "servo": "#ff00ff",         # Neon magenta
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

/* Futuristic card styling */
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

/* Glowing borders */
.pn-card {
    background: linear-gradient(135deg, #0f1535 0%, #1a1f3a 100%) !important;
    border: 1px solid rgba(0, 217, 255, 0.3) !important;
    border-radius: 12px !important;
    box-shadow: 0 0 20px rgba(0, 217, 255, 0.1), inset 0 0 15px rgba(0, 217, 255, 0.05) !important;
}

/* Text styling */
.pn-title {
    color: var(--text-primary) !important;
    font-weight: 700 !important;
    text-shadow: 0 0 10px rgba(0, 217, 255, 0.5) !important;
    letter-spacing: 2px !important;
}

.bk-root label {
    color: var(--text-primary) !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    font-size: 11px !important;
    letter-spacing: 1px !important;
}

/* Input fields */
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

/* Table styling */
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
}

.tabulator .tabulator-row:hover {
    background: rgba(0, 217, 255, 0.05) !important;
}

/* Scrollbar styling */
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

/* Panel header */
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

/* Sidebar */
.pn-sidebar {
    background: linear-gradient(180deg, #0a0e27 0%, #0f1535 100%) !important;
    border-right: 1px solid rgba(0, 217, 255, 0.2) !important;
}
"""

# Inject custom CSS
pn.config.raw_css = [CUSTOM_CSS]


# ─────────────────────────────────────────────────────────────
# UTILITY FUNCTIONS
# ─────────────────────────────────────────────────────────────
def get_timestamp() -> str:
    """Get current timestamp in HH:MM:SS format."""
    return datetime.now().strftime("%H:%M:%S")


def validate_sensor_value(sensor_key: str, payload: str) -> Optional[float]:
    """
    Parse and validate sensor payload.
    
    Args:
        sensor_key: The sensor identifier
        payload: The raw string payload from MQTT
        
    Returns:
        Validated float value, or None if invalid
    """
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
# ANALOG GAUGE CREATION
# ─────────────────────────────────────────────────────────────
def create_analog_gauge(value: float = 0, max_value: float = 100, 
                       color: str = ACCENT_CYAN, title: str = "") -> pn.pane.Bokeh:
    """
    Create a futuristic half-circle analog gauge using Bokeh.
    
    Args:
        value: Current gauge value
        max_value: Maximum gauge value
        color: Gauge color (hex)
        title: Gauge title
        
    Returns:
        Panel Bokeh pane with the gauge
    """
    # Create figure with transparent background
    p = figure(
        width=250, height=150,
        toolbar_location=None,
        tools="",
        min_border=0, max_border=0,
        margin=(0, 0, 0, 0)
    )
    
    # Set background colors
    p.background_fill_color = None
    p.border_fill_color = None
    p.outline_line_color = None
    p.grid.visible = False
    p.axis.visible = False
    
    # Normalize value to 0-180 degrees (half circle)
    angle = (value / max_value) * math.pi
    
    # Draw background arc (full half circle)
    background_arc = AnnularWedge(
        x=0, y=0, inner_radius=0.65, outer_radius=0.85,
        start_angle=0, end_angle=math.pi,
        fill_color="#1a1f3a", line_color=ACCENT_CYAN, line_width=2
    )
    p.add_glyph(p.renderers[0].data_source if p.renderers else None, background_arc)
    
    # Draw value arc (dynamic)
    value_arc = AnnularWedge(
        x=0, y=0, inner_radius=0.65, outer_radius=0.85,
        start_angle=0, end_angle=angle,
        fill_color=color, line_color=color, line_width=1, alpha=0.8
    )
    p.add_glyph(p.renderers[0].data_source if p.renderers else None, value_arc)
    
    # Add glow effect circle in center
    p.circle(x=0, y=0, size=15, fill_color=color, line_color=color, alpha=0.6)
    
    # Set axis range
    p.x_range.start, p.x_range.end = -1, 1
    p.y_range.start, p.y_range.end = -0.2, 1
    
    return pn.pane.Bokeh(p, height=150, sizing_mode="stretch_width")


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
# ANALOG GAUGE WIDGETS (DYNAMIC UPDATES)
# ─────────────────────────────────────────────────────────────
analog_temp = pn.pane.Bokeh(height=150, sizing_mode="stretch_width")
analog_hum = pn.pane.Bokeh(height=150, sizing_mode="stretch_width")
analog_lux = pn.pane.Bokeh(height=150, sizing_mode="stretch_width")


def update_analog_gauge(pane: pn.pane.Bokeh, value: float, max_value: float, 
                       color: str) -> None:
    """Update an analog gauge with new value."""
    p = figure(
        width=250, height=150,
        toolbar_location=None,
        tools="",
        min_border=0, max_border=0,
        margin=(0, 0, 0, 0)
    )
    
    p.background_fill_color = None
    p.border_fill_color = None
    p.outline_line_color = None
    p.grid.visible = False
    p.axis.visible = False
    
    angle = (value / max_value) * math.pi
    
    # Background arc
    from bokeh.models import ColumnDataSource
    
    # Draw arcs using line segments for better control
    angles_bg = [i * (math.pi / 50) for i in range(51)]
    x_bg = [0.75 * math.cos(a) for a in angles_bg]
    y_bg = [0.75 * math.sin(a) for a in angles_bg]
    
    p.line(x_bg, y_bg, line_width=12, color=ACCENT_CYAN, alpha=0.2)
    
    # Value arc
    angles_val = [i * (angle / 25) for i in range(26)]
    x_val = [0.75 * math.cos(a) for a in angles_val]
    y_val = [0.75 * math.sin(a) for a in angles_val]
    
    p.line(x_val, y_val, line_width=12, color=color, alpha=0.9)
    
    # Center indicator dot
    p.circle(x=0, y=0, size=20, fill_color=color, line_color=color, alpha=0.8)
    
    p.x_range.start, p.x_range.end = -1, 1
    p.y_range.start, p.y_range.end = -0.2, 1
    
    pane.object = p


# ─────────────────────────────────────────────────────────────
# FUTURISTIC SENSOR TREND CARDS WITH ANALOG GAUGES
# ─────────────────────────────────────────────────────────────
def make_trend_card_with_analog(label: str, emoji: str, color: str, 
                               analog_pane: pn.pane.Bokeh, 
                               chart_style: str = "line") -> Tuple[pn.indicators.Trend, pn.Card]:
    """Build a futuristic sensor card with trend and analog gauge."""
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
    
    # Create composite card with trend on top and analog gauge at bottom right
    card_content = pn.Column(
        trend,
        sizing_mode="stretch_width",
        styles={"height": "100%"}
    )
    
    card = pn.Card(
        pn.Row(
            card_content,
            pn.Column(
                analog_pane,
                sizing_mode="stretch_width",
                styles={"min-width": "250px"}
            ),
            sizing_mode="stretch_width",
            styles={"gap": "10px"}
        ),
        hide_header=True,
        sizing_mode="stretch_width",
        styles={
            "background": GRADIENT_CARD,
            "border": f"2px solid {color}",
            "border-radius": "12px",
            "box-shadow": f"0 0 30px {color}66, inset 0 0 20px {color}22",
            "padding": "16px",
        },
    )
    return trend, card


trend_temp, card_temp = make_trend_card_with_analog("🌡 TEMPERATURE", "°C", PALETTE["temperature"], analog_temp, "line")
trend_hum, card_hum = make_trend_card_with_analog("💧 HUMIDITY", "%", PALETTE["humidity"], analog_hum, "area")
trend_lux, card_lux = make_trend_card_with_analog("☀️ LIGHT INTENSITY", "lux", PALETTE["lux"], analog_lux, "bar")


# ─────────────────────────────────────────────────────────────
# STATUS DISPLAYS — servo angles and connection info
# ─────────────────────────────────────────────────────────────
display_servo_h = pn.indicators.Number(
    name="HORIZONTAL PAN", value=0, format="{value:.0f}°", font_size="32pt"
)
display_servo_v = pn.indicators.Number(
    name="VERTICAL TILT", value=0, format="{value:.0f}°", font_size="32pt"
)

display_time = pn.widgets.StaticText(name="⏱ LAST READING", value=WAITING_FOR_ESP32)
display_conn = pn.widgets.StaticText(name="🌐 CONNECTION STATUS", value="🔄 Connecting to broker…")

# Style the status displays
for display in [display_servo_h, display_servo_v, display_time, display_conn]:
    display.styles = {
        "background": GRADIENT_CARD,
        "border": f"1px solid {ACCENT_CYAN}",
        "border-radius": "8px",
        "padding": "16px",
        "color": ACCENT_CYAN,
    }


# ─────────────────────────────────────────────────────────────
# LIVE CHARTS — futuristic hvplot charts
# ─────────────────────────────────────────────────────────────
live_chart_temp = pn.pane.HoloViews(sizing_mode="stretch_width", height=250)
live_chart_lux = pn.pane.HoloViews(sizing_mode="stretch_width", height=250)


def refresh_trend_card(trend_widget: pn.indicators.Trend, sensor_key: str) -> None:
    """Update a Trend card's sparkline and value from the latest readings buffer."""
    buf = list(sensor_state.readings[sensor_key])
    if len(buf) < 2:
        return
    
    current = buf[-1]
    previous = buf[-2]
    pct_change = (current - previous) / abs(previous) if previous != 0 else 0.0
    
    trend_widget.data = {"x": list(range(len(buf))), "y": buf}
    trend_widget.value = round(current, 2)
    trend_widget.value_change = round(pct_change, 4)


def refresh_analog_gauges() -> None:
    """Update all analog gauges with current sensor values."""
    temp = sensor_state.live["temperature"]
    hum = sensor_state.live["humidity"]
    lux = sensor_state.live["lux"]
    
    # Temperature: -50 to 150°C
    update_analog_gauge(analog_temp, temp + 50, 200, PALETTE["temperature"])
    
    # Humidity: 0 to 100%
    update_analog_gauge(analog_hum, hum, 100, PALETTE["humidity"])
    
    # Light: 0 to 100000 lux (scaled to 0-100 for display)
    lux_scaled = min(lux / 1000, 100)
    update_analog_gauge(analog_lux, lux_scaled, 100, PALETTE["lux"])


def refresh_live_charts() -> None:
    """Redraw the temperature and lux hvplot charts from the current readings buffer."""
    df = sensor_state.to_dataframe()
    if len(df) < 2:
        return
    
    try:
        live_chart_temp.object = df.hvplot.line(
            x="time", y="temperature",
            title="🌡 TEMPERATURE TREND",
            xlabel="Time", ylabel="°C",
            color=PALETTE["temperature"], line_width=3,
            responsive=True, height=250,
        )
        live_chart_lux.object = df.hvplot.area(
            x="time", y="lux",
            title="☀️ LIGHT INTENSITY TREND",
            xlabel="Time", ylabel="lux",
            color=PALETTE["lux"], alpha=0.6, line_width=2,
            responsive=True, height=250,
        )
    except Exception as e:
        logger.error(f"Error refreshing live charts: {e}")


# ─────────────────────────────────────────────────────────────
# SENSOR SUMMARY TABLE — futuristic tabulator
# ─────────────────────────────────────────────────────────────
summary_table = pn.widgets.Tabulator(
    pd.DataFrame({
        "Sensor": ["🌡 Temperature", "💧 Humidity", "☀️ Light", "🎯 Horiz. Pan", "🎯 Vert. Tilt"],
        "Reading": ["—"] * 5,
        "Unit": ["°C", "%", "lux", "°", "°"],
        "Status": ["◐ WAITING"] * 5,
    }),
    show_index=False,
    disabled=True,
    widths={"Sensor": 160, "Reading": 100, "Unit": 60, "Status": 120},
    sizing_mode="stretch_width",
    height=280,
)


def refresh_summary_table() -> None:
    """Push the latest live values into the summary table."""
    now = sensor_state.live["last_seen"]
    conn_status = "🟢 ACTIVE" if sensor_state.live["connected"] else "🔴 OFFLINE"
    
    summary_table.value = pd.DataFrame({
        "Sensor": ["🌡 Temperature", "💧 Humidity", "☀️ Light", "🎯 Horiz. Pan", "🎯 Vert. Tilt"],
        "Reading": [
            f"{sensor_state.live['temperature']:.1f}",
            f"{sensor_state.live['humidity']:.0f}",
            f"{sensor_state.live['lux']:.0f}",
            f"{sensor_state.live['servo_h']:.0f}",
            f"{sensor_state.live['servo_v']:.0f}",
        ],
        "Unit": ["°C", "%", "lux", "°", "°"],
        "Status": [conn_status] * 5,
    })


# ─────────────────────────────────────────────────────────────
# MQTT LOG — scrolling live feed with tech styling
# ─────────────────────────────────────────────────────────────
incoming_log = pn.widgets.TextAreaInput(
    name="📡 INCOMING SENSOR DATA",
    value=f"[SYSTEM] {WAITING_FOR_DATA}\n",
    height=220,
    disabled=True,
    sizing_mode="stretch_width",
)

incoming_log.styles = {
    "background": GRADIENT_CHART,
    "border": f"1px solid {ACCENT_CYAN}",
    "border-radius": "8px",
    "color": ACCENT_LIME,
    "font-family": "'Courier New', monospace",
    "font-size": "11px",
    "font-weight": "500",
    "letter-spacing": "0.5px",
}


def log_incoming(entry: str) -> None:
    """Add a new line at the top of the incoming log."""
    lines = incoming_log.value.splitlines()
    incoming_log.value = "\n".join([entry] + lines[:MAX_LOG_LINES]) + "\n"


btn_clear_logs = pn.widgets.Button(
    name="🗑️  CLEAR LOGS", button_type="danger", width=150
)

btn_clear_logs.styles = {
    "background": "linear-gradient(135deg, rgba(255, 0, 0, 0.2) 0%, rgba(255, 0, 0, 0.1) 100%)",
    "border": "1px solid #ff4444",
    "color": "#ff6666",
}


def on_clear_logs(event: Any) -> None:
    """Clear the incoming log."""
    incoming_log.value = "[SYSTEM] Logs cleared.\n"
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
        display_conn.value = f"⚡ {CONNECTION_OK} — {BROKER}"
        logger.info(f"Connected to MQTT broker: {BROKER}")
        
        for topic in SENSOR_TOPICS.values():
            c.subscribe(topic)
            logger.debug(f"Subscribed to: {topic}")
    else:
        sensor_state.update_live("connected", False)
        display_conn.value = f"{CONNECTION_FAILED} (code {reason_code})"
        logger.error(f"MQTT connection failed with code {reason_code}")


def on_disconnect(c: mqtt.Client, userdata: Any, disconnect_flags: Any = None, 
                  reason_code: Any = None, properties: Any = None) -> None:
    """Handle MQTT disconnection event."""
    sensor_state.update_live("connected", False)
    display_conn.value = f"🔄 {CONNECTION_DISCONNECTED}"
    logger.warning(f"Disconnected from MQTT broker (code {reason_code})")


def on_message(c: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
    """Called every time a new MQTT message arrives from the ESP32."""
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
        display_conn.value = f"{CONNECTION_ERROR}: {e}"
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
            log_incoming(f"[{timestamp}] >> {sensor_name.upper()}: {payload}")
            
            if topic == SENSOR_TOPICS["temperature"]:
                sensor_state.add_reading_batch(timestamp)
                
                refresh_trend_card(trend_temp, "temperature")
                refresh_trend_card(trend_hum, "humidity")
                refresh_trend_card(trend_lux, "lux")
                refresh_analog_gauges()
                refresh_live_charts()
                refresh_summary_table()
    
    except queue.Empty:
        pass
    except Exception as e:
        logger.error(f"Error processing queued message: {e}")


pn.state.add_periodic_callback(process_queued_messages, period=100)


# ─────────────────────────────────────────────────────────────
# FUTURISTIC LAYOUT — main content area
# ─────────────────────────────────────────────────────────────

# Section headers with futuristic styling
def make_section_header(text: str, emoji: str = "") -> pn.pane.Markdown:
    """Create a styled section header."""
    return pn.pane.Markdown(
        f"## {emoji} {text}",
        styles={
            "color": ACCENT_CYAN,
            "text-shadow": f"0 0 10px {ACCENT_CYAN}",
            "font-weight": "700",
            "letter-spacing": "2px",
            "margin-top": "30px",
            "margin-bottom": "20px",
            "font-size": "20px",
        }
    )


main_content = pn.Column(
    # Hero Section
    pn.Row(
        pn.pane.Markdown(
            """
            # ⚡ SOLAR TRACKER COMMAND CENTER ⚡
            **Real-Time Sensor Network | Futuristic Control Panel**
            """,
            styles={
                "color": ACCENT_CYAN,
                "text-shadow": f"0 0 20px {ACCENT_CYAN}",
                "font-weight": "800",
                "text-align": "center",
            }
        ),
        sizing_mode="stretch_width",
        styles={
            "background": GRADIENT_HEADER,
            "border-bottom": f"2px solid {ACCENT_CYAN}",
            "border-radius": "12px",
            "padding": "30px 20px",
            "margin-bottom": "30px",
        }
    ),
    
    # Live Sensor Readings Section
    make_section_header("LIVE SENSOR READINGS (DIGITAL + ANALOG)", "📊"),
    pn.GridBox(
        card_temp, card_hum, card_lux,
        ncols=3,
        sizing_mode="stretch_width",
        styles={"gap": "20px"},
    ),

    # Solar Panel Orientation Section
    make_section_header("SOLAR PANEL ORIENTATION", "🎯"),
    pn.GridBox(
        display_servo_h, 
        display_servo_v, 
        ncols=2,
        sizing_mode="stretch_width",
        styles={"gap": "20px"},
    ),
    
    # Status Info Row
    pn.Row(
        display_time,
        display_conn,
        sizing_mode="stretch_width",
        styles={"gap": "20px"},
    ),

    # Sensor Summary Section
    make_section_header("SENSOR NETWORK STATUS", "📡"),
    summary_table,

    # Trends Section
    make_section_header("LIVE TRENDS ANALYSIS", "📈"),
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
# LAYOUT — sidebar (logs and info)
# ─────────────────────────────────────────────────────────────
sidebar_content = [
    pn.Column(
        pn.Card(
            pn.pane.Markdown(
                """
**🔴 DASHBOARD STATUS: LIVE**

This is an advanced telemetry interface displaying real-time data from the ESP32 Solar Tracker system.

**⚙️ System Configuration:**
- **Broker**: HiveMQ Public (TLS)
- **Protocol**: MQTT v3.1.1
- **Refresh Rate**: 100ms
- **Data Retention**: 20 readings

**📊 Active Sensors:**
- 🌡 DHT11 (Temperature & Humidity)
- ☀️ BH1750 (Ambient Light)
- 🎯 Servo Feedback (Pan & Tilt)

**🎮 Control Mode:**
- Auto-tracking via LDR feedback
- Physical buttons on ESP32
- Real-time telemetry streaming

**✨ Display Mode:**
- Hybrid Analog/Digital readouts
- Futuristic half-circle gauge dials
- Real-time data fusion
            """
            ),
            title="🖥️ SYSTEM INFO",
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
            incoming_log,
            pn.Row(btn_clear_logs, sizing_mode="stretch_width"),
            title="📡 MQTT TELEMETRY STREAM",
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
# DASHBOARD TEMPLATE
# ─────────────────────────────────────────────────────────────
dashboard = pn.template.FastListTemplate(
    title="☀️ SOLAR TRACKER COMMAND CENTER ☀️",
    accent_base_color=ACCENT_CYAN,
    header_background=DARK_BG,
    theme="dark",
    theme_toggle=False,
    main_max_width="1600px",
    sidebar=sidebar_content,
    main=[main_content],
)

logger.info("✨ Futuristic Dashboard with Analog Gauges initialized — Telemetry system online!")
dashboard.show()
