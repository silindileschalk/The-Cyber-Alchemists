 ******Solar Tracker IoT System******

Capstone Project — The Cyber Alchemists

 ******Project Overview******

This project is an IoT-enabled solar tracking system built using an ESP32 microcontroller. It automatically aligns a solar panel toward the highest light intensity using LDR sensors and servo motors while providing real-time environmental monitoring and remote control via MQTT.

The system integrates sensor data acquisition, actuator control, and cloud communication to simulate a smart renewable energy optimization solution.


 ******Features******
 Automatic solar tracking (dual-axis control)
 Manual override mode via MQTT dashboard
 Temperature & humidity monitoring (DHT11)
 Light intensity measurement (BH1750)
 Battery voltage monitoring via voltage divider
 Real-time MQTT communication (secure TLS)
 LCD live system status display
 Remote buzzer control
 LED toggle control
 Auto-reconnect WiFi & MQTT handling
 System Architecture


******The system operates in two modes:******

1. ******AUTO MODE******
LDR sensors detect light imbalance
Servo motors adjust panel position
Continuous optimization of solar alignment
2. MANUAL MODE
Dashboard sends commands via MQTT
User directly controls:
Servo pan angle
Servo tilt angle
LED state
Buzzer activation
 ******Hardware Components******
ESP32 Development Board
2x Servo Motors (Pan & Tilt)
4x LDR Light Sensors
DHT11 Temperature & Humidity Sensor
BH1750 Light Intensity Sensor
LCD I2C Display (16x2)
Buzzer

Voltage Divider Circuit (Battery Monitoring)
 ******Software & Libraries Used******
WiFi.h (ESP32 networking)
PubSubClient.h (MQTT communication)
Wire.h (I2C communication)
LCD_I2C.h (LCD display control)
ESP32Servo.h (servo motor control)
DHT11.h (temperature & humidity sensor)
BH1750.h (light sensor)
WiFiClientSecure.h (TLS MQTT security)
 ******MQTT Communication
Broker******

HiveMQ Cloud (secure TLS connection)

 ******Published Topics (ESP32 → Dashboard)******
sensors/temperature
sensors/humidity
sensors/lux
sensors/battery
actuators/servo_pan
actuators/servo_tilt
 ******Subscribed Topics (Dashboard → ESP32)******
control/tracking_mode → AUTO / MANUAL switch
control/servo_pan → manual pan control
control/servo_tilt → manual tilt control
control/led → LED toggle
control/buzzer → buzzer trigger
******System Workflow******
ESP32 boots and connects to WiFi
Secure MQTT connection established
Sensors begin continuous data sampling
Data is published every second
Dashboard sends control commands via MQTT
ESP32 updates actuators in real-time
LCD displays system status continuously
 ******Key Design Decisions******
 Modular Architecture

The code is split into functions:

readSensors()
updateTracking()
updateDisplay()
connectMqtt()

This improves readability, debugging, and scalability.

 Safety & Robustness
Sensor failure handling (DHT returns -1)
Servo angle constraints (0–180°, 0–90°)
MQTT auto-reconnect logic
WiFi blocking loop only at startup
 Real-Time System Behavior
Non-blocking MQTT loop
Timed publishing using millis()
No delay-heavy logic in main loop
 Hybrid Control System

Combines:

Autonomous solar optimization (AUTO)
Human override via dashboard (MANUAL)
 ******Performance Summary******
Update rate: ~1 second telemetry
Control latency: near real-time (MQTT dependent)
Tracking accuracy: based on LDR differential threshold
System stability: improved via reconnection logic
 ******Installation & Setup******
1. Clone Project
git clone https://github.com/your-repo/solar-tracker
2. Install Arduino Libraries

Install via Library Manager:

PubSubClient
ESP32Servo
BH1750
DHT11
LCD_I2C
3. Configure WiFi & MQTT

Edit:

WIFI_SSID
WIFI_PASSWORD
MQTT_BROKER
MQTT_USER
MQTT_PASS
4. Upload to ESP32

Select:

Board: ESP32 Dev Module
Baud: 115200
 ******Testing Procedure******
Verify WiFi connection on Serial Monitor
Confirm MQTT connection logs
Shine light on LDR sensors → observe servo movement
Switch AUTO/MANUAL via dashboard
Trigger LED and buzzer remotely
Check live LCD updates
 ******Known Limitations******
DHT11 has low accuracy and slow response
LDR calibration depends on physical placement
MQTT dependency requires stable internet
Servo jitter may occur under noisy sensor input
==> ***Author***

The Cyber Alchemists
EPG317E Capstone Team
Central University of Technology

 License: For academic use only.
