"""
EPG317E Capstone Project — Solar Tracker Dashboard (v3)
The Cyber Alchemists
--------------------------------------------------------
"""

import math
import queue
import random
import logging
import threading
from datetime import datetime
import param
import pandas as pd
import panel as pn
import hvplot.pandas
import ssl
import paho.mqtt.client as mqtt
from bokeh.plotting import figure
import warnings
from bokeh.util.warnings import BokehUserWarning
import sys
from pathlib import Path
currentFilePath = Path(__file__).resolve()
repoRoot = currentFilePath.parent.parent
databaseFolder = repoRoot / "DatabaseFolder" 
sys.path.insert(0, str(databaseFolder))

from database import (
    store_mqtt_reading,
    log_command,
    log_event,
    load_readings_last_n_hours_to_df,
)

# ─────────────────────────────────────────────────────────────
# LOGGING & PANEL INIT
# ─────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)
pn.extension("tabulator", sizing_mode="stretch_width")
# Suppress the harmless Bokeh widget recycling warnings
warnings.filterwarnings("ignore", category=BokehUserWarning, message="reference already known")



# ─────────────────────────────────────────────────────────────
# THEME DEFINITIONS
# ─────────────────────────────────────────────────────────────
DARK_THEME = {
    "name":          "dark",
    "bg":            "#0a0e27",
    "card_bg":       "linear-gradient(135deg, #0f1535 0%, #1a1f3a 100%)",
    "header_bg":     "#0a0e27",
    "accent":        "#00d9ff",
    "accent_lime":   "#00ff41",
    "accent_orange": "#ff6b35",
    "accent_yellow": "#ffcc00",
    "accent_purple": "#ff00ff",
    "gauge_track":   "#00d9ff",
    "css": """
        body { background: linear-gradient(135deg,#0a0e27 0%,#1a1f3a 50%,#0f1535 100%) !important;
               font-family:'Segoe UI',monospace !important; }
        .pn-card { background:linear-gradient(135deg,#0f1535 0%,#1a1f3a 100%) !important;
                   border:1px solid rgba(0,217,255,0.3) !important; border-radius:12px !important; }
        .bk-root { background:transparent !important; }
        h2,h3 { font-family:'Segoe UI',monospace !important; }
    """,
}

LIGHT_THEME = {
    "name":          "light",
    "bg":            "#f0f4ff",
    "card_bg":       "linear-gradient(135deg, #ffffff 30%, #e8eeff 70%)",
    "header_bg":     "#1565c0",
    "accent":        "#1565c0",
    "accent_lime":   "#2e7d32",
    "accent_orange": "#e65100",
    "accent_yellow": "#f57f17",
    "accent_purple": "#6a1b9a",
    "gauge_track":   "#90caf9",
    "css": """
        body { background: linear-gradient(135deg,#f0f4ff 50%,#e3eaff 50%,#dce8ff 0%) !important;
               font-family:'Segoe UI',monospace !important; color:#1a1a2e !important; }
        .pn-card { background:linear-gradient(135deg,#ffffff 0%,#e8eeff 100%) !important;
                   border:1px solid rgba(21,101,192,0.35) !important; border-radius:12px !important; }
        .bk-root { background:transparent !important; }
        h2,h3 { font-family:'Segoe UI',monospace !important; color:#1a1a2e !important; }
    """,
}

# Start with dark theme
THEME = DARK_THEME
pn.config.raw_css = [THEME["css"]]

# ─────────────────────────────────────────────────────────────
# MQTT CONFIG
# ─────────────────────────────────────────────────────────────
MQTT_BROKER    = "4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud"
MQTT_PORT      = 8883
MQTT_KEEPALIVE = 60
MQTT_USERNAME  = "Cyber_Alchemy"
MQTT_PASSWD    = "P@ss123456"

TEAM_ID    = "TheCyberAlchemists"
BASE       = f"epg317e/solar/{TEAM_ID}"
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
# SENSOR STATE
# ─────────────────────────────────────────────────────────────
class SensorState(param.Parameterized):
    temperature   = param.Number(default=0.0,  bounds=(-40, 100),  doc="Temperature (°C)")
    humidity      = param.Number(default=0.0,  bounds=(0, 100),    doc="Relative humidity (%)")
    lux           = param.Number(default=0.0,  bounds=(0, 200000), doc="Light intensity (lux)")
    servo_pan     = param.Number(default=90.0, bounds=(0, 180),    doc="Pan angle (°)")
    servo_tilt    = param.Number(default=45.0, bounds=(0, 90),     doc="Tilt angle (°)")
    battery       = param.Number(default=0.0,  bounds=(0, 5),      doc="Battery voltage (V)")
    connected     = param.Boolean(default=False)
    last_seen     = param.String(default="waiting...")
    tracking_mode = param.String(default="Automatic", doc="'Automatic' or 'Manual'")
    manual_pan    = param.Number(default=90.0, bounds=(0, 180))
    manual_tilt   = param.Number(default=45.0, bounds=(0, 90))

    def __init__(self, **params):
        super().__init__(**params)
        self.current_batch: set = set()
        self.param.watch(
            self._on_sensor_update,
            ['temperature', 'humidity', 'lux', 'servo_pan', 'servo_tilt', 'battery']
        )

    def _on_sensor_update(self, event):
        self.current_batch.add(event.name)
        if BATCH_KEYS.issubset(self.current_batch):
            self._commit_to_db()
            self.current_batch.clear()
            self.last_seen = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _commit_to_db(self):
        try:
            store_mqtt_reading({
                "temperature":   self.temperature,
                "humidity":      self.humidity,
                "light":         self.lux,
                "servo_pan":     self.servo_pan,
                "servo_tilt":    self.servo_tilt,
                "battery":       self.battery,
                "tracking_mode": self.tracking_mode,
            })
            logger.info(f"Reading saved at {self.last_seen} [{self.tracking_mode}]")
        except Exception as e:
            logger.error(f"DB write error: {e}")

    def fetch_history(self, hours: int) -> pd.DataFrame:
        try:
            df = load_readings_last_n_hours_to_df(hours=hours)
            if not df.empty and "light" in df.columns:
                df = df.rename(columns={"light": "lux"})
            return df
        except Exception as e:
            logger.error(f"DB read error: {e}")
            return pd.DataFrame()

sensor_state  = SensorState()
message_queue: queue.Queue = queue.Queue()


# ─────────────────────────────────────────────────────────────
# GAUGE HELPER
# ─────────────────────────────────────────────────────────────
def create_gauge(value: float, max_value: float, color: str, track_color: str) -> figure:
    p = figure(width=320, height=180, toolbar_location=None, tools="", min_border=10)
    p.background_fill_color = p.border_fill_color = p.outline_line_color = None
    p.grid.visible = p.axis.visible = False
    angle = (value / max_value) * math.pi if max_value > 0 else 0
    bg = [i * math.pi / 50 for i in range(51)]
    p.line([0.75 * math.cos(a) for a in bg], [0.75 * math.sin(a) for a in bg],
           line_width=14, color=track_color, alpha=0.15)
    if angle > 0:
        fg = [i * angle / 25 for i in range(26)]
        p.line([0.75 * math.cos(a) for a in fg], [0.75 * math.sin(a) for a in fg],
               line_width=14, color=color, alpha=0.95)
    p.scatter(0, 0, size=24, marker="circle", fill_color=color, line_color=color, alpha=0.85)
    p.x_range.start, p.x_range.end = -1.05, 1.05
    p.y_range.start, p.y_range.end = -0.25, 1.05
    return p


# ─────────────────────────────────────────────────────────────
# REACTIVE GAUGE VIEWS
# Each function reads THEME at render time, so rebuilding the
# layout after a theme swap gives fresh colours automatically.
# ─────────────────────────────────────────────────────────────
@param.depends(sensor_state.param.temperature)
def view_temp_gauge(_=None):
    v  = sensor_state.temperature
    tc = THEME["accent_orange"]
    return pn.Column(
        pn.pane.HTML(f"<h2 style='text-align:center;margin:0;color:{tc};'>{v:.1f} \u00b0C</h2>"),
        pn.pane.Bokeh(create_gauge(v, 100, tc, THEME["gauge_track"]),
                      sizing_mode="stretch_width", height=180),
    )

@param.depends(sensor_state.param.humidity)
def view_hum_gauge(_=None):
    v  = sensor_state.humidity
    tc = THEME["accent"]
    return pn.Column(
        pn.pane.HTML(f"<h2 style='text-align:center;margin:0;color:{tc};'>{v:.1f} %</h2>"),
        pn.pane.Bokeh(create_gauge(v, 100, tc, THEME["gauge_track"]),
                      sizing_mode="stretch_width", height=180),
    )

@param.depends(
    sensor_state.param.servo_pan,
    sensor_state.param.manual_pan,
    sensor_state.param.tracking_mode,
)
def view_pan_gauge(_=None, _mp=None, _tm=None):
    is_manual = sensor_state.tracking_mode == "Manual"
    v  = sensor_state.manual_pan if is_manual else sensor_state.servo_pan
    tc = THEME["accent"]
    badge = (
        f"<span style='font-size:0.55em;background:{tc};color:#fff;"
        f"padding:2px 8px;border-radius:8px;margin-left:8px;vertical-align:middle;'>MANUAL</span>"
        if is_manual else ""
    )
    return pn.Column(
        pn.pane.HTML(f"<h2 style='text-align:center;margin:0;color:{tc};'>{v:.0f} \u00b0{badge}</h2>"),
        pn.pane.Bokeh(create_gauge(v, 180, tc, THEME["gauge_track"]),
                      sizing_mode="stretch_width", height=180),
    )

@param.depends(
    sensor_state.param.servo_tilt,
    sensor_state.param.manual_tilt,
    sensor_state.param.tracking_mode,
)
def view_tilt_gauge(_=None, _mt=None, _tm=None):
    is_manual = sensor_state.tracking_mode == "Manual"
    v  = sensor_state.manual_tilt if is_manual else sensor_state.servo_tilt
    tc = THEME["accent_lime"]
    badge = (
        f"<span style='font-size:0.55em;background:{tc};color:#fff;"
        f"padding:2px 8px;border-radius:8px;margin-left:8px;vertical-align:middle;'>MANUAL</span>"
        if is_manual else ""
    )
    return pn.Column(
        pn.pane.HTML(f"<h2 style='text-align:center;margin:0;color:{tc};'>{v:.0f} \u00b0{badge}</h2>"),
        pn.pane.Bokeh(create_gauge(v, 90, tc, THEME["gauge_track"]),
                      sizing_mode="stretch_width", height=180),
    )

@param.depends(sensor_state.param.battery)
def view_battery(_=None):
    v = sensor_state.battery
    c = "#00ff41" if v >= 3.5 else "#ffcc00" if v >= 3.0 else "#ff4444"
    return pn.pane.HTML(
        f"<div style='text-align:center;padding:12px;'>"
        f"<span style='font-size:2rem;color:{c};'>&#x1F50B; {v:.2f} V</span></div>"
    )

# TIME FILTER & BOUND CHARTS

time_filter = pn.widgets.RadioButtonGroup(
    name='Historical Range',
    options={'1 Hour': 1, '6 Hours': 6, '24 Hours': 24, '7 Days': 168},
    value=1, button_type='primary', sizing_mode="stretch_width",
)

def build_env_chart(hours, last_seen):
    df = sensor_state.fetch_history(hours)
    if df.empty or len(df) < 2:
        return pn.pane.Markdown("*Waiting for data...*")
    return df.hvplot.line(
        x="timestamp", y=["temperature", "humidity"],
        title="Environment Trends",
        color=[THEME["accent_orange"], THEME["accent"]],
        line_width=2, responsive=True, height=300,
    )

def build_tracking_chart(hours, last_seen):
    df = sensor_state.fetch_history(hours)
    if df.empty or len(df) < 2:
        return pn.pane.Markdown("*Waiting for data...*")
    return df.hvplot.step(
        x="timestamp", y=["servo_pan", "servo_tilt"],
        title="Solar Tracking History",
        color=[THEME["accent"], THEME["accent_lime"]],
        line_width=2, responsive=True, height=300,
    )

bound_env      = pn.bind(build_env_chart,hours=time_filter, last_seen=sensor_state.param.last_seen)
bound_tracking = pn.bind(build_tracking_chart, hours=time_filter, last_seen=sensor_state.param.last_seen)


# PERSISTENT METRICS TABLE
# ─────────────────────────────────────────────────────────────
metrics_table = pn.widgets.Tabulator(
    pd.DataFrame({"Metric": ["--"], "Value": ["--"], "Tracking Mode": ["--"]}),
    show_index=False, disabled=True,
    widths={"Metric": 150, "Value": 150, "Tracking Mode": 120},
    sizing_mode="stretch_width", height=280,
    theme="midnight",
)

def update_metrics_table(event=None):
    is_manual = sensor_state.tracking_mode == "Manual"
    pan_val   = sensor_state.manual_pan  if is_manual else sensor_state.servo_pan
    tilt_val  = sensor_state.manual_tilt if is_manual else sensor_state.servo_tilt
    mode_str  = sensor_state.tracking_mode
    metrics_table.value = pd.DataFrame({
        "Metric": ["Temperature", "Humidity", "Lux", "Pan Angle", "Tilt Angle", "Battery", "Last Update"],
        "Value": [
            f"{sensor_state.temperature:.1f} C",
            f"{sensor_state.humidity:.1f} %RH",
            f"{sensor_state.lux:.0f} lux",
            f"{pan_val:.1f} deg",
            f"{tilt_val:.1f} deg",
            f"{sensor_state.battery:.2f} V",
            sensor_state.last_seen,
        ],
        "Tracking Mode": [mode_str] * 7,
    })

sensor_state.param.watch(update_metrics_table,
                         ['last_seen', 'tracking_mode', 'manual_pan', 'manual_tilt'])
update_metrics_table()


# ─────────────────────────────────────────────────────────────
# CONNECTION STATUS WIDGET
# ─────────────────────────────────────────────────────────────
display_conn = pn.widgets.StaticText(
    name="SYSTEM STATUS", value="Connecting...", sizing_mode="stretch_width"
)

@param.depends(sensor_state.param.connected, watch=True)
def _update_conn_display(_=None):
    display_conn.value = (
        f"ONLINE -- Connected to {MQTT_BROKER}" if sensor_state.connected
        else f"OFFLINE -- reconnecting to {MQTT_BROKER}..."
    )


# ─────────────────────────────────────────────────────────────
# CONTROL WIDGETS
# Created once and reused across theme rebuilds so slider
# positions and switch state are preserved after toggling.
# ─────────────────────────────────────────────────────────────
control_switch_mode = pn.widgets.Switch(name="Auto-Tracking Mode", value=True)
control_pan  = pn.widgets.IntSlider(name="Manual Pan Angle",  start=0, end=180, step=1, value=90)
control_tilt = pn.widgets.IntSlider(name="Manual Tilt Angle", start=0, end=90,  step=1, value=45)
btn_led      = pn.widgets.Button(name="TOGGLE LED",          button_type="primary", sizing_mode="stretch_width")
btn_buzzer   = pn.widgets.Button(name="SOUND BUZZER",        button_type="warning",  sizing_mode="stretch_width")
btn_theme    = pn.widgets.Button(name="Light Theme",         button_type="light",    sizing_mode="stretch_width")

manual_pane = pn.Column(
    pn.layout.Divider(),
    pn.pane.Markdown("**MANUAL POSITIONING**", styles={"color": THEME["accent"]}),
    control_pan,
    control_tilt,
    visible=False,
)

def publish_command(topic_key: str, payload: str) -> None:
    if sensor_state.connected:
        client.publish(CONTROL_TOPICS[topic_key], str(payload))
        log_command(topic_key, payload, sent_by="operator")
        logger.info(f"Command -> {topic_key}: {payload}")
    else:
        logger.warning(f"Command dropped (not connected): {topic_key}={payload}")

def on_mode_switch(event):
    auto = event.new
    manual_pane.visible = not auto
    sensor_state.tracking_mode = "Automatic" if auto else "Manual"
    publish_command("tracking_mode", "AUTO" if auto else "MANUAL")

control_switch_mode.param.watch(on_mode_switch, 'value')

def on_pan_change(event):
    sensor_state.manual_pan = float(event.new)
    publish_command("servo_pan", str(event.new))

def on_tilt_change(event):
    sensor_state.manual_tilt = float(event.new)
    publish_command("servo_tilt", str(event.new))

control_pan.param.watch(on_pan_change,   'value_throttled')
control_tilt.param.watch(on_tilt_change, 'value_throttled')
btn_led.on_click(lambda e: publish_command("led","TOGGLE"))
btn_buzzer.on_click(lambda e: publish_command("buzzer", "TRIGGER"))


# LAYOUT BUILDER FUNCTIONS
def make_card(title, color, *content):
    return pn.Card(
        *content,
        title=title,
        sizing_mode="stretch_width",
        styles={
            "background": THEME["card_bg"],
            "border":     f"2px solid {color}",
            "padding":    "10px",
        },
    )

def build_main():
    T = THEME
    return pn.Column(
        # Header
        pn.Row(
            pn.pane.Markdown(
                "# Solar Tracker Command Center ☀️",
                styles={"color": T["accent"], "text-align": "center", "margin": "0"},
            ),
            styles={
                "background":    f"linear-gradient(135deg,{T['bg']} 0%,{T['bg']} 100%)",
                "padding":       "20px",
                "border-radius": "12px",
            },
        ),
        display_conn,

        # Live sensor gauges
        pn.pane.Markdown("**LIVE SENSOR FEED**",
                         styles={"color": T["accent"], "font-weight": "700"}),
        pn.GridBox(
            make_card("TEMPERATURE", T["accent_orange"], view_temp_gauge),
            make_card("HUMIDITY",    T["accent"],view_hum_gauge),
            ncols=2, sizing_mode="stretch_width",
        ),

        # Panel orientation gauges
        pn.pane.Markdown("**PANEL ORIENTATION**",
                         styles={"color": T["accent"], "font-weight": "700"}),
        pn.GridBox(
            make_card("PAN ANGLE",  T["accent"],      view_pan_gauge),
            make_card("TILT ANGLE", T["accent_lime"], view_tilt_gauge),
            ncols=2, sizing_mode="stretch_width",
        ),

        # Battery
        pn.pane.Markdown("**BATTERY**",
                         styles={"color": T["accent"], "font-weight": "700"}),
        make_card("BATTERY VOLTAGE", T["accent_purple"], view_battery),

        # Live metrics table
        pn.pane.Markdown("**LIVE METRICS TABLE**",
                         styles={"color": T["accent"], "font-weight": "700"}),
        metrics_table,

        # Historical trends
        pn.pane.Markdown("**HISTORICAL TRENDS**",
                         styles={"color": T["accent"], "font-weight": "700"}),
        time_filter,
        pn.Column(
            pn.panel(bound_env,      sizing_mode="stretch_width", height=300),
            pn.panel(bound_tracking, sizing_mode="stretch_width", height=300),
        ),

        sizing_mode="stretch_width",
        styles={"background": T["bg"], "padding": "30px"},
    )

def build_sidebar():
    """
    Builds the sidebar using the current THEME.
    Called once at startup and again whenever the theme is toggled.
    """
    T = THEME
    return pn.Column(
        pn.Card(
            pn.Column(
                pn.pane.Markdown("**DISPLAY**", styles={"color": T["accent"]}),
                btn_theme,
                pn.layout.Divider(),
                pn.pane.Markdown("**TRACKING OVERRIDE**",  styles={"color": T["accent"]}),
                control_switch_mode,
                manual_pane,
                pn.layout.Divider(),
                pn.pane.Markdown("**ALERTS & SIGNALS**",styles={"color": T["accent"]}),
                btn_led,
                btn_buzzer,
                pn.layout.Divider(),
            ),
            title="CONTROL PANEL",
            styles={
                "background": T["card_bg"],
                "border":     f"1px solid {T['accent']}",
            },
        )
    )

# THEME TOGGLE

def toggle_theme(event):
    """
    If the current theme is dark, switch to light — otherwise switch back.
    After swapping THEME, rebuild both panels so every colour reference
    """
    global THEME

    if THEME["name"] == "dark":
        THEME = LIGHT_THEME
        btn_theme.name = "Dark Theme 🌑"
    else:
        THEME = DARK_THEME
        btn_theme.name = "Light Theme ☀"
        
    pn.config.raw_css = [THEME["css"]]
    dashboard.main[0].clear()
    dashboard.sidebar[0].clear()

    # Now safely rebuild and assign the new objects
    dashboard.main[0].objects = build_main().objects
    dashboard.sidebar[0].objects = build_sidebar().objects

    # Update the template header and accent
    dashboard.accent_base_color = THEME["accent"]
    dashboard.header_background = THEME["header_bg"]

    logger.info(f"Theme switched to {THEME['name']}")
btn_theme.on_click(toggle_theme)

# MQTT CLIENT SETUP
#******************************************************************************
try:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
except AttributeError:
    client = mqtt.Client()

def on_connect(c, userdata, flags, rc, properties=None):
    if rc == 0:
        # Use pn.state.execute to safely mutate UI-bound state from the background thread
        pn.state.execute(lambda: setattr(sensor_state, 'connected', True))
        for topic in SENSOR_TOPICS.values():
            c.subscribe(topic)
        log_event("connection", "info", f"MQTT connected to {MQTT_BROKER}")
        logger.info(f"MQTT connected to {MQTT_BROKER}")
    else:
        pn.state.execute(lambda: setattr(sensor_state, 'connected', False))
        log_event("connection", "critical", f"MQTT connection failed (rc={rc})")
        logger.error(f"MQTT connection failed rc={rc}")

def on_disconnect(c, userdata, disconnect_flags, rc, properties=None):
    # Safely update state on disconnect
    pn.state.execute(lambda: setattr(sensor_state, 'connected', False))
    log_event("connection", "warning", f"MQTT disconnected (rc={rc})")
    logger.warning(f"MQTT disconnected rc={rc}")

def on_message(c, userdata, msg):
    try:
        topic = msg.topic
        val = float(msg.payload.decode().strip())
        for key, t in SENSOR_TOPICS.items():
            if topic == t:
                # Instantly and safely update the UI directly from the MQTT thread
                pn.state.execute(lambda k=key, v=val: setattr(sensor_state, k, v))
                break
    except Exception:
        pass
    
client.on_connect    = on_connect
client.on_disconnect = on_disconnect
client.on_message    = on_message

def _start_mqtt():
    try:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWD)
        client.tls_set(tls_version=ssl.PROTOCOL_TLS)
        client.connect(MQTT_BROKER, MQTT_PORT, MQTT_KEEPALIVE)
        client.loop_forever()
    except Exception as e:
        logger.error(f"MQTT thread error: {e}")
        sensor_state.connected = False

threading.Thread(target=_start_mqtt, daemon=True).start()

# MESSAGE PROCESSING LOOP

def process_messages():
    try:
        while True:
            topic, payload = message_queue.get_nowait()
            try:
                val = float(payload)
            except ValueError:
                continue
            for key, t in SENSOR_TOPICS.items():
                if topic == t:
                    setattr(sensor_state, key, val)
                    break
    except queue.Empty:
        pass

pn.state.add_periodic_callback(process_messages, period=500)


# BACKGROUND TASKS (FIX FOR .SHOW() COMPATIBILITY)

def _start_background_tasks():
    # This ensures the loops only start after the UI is fully loaded
   # pn.state.add_periodic_callback(_simulate_tick, period=1000)
    pn.state.add_periodic_callback(process_messages, period=250)

pn.state.onload(_start_background_tasks)


# DASHBOARD TEMPLATE

dashboard = pn.template.FastListTemplate(
    title="IoT Solar Tracker",
    accent_base_color=THEME["accent"],
    header_background=THEME["name"],
    theme=THEME["name"],
    main_max_width="1600px",
    sidebar=[build_sidebar()],
    main=[build_main()],
)
# DISPLAY DASHBOARD 
if __name__ == "__main__":
    dashboard.show()
else:
    dashboard.servable()
