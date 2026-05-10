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
    pip install panel paho-mqtt hvplot pandas bokeh

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
MQTT_KEEPALIVE = 60

# All keys that must arrive before a DB commit is triggered
BATCH_KEYS = {"temperature", "humidity", "lux", "servo_pan", "servo_tilt", "battery"}

SENSOR_TOPICS = {
    "temperature": f"{BASE}/sensors/temperature",
    "humidity":    f"{BASE}/sensors/humidity",
    "lux":         f"{BASE}/sensors/lux",
    "battery":     f"{BASE}/sensors/battery",
    "servo_pan":   f"{BASE}/actuators/servo_pan",
    "servo_tilt":  f"{BASE}/actuators/servo_tilt",
}

CONTROL_TOPICS = {
    "tracking_mode": f"{BASE}/control/tracking_mode",
    "servo_pan":     f"{BASE}/control/servo_pan",
    "servo_tilt":    f"{BASE}/control/servo_tilt",
    "led":           f"{BASE}/control/led",
    "buzzer":        f"{BASE}/control/buzzer",
}

# ─────────────────────────────────────────────────────────────
# DATABASE SETUP (SQLite)
# FIX #2: Use AUTOINCREMENT id as primary key (not timestamp)
#          so rapid inserts never collide and lose data.
# FIX #5: Added battery column so voltage history is persisted.
# ─────────────────────────────────────────────────────────────
def init_db():
    """Initialises the SQLite database schema if it doesn't exist."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS telemetry (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   DATETIME NOT NULL,
            temperature REAL,
            humidity    REAL,
            lux         REAL,
            servo_pan   REAL,
            servo_tilt  REAL,
            battery     REAL
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
            "servo_pan": 90.0, "servo_tilt": 45.0, "battery": 0.0,
            "last_seen": "waiting…", "connected": False,
        }
        # FIX #6: Track which keys have arrived in the current batch.
        self.current_batch: set = set()

    def update_live(self, key: str, value: float) -> None:
        self.live[key] = value

    def commit_to_db(self, timestamp: str) -> None:
        """Writes the current snapshot of live data to SQLite.
        FIX #5: battery is now included in the INSERT.
        """
        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("""
                INSERT INTO telemetry
                    (timestamp, temperature, humidity, lux, servo_pan, servo_tilt, battery)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                timestamp,
                self.live["temperature"],
                self.live["humidity"],
                self.live["lux"],
                self.live["servo_pan"],
                self.live["servo_tilt"],
                self.live["battery"],
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Database insert error: {e}")

    def fetch_historical_data(self, hours: int) -> pd.DataFrame:
        """Queries SQLite for data within the selected time window.
        FIX #3: Uses a parameterised query to prevent SQL injection.
        """
        try:
            conn = sqlite3.connect(DB_FILE)
            cutoff_time = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
            query = "SELECT * FROM telemetry WHERE timestamp >= ? ORDER BY timestamp ASC"
            df = pd.read_sql_query(query, conn, params=(cutoff_time,), parse_dates=['timestamp'])
            conn.close()
            return df
        except Exception as e:
            logger.error(f"Database query error: {e}")
            return pd.DataFrame()

sensor_state = SensorState()
message_queue: queue.Queue = queue.Queue()

# ─────────────────────────────────────────────────────────────
# UI COMPONENTS: CONTROL PANEL (PUBLISHING TO ESP32)
# FIX #4: control_tilt range corrected to 0–90° (per README spec).
# ─────────────────────────────────────────────────────────────
control_switch_mode = pn.widgets.Switch(name="Auto-Tracking Mode", value=True)
control_pan  = pn.widgets.IntSlider(name="Manual Pan Angle",  start=0, end=180, step=1, value=90)
control_tilt = pn.widgets.IntSlider(name="Manual Tilt Angle", start=0, end=90,  step=1, value=45)
btn_led    = pn.widgets.Button(name="💡 TOGGLE LED",    button_type="primary", sizing_mode="stretch_width")
btn_buzzer = pn.widgets.Button(name="🔊 SOUND BUZZER", button_type="warning",  sizing_mode="stretch_width")

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
# FIX #4: gauge_tilt now uses max_value=90 to match tilt spec.
# ─────────────────────────────────────────────────────────────
def create_analog_gauge(value: float, max_value: float, color: str) -> figure:
    p = figure(width=320, height=180, toolbar_location=None, tools="", min_border=10, margin=(5, 5, 5, 5))
    p.background_fill_color = None; p.border_fill_color = None; p.outline_line_color = None
    p.grid.visible = False; p.axis.visible = False

    angle = (value / max_value) * math.pi if max_value > 0 else 0

    angles_bg = [i * (math.pi / 50) for i in range(51)]
    p.line([0.75 * math.cos(a) for a in angles_bg], [0.75 * math.sin(a) for a in angles_bg],
           line_width=14, color=ACCENT_CYAN, alpha=0.15)

    if angle > 0:
        angles_val = [i * (angle / 25) for i in range(26)]
        p.line([0.75 * math.cos(a) for a in angles_val], [0.75 * math.sin(a) for a in angles_val],
               line_width=14, color=color, alpha=0.95)

    p.circle(x=0, y=0, size=24, fill_color=color, line_color=color, alpha=0.85)
    p.x_range.start, p.x_range.end = -1.05, 1.05
    p.y_range.start, p.y_range.end = -0.25, 1.05
    return p

gauge_temp = pn.pane.Bokeh(create_analog_gauge(0, 100, PALETTE["temperature"]), sizing_mode="stretch_width", height=180)
gauge_hum  = pn.pane.Bokeh(create_analog_gauge(0, 100, PALETTE["humidity"]),    sizing_mode="stretch_width", height=180)
gauge_pan  = pn.pane.Bokeh(create_analog_gauge(0, 180, PALETTE["pan"]),         sizing_mode="stretch_width", height=180)
gauge_tilt = pn.pane.Bokeh(create_analog_gauge(0, 90,  PALETTE["tilt"]),        sizing_mode="stretch_width", height=180)

txt_temp = pn.pane.HTML(f"<h2 style='text-align:center; margin:0; padding-top:10px; color:{PALETTE['temperature']};'>0.0 °C</h2>")
txt_hum  = pn.pane.HTML(f"<h2 style='text-align:center; margin:0; padding-top:10px; color:{PALETTE['humidity']};'>0.0 %</h2>")
txt_pan  = pn.pane.HTML(f"<h2 style='text-align:center; margin:0; padding-top:10px; color:{PALETTE['pan']};'>0 °</h2>")
txt_tilt = pn.pane.HTML(f"<h2 style='text-align:center; margin:0; padding-top:10px; color:{PALETTE['tilt']};'>0 °</h2>")

def make_card(title, color, text_pane, gauge_pane):
    return pn.Card(
        pn.Column(text_pane, gauge_pane),
        title=title, sizing_mode="stretch_width",
        styles={"background": GRADIENT_CARD, "border": f"2px solid {color}", "padding": "10px"}
    )

# Time Range Filter & Charts
time_filter = pn.widgets.RadioButtonGroup(
    name='Historical Range',
    options={'1 Hour': 1, '6 Hours': 6, '24 Hours': 24, '7 Days': 168},
    value=1, button_type='primary', sizing_mode="stretch_width"
)

chart_env   = pn.pane.HoloViews(sizing_mode="stretch_width", height=300)
chart_track = pn.pane.HoloViews(sizing_mode="stretch_width", height=300)
display_conn = pn.widgets.StaticText(name="SYSTEM STATUS", value="🔄 Connecting…", sizing_mode="stretch_width")

# ─────────────────────────────────────────────────────────────
# UI REFRESH LOGIC
# FIX #4: gauge_tilt updated with max_value=90.
# ─────────────────────────────────────────────────────────────
def update_ui_components():
    """Updates gauges and SQLite-backed charts."""
    temp, hum = sensor_state.live["temperature"], sensor_state.live["humidity"]
    pan, tilt  = sensor_state.live["servo_pan"],   sensor_state.live["servo_tilt"]

    txt_temp.object = f"<h2 style='text-align:center; margin:0; padding-top:10px; color:{PALETTE['temperature']};'>{temp:.1f} °C</h2>"
    txt_hum.object  = f"<h2 style='text-align:center; margin:0; padding-top:10px; color:{PALETTE['humidity']};'>{hum:.1f} %</h2>"
    txt_pan.object  = f"<h2 style='text-align:center; margin:0; padding-top:10px; color:{PALETTE['pan']};'>{pan:.0f} °</h2>"
    txt_tilt.object = f"<h2 style='text-align:center; margin:0; padding-top:10px; color:{PALETTE['tilt']};'>{tilt:.0f} °</h2>"

    gauge_temp.object = create_analog_gauge(temp, 100, PALETTE["temperature"])
    gauge_hum.object  = create_analog_gauge(hum,  100, PALETTE["humidity"])
    gauge_pan.object  = create_analog_gauge(pan,  180, PALETTE["pan"])
    gauge_tilt.object = create_analog_gauge(tilt,  90, PALETTE["tilt"])  # FIX #4

    df = sensor_state.fetch_historical_data(hours=time_filter.value)
    if len(df) > 1:
        chart_env.object   = df.hvplot.line(x="timestamp", y=["temperature", "humidity"],
                                            title="Environment Trends",
                                            color=[PALETTE["temperature"], PALETTE["humidity"]],
                                            line_width=2, responsive=True, height=300)
        chart_track.object = df.hvplot.step(x="timestamp", y=["servo_pan", "servo_tilt"],
                                            title="Solar Tracking History",
                                            color=[PALETTE["pan"], PALETTE["tilt"]],
                                            line_width=2, responsive=True, height=300)

time_filter.param.watch(lambda e: update_ui_components(), 'value')

# ─────────────────────────────────────────────────────────────
# MQTT COMMUNICATION PROTOCOLS
# FIX #8: Added on_disconnect handler to update UI when broker drops.
# ─────────────────────────────────────────────────────────────
try:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
except AttributeError:
    client = mqtt.Client()

def on_connect(c, userdata, flags, rc, properties=None):
    if rc == 0:
        sensor_state.update_live("connected", True)
        display_conn.value = f"⚡ ONLINE — Connected to {BROKER}"
        for topic in SENSOR_TOPICS.values():
            c.subscribe(topic)
        logger.info(f"MQTT connected to {BROKER}")
    else:
        sensor_state.update_live("connected", False)
        display_conn.value = f"❌ CONNECTION FAILED (rc={rc})"
        logger.error(f"MQTT connection failed with rc={rc}")

def on_disconnect(c, userdata, disconnect_flags, rc, properties=None):
    """FIX #8: Update connection status so operators know data has stopped."""
    sensor_state.update_live("connected", False)
    display_conn.value = f"⚠️ OFFLINE — reconnecting to {BROKER}…"
    logger.warning(f"MQTT disconnected (rc={rc}), Paho will attempt reconnect.")

def on_message(c, userdata, msg):
    try:
        message_queue.put((msg.topic, msg.payload.decode().strip()), block=False)
    except Exception:
        pass

client.on_connect    = on_connect
client.on_disconnect = on_disconnect  # FIX #8
client.on_message    = on_message

threading.Thread(
    target=lambda: client.connect(BROKER, PORT, MQTT_KEEPALIVE) or client.loop_forever(),
    daemon=True
).start()

# ─────────────────────────────────────────────────────────────
# MESSAGE PROCESSING LOOP
# FIX #6: Commit to DB only when ALL batch keys have arrived,
#          not just when servo_tilt is seen (fragile ordering assumption).
# FIX #7: Use get_nowait() so the callback never blocks the event loop.
# ─────────────────────────────────────────────────────────────
def process_messages():
    """Drain the MQTT message queue and update state.
    Called every 250 ms by Panel's periodic callback (main thread).
    """
    try:
        while True:
            topic, payload = message_queue.get_nowait()  # FIX #7: non-blocking drain
            try:
                val = float(payload)
            except ValueError:
                logger.debug(f"Non-numeric payload on {topic}: {payload!r} — skipped")
                continue

            for key, t in SENSOR_TOPICS.items():
                if topic == t:
                    sensor_state.update_live(key, val)
                    sensor_state.current_batch.add(key)  # FIX #6
                    break

            # FIX #6: Commit and refresh only once a full batch has arrived.
            if BATCH_KEYS.issubset(sensor_state.current_batch):
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                sensor_state.commit_to_db(timestamp)
                sensor_state.current_batch.clear()
                update_ui_components()

    except queue.Empty:
        pass  # Nothing in the queue right now — return immediately (FIX #7)

pn.state.add_periodic_callback(process_messages, period=250)

# ─────────────────────────────────────────────────────────────
# LAYOUT ASSEMBLY
# ─────────────────────────────────────────────────────────────
main_content = pn.Column(
    pn.Row(
        pn.pane.Markdown(
            "# ☀️ SOLAR TRACKER COMMAND CENTER",
            styles={"color": ACCENT_CYAN, "text-align": "center", "margin": "0"}
        ),
        styles={"background": GRADIENT_HEADER, "padding": "20px", "border-radius": "12px"}
    ),
    display_conn,
    pn.pane.Markdown("**LIVE SENSOR FEED**", styles={"color": ACCENT_CYAN, "font-weight": "700"}),
    pn.GridBox(
        make_card("TEMPERATURE", PALETTE["temperature"], txt_temp, gauge_temp),
        make_card("HUMIDITY",    PALETTE["humidity"],    txt_hum,  gauge_hum),
        ncols=2, sizing_mode="stretch_width"
    ),
    pn.pane.Markdown("**PANEL ORIENTATION**", styles={"color": ACCENT_CYAN, "font-weight": "700"}),
    pn.GridBox(
        make_card("PAN ANGLE",  PALETTE["pan"],  txt_pan,  gauge_pan),
        make_card("TILT ANGLE", PALETTE["tilt"], txt_tilt, gauge_tilt),
        ncols=2, sizing_mode="stretch_width"
    ),
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
        title="CONTROL PANEL",
        styles={"background": GRADIENT_CARD, "border": f"1px solid {ACCENT_CYAN}"}
    )
)

dashboard = pn.template.FastListTemplate(
    title="IoT Solar Tracker",
    accent_base_color=ACCENT_CYAN,
    header_background=DARK_BG,
    theme="dark",
    main_max_width="1600px",
    sidebar=[sidebar_content],
    main=[main_content]
)

# FIX #1: Support both launch methods.
#
#   VS Code / python dashboard.py  → __name__ == "__main__" → .show()
#   panel serve dashboard.py       → __name__ == module name → .servable()
#
# Using .show() alone conflicts with `panel serve` (two servers on the same port).
# Using .servable() alone means a direct `python dashboard.py` run does nothing.
if __name__ == "__main__":
    dashboard.show()
else:
    dashboard.servable()
