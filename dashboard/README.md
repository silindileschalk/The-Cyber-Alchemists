# ☀️ Solar Tracker Dashboard

A real-time IoT monitoring and control interface built with **Python**, **Panel**, and **MQTT**. This dashboard is designed to interface with an ESP32-powered solar tracking system, providing live telemetry visualization and remote actuator control.

## 🚀 Features

### 📊 Real-Time Visualization
* **Sensor Trend Cards:** Live sparklines and percentage changes for Temperature, Humidity, Light Intensity (Lux), and Battery Voltage.
* **Historical Trends:** Dynamic line and area charts showing the last 20 readings using `hvplot`.
* **Summary Table:** A consolidated `Tabulator` view of all system states and timestamps.
* **Orientation Tracking:** High-visibility indicators for current servo pan and tilt angles.

### 🎮 Remote Control
* **Tracking Mode:** Toggle between manual and autonomous light-seeking modes.
* **Manual Overrides:** Precise sliders to adjust pan (0-180°) and tilt (0-90°) angles.
* **Actuators:** Remote triggers for onboard LEDs and buzzers.
* **Sensitivity Tuning:** Real-time adjustment of the Lux threshold for auto-tracking activation.

### 📋 System Monitoring
* **MQTT Logs:** Dual-window log system tracking incoming sensor data and outgoing commands.
* **Connection Status:** Real-time feedback on the broker connection state and heartbeat.

## 🛠 Tech Stack
* **Framework:** [Panel](https://panel.holoviz.org/)
* **Communication:** [Paho-MQTT](https://pypi.org/project/paho-mqtt/)
* **Data Handling:** [Pandas](https://pandas.pydata.org/)
* **Plotting:** [hvPlot](https://hvplot.holoviz.org/) & [HoloViews](https://holoviz.org/)

## 📦 Installation

1. **Clone the repository:**
   ```bash
   git clone [https://github.com/yourusername/solar-tracker-dashboard.git](https://github.com/yourusername/solar-tracker-dashboard.git)
   cd solar-tracker-dashboard
