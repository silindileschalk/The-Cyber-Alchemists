
☀️ Solar Tracker IoT System
Capstone Project — The Cyber Alchemists

📌 Project Overview
This project is an IoT-enabled solar tracking system built using an ESP32 microcontroller. The system automatically aligns a solar panel toward the highest light intensity using LDR sensors and servo motors, improving energy efficiency.
In addition to autonomous tracking, the system provides real-time monitoring and remote control through a Python-based dashboard using MQTT communication. The project demonstrates the integration of embedded systems, cloud communication, and data visualisation to simulate a smart renewable energy optimisation solution.

🚀 Key Features
🔄 Automatic Tracking

Dual-axis solar tracking (pan & tilt)
Uses LDR sensors to detect maximum light direction
Continuous adjustment for optimal alignment

🎮 Remote Control

Switch between AUTO and MANUAL modes
Adjust servo angles via dashboard
Toggle LED remotely
Trigger buzzer alerts

📊 Real-Time Monitoring

Temperature & humidity monitoring (DHT11)
Light intensity measurement (BH1750 + LDRs)
Battery voltage monitoring (voltage divider)
Live telemetry updates via MQTT

📟 Local System Feedback

LCD display showing live system data
Real-time actuator position feedback
Serial debugging output


🖥️ Dashboard Features
📊 Visualisation

Real-time sensor data trends
Historical data plots (last 20 readings)
Summary tables of system state
Servo orientation indicators

🎛️ Controls

Mode selection (AUTO / MANUAL)
Servo position sliders
LED and buzzer controls
Sensitivity tuning for tracking

📋 Monitoring

MQTT logs (incoming and outgoing messages)
Connection status tracking
System heartbeat monitoring


🛠 Tech Stack
Hardware:

ESP32 Development Board
Servo Motors (Pan & Tilt)
LDR Sensors
DHT11 Sensor
BH1750 Sensor
LCD I2C Display
Buzzer, LED, Push Button

Software & Libraries:

WiFi.h
PubSubClient.h (MQTT)
ESP32Servo.h
DHT11.h
BH1750.h
LCD_I2C.h

Dashboard:

Panel
Paho-MQTT
Pandas
hvPlot & HoloViews


🔌 System Architecture
The system follows a layered IoT architecture:
ESP32 → MQTT Broker → Python Backend → SQLite Database → Panel Dashboard → Cloud
Operation Modes
AUTO MODE

LDR sensors detect light imbalance
Servo motors adjust position automatically
Continuous optimisation of panel alignment

MANUAL MODE

Dashboard sends commands via MQTT
User directly controls actuators
Overrides automatic tracking


📡 MQTT Communication
Broker: HiveMQ Cloud (TLS secured)
📤 Published (ESP32 → Dashboard)

sensors/temperature
sensors/humidity
sensors/lux
sensors/battery
actuators/servo_pan
actuators/servo_tilt

📥 Subscribed (Dashboard → ESP32)

control/tracking_mode
control/servo_pan
control/servo_tilt
control/led
control/buzzer


⚙️ System Workflow

ESP32 connects to WiFi
MQTT secure connection established
Sensors begin continuous data collection
Data is published periodically (≈1 sec)
Dashboard subscribes and displays data
User sends commands from dashboard
ESP32 updates actuators in real-time
LCD displays system status locally


🧠 Key Design Decisions
✅ Modular Firmware

Separate functions for reading sensors, tracking logic, display, and communication
Improves maintainability and debugging

✅ Real-Time Processing

Non-blocking loop using millis()
Continuous MQTT communication
Smooth servo movement implementation

✅ Hybrid Control System

Autonomous optimisation + manual override
Flexible system behaviour

✅ Reliability

MQTT auto-reconnect
WiFi reconnection handling
Servo constraints for safety


📊 Performance Summary

Update rate: ~1 second
Control latency: Near real-time (MQTT dependent)
Tracking accuracy: Based on LDR threshold comparison
System stability: Improved with reconnection logic and smoothing


📦 Installation & Setup
1. Clone Repository
Shellgit clone https://github.com/silindileschalk/The-Cyber-Alchemists.gitcd The-Cyber-AlchemistsShow more lines
2. Install Required Libraries
Install using Arduino Library Manager:

PubSubClient
ESP32Servo
BH1750
DHT11
LCD_I2C

3. Configure Credentials
Update the following in code:

WIFI_SSID
WIFI_PASSWORD
MQTT_BROKER
MQTT_USER
MQTT_PASS

4. Upload to ESP32

Board: ESP32 Dev Module
Baud Rate: 115200


🧪 Testing Procedure

Verify WiFi connection via Serial Monitor
Confirm MQTT connection logs
Shine light on sensors → observe servo movement
Switch AUTO/MANUAL modes from dashboard
Test LED and buzzer controls
Verify live LCD updates


⚠️ Known Limitations

DHT11 provides low accuracy and slow response
LDR calibration depends on placement
System depends on stable internet (MQTT)
Hardware changes can affect system stability
Servo jitter may occur due to noisy sensor input


🔮 Future Improvements

Use higher accuracy sensors (e.g. DHT22)
Add filtering for sensor noise
Improve MQTT reliability and security
Expand to real solar panel applications
Cloud deployment with scalable database


👥 Authors
## The Cyber Alchemist
# Members and student numbers
223009193 S Schalk
223051755 SI NTULI
224055563 L Matsimela
223085157 LT Mbazima
222009085 HE Mulibana
EPG317E Capstone Team
Central University of Technology, Free State

📜 License
For academic use only
