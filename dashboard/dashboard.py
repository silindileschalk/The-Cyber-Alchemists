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
import logging
import queue
from datetime import datetime
from collections import deque
from typing import Optional, Dict, Callable, Tuple, Any

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
CONNECTION_OK = "✅ Connected"
CONNECTION_FAILED = "❌ Connection failed"
CONNECTION_DISCONNECTED = "⚠️ Disconnected — retrying…"
CONNECTION_ERROR = "❌ MQTT error"
WAITING_FOR_DATA = "Waiting for data from ESP32..."
WAITING_FOR_ESP32 = "Waiting for ESP32…"
MQTT_KEEPALIVE = 60

# Control Values
TRACKING_ON = "ON"
TRACKING_OFF = "OFF"
LED_ON = "ON"
LED_OFF = "OFF"
BUZZER_TRIGGER = "TRIGGER"

# Sensor Bounds for Validation
SENSOR_BOUNDS = {
    "temperature": (-50, 150),  # °C
    "humidity": (0, 100),       # %
    "lux": (0, 100000),         # lux
    "battery": (0, 5),          # V
    "servo_pan": (0, 180),      # degrees
    "servo_tilt": (0, 90),      # degrees
}

# Topics the ESP32 publishes sensor readings to
SENSOR_TOPICS = {
    "temperature": f"{BASE}/sensors/temperature",
    "humidity": f"{BASE}/sensors/humidity",
    "lux": f"{BASE}/sensors/lux",
    "battery": f"{BASE}/sensors/battery",
    "servo_pan": f"{BASE}/actuators/servo_pan",
    "servo_tilt": f"{BASE}/actuators/servo_tilt",
    "tracking": f"{BASE}/control/tracking_mode",
}

# Topics the dashboard publishes commands to
COMMAND_TOPICS = {
    "tracking": f"{BASE}/control/tracking_mode",
    "led": f"{BASE}/control/led",
    "buzzer": f"{BASE}/control/buzzer",
    "servo_pan": f"{BASE}/actuators/servo_pan",
    "servo_tilt": f"{BASE}/actuators/servo_tilt",
    "threshold": f"{BASE}/control/lux_threshold",
}

# Colour Scheme
PALETTE = {
    "temperature": "#0F6E56",   # deep teal
    "humidity": "#185FA5",      # ocean blue
    "lux": "#BA7517",           # warm amber
    "battery": "#993556",       # berry pink
}


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
        
        # Check bounds if sensor has bounds defined
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
# SENSOR STATE CLASS
# Encapsulates all live sensor data and historical readings
# ─────────────────────────────────────────────────────────────
class SensorState:
    """Manages sensor readings, live state, and data buffers."""
    
    def __init__(self, max_readings: int = MAX_READINGS):
        """Initialize sensor state with rolling buffers."""
        self.max_readings = max_readings
        
        # Rolling history buffers for trend analysis
        self.readings: Dict[str, deque] = {
            "time": deque(maxlen=max_readings),
            "temperature": deque(maxlen=max_readings),
            "humidity": deque(maxlen=max_readings),
            "lux": deque(maxlen=max_readings),
            "battery": deque(maxlen=max_readings),
        }
        
        # Current live state — always holds the most recent value from ESP32
        self.live: Dict[str, Any] = {
            "temperature": 0.0,
            "humidity": 0.0,
            "lux": 0.0,
            "battery": 0.0,
            "servo_pan": 90.0,
            "servo_tilt": 45.0,
            "tracking": "unknown",
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
            "battery": list(self.readings["battery"]),
        })
    
    def update_live(self, key: str, value: Any) -> None:
        """Update a live state value."""
        self.live[key] = value
    
    def add_reading_batch(self, timestamp: str) -> None:
        """
        Add current live values to rolling buffers.
        Called when a complete sensor batch arrives (typically on temperature update).
        """
        self.readings["time"].append(timestamp)
        self.readings["temperature"].append(self.live["temperature"])
        self.readings["humidity"].append(self.live["humidity"])
        self.readings["lux"].append(self.live["lux"])
        self.readings["battery"].append(self.live["battery"])


# Initialize shared sensor state
sensor_state = SensorState()
message_queue: queue.Queue = queue.Queue()


# ─────────────────────────────────────────────────────────────
# SENSOR TREND CARDS
# Each card shows: current value, % change since last reading,
# and a mini sparkline chart — built with pn.indicators.Trend
# ─────────────────────────────────────────────────────────────
def make_trend_card(label: str, color: str, chart_style: str = "line") -> Tuple[pn.indicators.Trend, pn.Card]:
    """
    Build one sensor card with trend indicator.
    
    Args:
        label: Display name for the sensor (with emoji)
        color: Hex color code for the card styling
        chart_style: Type of chart ('line', 'area', 'bar', 'step')
        
    Returns:
        Tuple of (Trend widget, Card container)
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
            "border": f"2px solid {color}",
            "border-radius": "12px",
            "box-shadow": f"0 4px 16px {color}33",
            "padding": "10px",
        },
    )
    return trend, card


trend_temp, card_temp = make_trend_card("🌡 Temperature (°C)", PALETTE["temperature"], "line")
trend_hum, card_hum = make_trend_card("💧 Humidity (%)", PALETTE["humidity"], "area")
trend_lux, card_lux = make_trend_card("☀️ Light (lux)", PALETTE["lux"], "bar")
trend_bat, card_bat = make_trend_card("🔋 Battery (V)", PALETTE["battery"], "step")


# ─────────────────────────────────────────────────────────────
# STATUS DISPLAYS — servo angles and connection info
# ─────────────────────────────────────────────────────────────
display_pan = pn.indicators.Number(
    name="Pan angle (°)", value=0, format="{value:.0f}", font_size="28pt"
)
display_tilt = pn.indicators.Number(
    name="Tilt angle (°)", value=0, format="{value:.0f}", font_size="28pt"
)

display_mode = pn.widgets.StaticText(name="Tracking mode", value="—")
display_time = pn.widgets.StaticText(name="Last reading", value=WAITING_FOR_ESP32)
display_conn = pn.widgets.StaticText(name="Connection", value="Connecting to broker…")


# ─────────────────────────────────────────────────────────────
# LIVE CHARTS — last 20 readings as hvplot line/area charts
# ─────────────────────────────────────────────────────────────
live_chart_temp = pn.pane.HoloViews(sizing_mode="stretch_width", height=200)
live_chart_lux = pn.pane.HoloViews(sizing_mode="stretch_width", height=200)


def refresh_trend_card(trend_widget: pn.indicators.Trend, sensor_key: str) -> None:
    """
    Update a Trend card's sparkline and value from the latest readings buffer.
    
    Args:
        trend_widget: The Trend indicator widget to update
        sensor_key: The sensor key to pull data from (e.g., 'temperature')
    """
    buf = list(sensor_state.readings[sensor_key])
    if len(buf) < 2:
        return
    
    current = buf[-1]
    previous = buf[-2]
    pct_change = (current - previous) / abs(previous) if previous != 0 else 0.0
    
    trend_widget.data = {"x": list(range(len(buf))), "y": buf}
    trend_widget.value = round(current, 2)
    trend_widget.value_change = round(pct_change, 4)


def refresh_live_charts() -> None:
    """Redraw the temperature and lux hvplot charts from the current readings buffer."""
    df = sensor_state.to_dataframe()
    if len(df) < 2:
        return
    
    try:
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
    except Exception as e:
        logger.error(f"Error refreshing live charts: {e}")


# ─────────────────────────────────────────────────────────────
# SENSOR SUMMARY TABLE
# A Tabulator table that shows all sensors in one place.
# ─────────────────────────────────────────────────────────────
summary_table = pn.widgets.Tabulator(
    pd.DataFrame({
        "Sensor": ["Temperature", "Humidity", "Light", "Battery", "Pan", "Tilt", "Tracking"],
        "Reading": ["—"] * 7,
        "Unit": ["°C", "%", "lux", "V", "°", "°", "—"],
        "Last updated": ["—"] * 7,
    }),
    show_index=False,
    disabled=True,
    widths={"Sensor": 120, "Reading": 90, "Unit": 55, "Last updated": 100},
    sizing_mode="stretch_width",
    height=280,
)


def refresh_summary_table() -> None:
    """Push the latest live values into the summary table."""
    now = sensor_state.live["last_seen"]
    summary_table.value = pd.DataFrame({
        "Sensor": ["Temperature", "Humidity", "Light", "Battery", "Pan", "Tilt", "Tracking"],
        "Reading": [
            f"{sensor_state.live['temperature']:.1f}",
            f"{sensor_state.live['humidity']:.0f}",
            f"{sensor_state.live['lux']:.0f}",
            f"{sensor_state.live['battery']:.2f}",
            f"{sensor_state.live['servo_pan']:.0f}",
            f"{sensor_state.live['servo_tilt']:.0f}",
            sensor_state.live["tracking"].upper(),
        ],
        "Unit": ["°C", "%", "lux", "V", "°", "°", "—"],
        "Last updated": [now] * 7,
    })


# ─────────────────────────────────────────────────────────────
# MQTT LOG — scrolling live feed of messages and commands
# ─────────────────────────────────────────────────────────────
incoming_log = pn.widgets.TextAreaInput(
    name="📡 Incoming sensor data",
    value=f"{WAITING_FOR_DATA}\n",
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


def log_incoming(entry: str) -> None:
    """Add a new line at the top of the incoming log."""
    lines = incoming_log.value.splitlines()
    incoming_log.value = "\n".join([entry] + lines[:MAX_LOG_LINES]) + "\n"


def log_outgoing(entry: str) -> None:
    """Add a new line at the top of the outgoing log."""
    lines = outgoing_log.value.splitlines()
    outgoing_log.value = "\n".join([entry] + lines[:MAX_LOG_LINES]) + "\n"


btn_clear_logs = pn.widgets.Button(
    name="🗑 Clear logs", button_type="danger", width=130
)


def on_clear_logs(event: Any) -> None:
    """Clear both incoming and outgoing logs."""
    incoming_log.value = "Logs cleared.\n"
    outgoing_log.value = "Logs cleared.\n"
    logger.info("Logs cleared by user")


btn_clear_logs.on_click(on_clear_logs)


# ─────────────────────────────────────────────────────────────
# CONTROL WIDGETS — buttons and sliders in the sidebar
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

# Servo sliders
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
def servo_angle_preview(pan: int, tilt: int) -> pn.pane.Markdown:
    """Show a live preview of servo angles that will be sent."""
    return pn.pane.Markdown(
        f"*Will send →* pan **{pan}°** | tilt **{tilt}°**",
        sizing_mode="stretch_width",
    )


servo_preview_pane = pn.bind(servo_angle_preview, pan=sl_pan, tilt=sl_tilt)


# ─────────────────────────────────────────────────────────────
# MQTT CLIENT SETUP
# ─────────────────────────────────────────────────────────────
try:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
except AttributeError:
    # Fallback for older paho-mqtt versions
    client = mqtt.Client()


def on_connect(c: mqtt.Client, userdata: Any, flags: Any, reason_code: int, 
               properties: Any = None) -> None:
    """Handle MQTT connection event."""
    if reason_code == 0:
        sensor_state.update_live("connected", True)
        display_conn.value = f"{CONNECTION_OK} to {BROKER}"
        logger.info(f"Connected to MQTT broker: {BROKER}")
        
        # Subscribe to all sensor topics
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
    display_conn.value = CONNECTION_DISCONNECTED
    logger.warning(f"Disconnected from MQTT broker (code {reason_code})")


def on_message(c: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
    """
    Called every time a new MQTT message arrives from the ESP32.
    Queues messages for processing on the main thread (thread-safe).
    """
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
# MESSAGE PROCESSING — handle queued MQTT messages on main thread
# ─────────────────────────────────────────────────────────────
def create_topic_handlers() -> Dict[str, Callable[[str], None]]:
    """
    Create a dispatch dictionary mapping topics to handler functions.
    More maintainable than if-elif chains.
    """
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
    
    def handle_battery(payload: str) -> None:
        value = validate_sensor_value("battery", payload)
        if value is not None:
            sensor_state.update_live("battery", value)
    
    def handle_servo_pan(payload: str) -> None:
        value = validate_sensor_value("servo_pan", payload)
        if value is not None:
            sensor_state.update_live("servo_pan", value)
            display_pan.value = value
    
    def handle_servo_tilt(payload: str) -> None:
        value = validate_sensor_value("servo_tilt", payload)
        if value is not None:
            sensor_state.update_live("servo_tilt", value)
            display_tilt.value = value
    
    def handle_tracking(payload: str) -> None:
        sensor_state.update_live("tracking", payload)
        display_mode.value = payload.upper()
    
    return {
        SENSOR_TOPICS["temperature"]: handle_temperature,
        SENSOR_TOPICS["humidity"]: handle_humidity,
        SENSOR_TOPICS["lux"]: handle_lux,
        SENSOR_TOPICS["battery"]: handle_battery,
        SENSOR_TOPICS["servo_pan"]: handle_servo_pan,
        SENSOR_TOPICS["servo_tilt"]: handle_servo_tilt,
        SENSOR_TOPICS["tracking"]: handle_tracking,
    }


topic_handlers = create_topic_handlers()


def process_queued_messages() -> None:
    """
    Process all queued MQTT messages.
    Called periodically on the main thread (thread-safe).
    """
    try:
        while True:
            topic, payload = message_queue.get(timeout=MESSAGE_QUEUE_TIMEOUT)
            
            # Route to appropriate handler
            if topic in topic_handlers:
                topic_handlers[topic](payload)
            else:
                logger.warning(f"Unknown topic: {topic}")
            
            # Timestamp the message
            timestamp = get_timestamp()
            sensor_state.update_live("last_seen", timestamp)
            display_time.value = timestamp
            
            # Log the incoming message
            sensor_name = topic.split("/")[-1]
            log_incoming(f"[{timestamp}]  {sensor_name}: {payload}")
            
            # On temperature reading (sync signal), update all displays
            # Temperature is used as the sync signal because the ESP32 sends
            # all sensors together — temperature always arrives last in the sequence.
            if topic == SENSOR_TOPICS["temperature"]:
                sensor_state.add_reading_batch(timestamp)
                
                refresh_trend_card(trend_temp, "temperature")
                refresh_trend_card(trend_hum, "humidity")
                refresh_trend_card(trend_lux, "lux")
                refresh_trend_card(trend_bat, "battery")
                refresh_live_charts()
                refresh_summary_table()
    
    except queue.Empty:
        pass
    except Exception as e:
        logger.error(f"Error processing queued message: {e}")


# Schedule message processing on the main thread
pn.state.add_periodic_callback(process_queued_messages, period=100)


# ─────────────────────────────────────────────────────────────
# CONTROL CALLBACKS
# ─────────────────────────────────────────────────────────────
def send_command(topic: str, payload: Any) -> None:
    """
    Publish a command to the ESP32. Warns if not connected.
    
    Args:
        topic: MQTT topic to publish to
        payload: Message payload to send
    """
    if sensor_state.live["connected"]:
        try:
            client.publish(topic, str(payload), qos=1)
            logger.info(f"Published to {topic}: {payload}")
        except Exception as e:
            logger.error(f"Error publishing command: {e}")
    else:
        logger.warning("Not connected to MQTT broker — command not sent")


def make_toggle_handler(button: pn.widgets.Toggle, topic: str, label: str, 
                       on_value: str, off_value: str) -> Callable:
    """
    Factory function to create a toggle button handler.
    Reduces code duplication for similar toggle behaviors.
    
    Args:
        button: The toggle button widget
        topic: MQTT topic to publish to
        label: Display label for the button
        on_value: Value to send when toggle is ON
        off_value: Value to send when toggle is OFF
        
    Returns:
        Handler function for the toggle event
    """
    def handler(event: Any) -> None:
        val = on_value if event.new else off_value
        send_command(topic, val)
        button.name = f"{label}: {val}"
        log_outgoing(f"[{get_timestamp()}]  {label} → {val}")
    
    return handler


def on_buzzer_click(event: Any) -> None:
    """Handle buzzer button click."""
    send_command(COMMAND_TOPICS["buzzer"], BUZZER_TRIGGER)
    log_outgoing(f"[{get_timestamp()}]  buzzer → {BUZZER_TRIGGER}")


def on_send_servo(event: Any) -> None:
    """Handle servo send button click."""
    send_command(COMMAND_TOPICS["servo_pan"], sl_pan.value)
    send_command(COMMAND_TOPICS["servo_tilt"], sl_tilt.value)
    log_outgoing(
        f"[{get_timestamp()}]  servo → pan={sl_pan.value}°  tilt={sl_tilt.value}°"
    )


def on_send_threshold(event: Any) -> None:
    """Handle threshold send button click."""
    send_command(COMMAND_TOPICS["threshold"], sl_threshold.value)
    log_outgoing(
        f"[{get_timestamp()}]  lux threshold → {sl_threshold.value} lx"
    )


# Attach handlers to widgets
btn_tracking.param.watch(
    make_toggle_handler(btn_tracking, COMMAND_TOPICS["tracking"], 
                       "🔄 Auto-tracking", TRACKING_ON, TRACKING_OFF),
    "value"
)
btn_led.param.watch(
    make_toggle_handler(btn_led, COMMAND_TOPICS["led"], 
                       "💡 LED", LED_ON, LED_OFF),
    "value"
)
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
        pn.Column(pn.pane.Markdown("**Last reading**"), display_time),
        pn.Column(pn.pane.Markdown("**Broker status**"), display_conn),
    ),

    pn.pane.Markdown("## All Sensors at a Glance"),
    summary_table,

    pn.pane.Markdown("## Trends — last 20 readings"),
    pn.Row(live_chart_temp, live_chart_lux),
)


# ─────────────────────────────────────────────────────────────
# LAYOUT — sidebar (controls + logs)
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
    title="☀️ Solar Tracker Dashboard ☀️",
    accent_base_color="#0F6E56",
    header_background="#0F6E56",
    theme="dark",
    theme_toggle=True,
    main_max_width="1400px",
    sidebar=sidebar_content,
    main=[main_content],
)

logger.info("Dashboard initialized and ready to display")
dashboard.show()
