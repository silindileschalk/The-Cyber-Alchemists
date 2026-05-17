// The Cyber Alchemists
// EPG317E Capstone Project
// ESP32 Solar Tracker Code aligned with the Python Dashboard

#include <WiFi.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <LCD_I2C.h>
#include <ESP32Servo.h>
#include <DHT11.h>
#include <BH1750.h>
#include <WiFiClientSecure.h>

// ─────────────────────────────────────────────────────────────
// WIFI CONFIG
// ─────────────────────────────────────────────────────────────
const char* WIFI_SSID     = "The Cyber Alchemists IoT";
const char* WIFI_PASSWORD = "Cy13ER123";

// ─────────────────────────────────────────────────────────────
// MQTT CONFIG
// Must match dashboard.py
// ─────────────────────────────────────────────────────────────
const char* MQTT_BROKER   = "4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud";
const int   MQTT_PORT     = 8883;
const char* MQTT_USERNAME = "Cyber_Alchemy";
const char* MQTT_PASSWD   = "P@ss123456";

// ─────────────────────────────────────────────────────────────
// MQTT TOPICS: ESP32 → Dashboard
// ─────────────────────────────────────────────────────────────
const char* T_TEMP    = "epg317e/solar/TheCyberAlchemists/sensors/temperature";
const char* T_HUM     = "epg317e/solar/TheCyberAlchemists/sensors/humidity";
const char* T_LUX     = "epg317e/solar/TheCyberAlchemists/sensors/lux";
const char* T_BATTERY = "epg317e/solar/TheCyberAlchemists/sensors/battery";
const char* T_PAN_FB  = "epg317e/solar/TheCyberAlchemists/actuators/servo_pan";
const char* T_TILT_FB = "epg317e/solar/TheCyberAlchemists/actuators/servo_tilt";

// ─────────────────────────────────────────────────────────────
// MQTT TOPICS: Dashboard → ESP32
// ─────────────────────────────────────────────────────────────
const char* T_MODE     = "epg317e/solar/TheCyberAlchemists/control/tracking_mode";
const char* T_PAN_CMD  = "epg317e/solar/TheCyberAlchemists/control/servo_pan";
const char* T_TILT_CMD = "epg317e/solar/TheCyberAlchemists/control/servo_tilt";
const char* T_LED      = "epg317e/solar/TheCyberAlchemists/control/led";
const char* T_BUZZER   = "epg317e/solar/TheCyberAlchemists/control/buzzer";

// ─────────────────────────────────────────────────────────────
// PIN DEFINITIONS
// ─────────────────────────────────────────────────────────────
#define SERVO_H   18
#define SERVO_V   19
#define BUZZER    15
#define BUTTON    2

#define LDR_BOT   34
#define LDR_TOP   35
#define LDR_LEFT  32
#define LDR_RIGHT 33

#define BATTERY   36
#define LED       27

// ─────────────────────────────────────────────────────────────
// HARDWARE OBJECTS
// ─────────────────────────────────────────────────────────────
LCD_I2C lcd(0x27, 16, 2);
DHT11 dht(4);
BH1750 lightMeter;

Servo servoHori;
Servo servoVerti;

WiFiClientSecure wifiClient;
PubSubClient mqttClient(wifiClient);

// ─────────────────────────────────────────────────────────────
// STATE VARIABLES
// ─────────────────────────────────────────────────────────────
int servoH = 90;
int servoV = 45;

int tolerance = 25;

bool autoMode = true;
bool ledState = false;
bool buzzerPulseActive = false;

unsigned long lastPublish = 0;
unsigned long lastReconnect = 0;
unsigned long buzzerStartedAt = 0;

const unsigned long PUBLISH_MS = 1000;      // Publish every 1 second
const unsigned long RECONNECT_MS = 5000;    // Retry MQTT every 5 seconds
const unsigned long BUZZER_PULSE_MS = 300;  // Buzzer pulse duration

// ─────────────────────────────────────────────────────────────
// BATTERY VOLTAGE READING
// Voltage divider: battery+ → R1 → GPIO36 → R2 → GND
// ─────────────────────────────────────────────────────────────
float readBatteryVoltage() {
  const float R1 = 100000.0;
  const float R2 = 100000.0;
  const float VREF = 3.3;
  const float ADC_MAX = 4095.0;

  int raw = analogRead(BATTERY);

  float adcVoltage = (raw / ADC_MAX) * VREF;
  float batteryVoltage = adcVoltage * ((R1 + R2) / R2);

  return batteryVoltage;
}

// ─────────────────────────────────────────────────────────────
// LCD HELPER
// Keeps each LCD line clean by padding to 16 characters
// ─────────────────────────────────────────────────────────────
void printPaddedLCD(String text) {
  while (text.length() < 16) {
    text += " ";
  }

  lcd.print(text.substring(0, 16));
}

// ─────────────────────────────────────────────────────────────
// BUZZER HELPERS
// ─────────────────────────────────────────────────────────────
void buzzerOn() {
  buzzerPulseActive = true;
  buzzerStartedAt = millis();
  digitalWrite(BUZZER, HIGH);
}

void buzzerOff() {
  buzzerPulseActive = false;
  digitalWrite(BUZZER, LOW);
}

// ─────────────────────────────────────────────────────────────
// MQTT MESSAGE RECEIVED FROM DASHBOARD
// ─────────────────────────────────────────────────────────────
void onMessage(char* topic, byte* payload, unsigned int len) {
  char msg[64];

  memset(msg, 0, sizeof(msg));
  memcpy(msg, payload, min((unsigned int)63, len));

  Serial.printf("[MQTT IN] %s -> %s\n", topic, msg);

  // Tracking mode command
  if (strcmp(topic, T_MODE) == 0) {
    if (strcmp(msg, "AUTO") == 0) {
      autoMode = true;
    }
    else if (strcmp(msg, "MANUAL") == 0) {
      autoMode = false;
    }

    lcd.setCursor(0, 0);
    printPaddedLCD(autoMode ? "Mode: AUTO" : "Mode: MANUAL");

    Serial.printf("Tracking mode: %s\n", autoMode ? "AUTO" : "MANUAL");
  }

  // Manual pan command from dashboard slider
  else if (strcmp(topic, T_PAN_CMD) == 0) {
    if (!autoMode) {
      servoH = constrain(atoi(msg), 0, 180);
      servoHori.write(servoH);

      Serial.printf("Manual pan -> %d degrees\n", servoH);
    }
  }

  // Manual tilt command from dashboard slider
  else if (strcmp(topic, T_TILT_CMD) == 0) {
    if (!autoMode) {
      servoV = constrain(atoi(msg), 0, 90);
      servoVerti.write(servoV);

      Serial.printf("Manual tilt -> %d degrees\n", servoV);
    }
  }

  // LED command from dashboard
  else if (strcmp(topic, T_LED) == 0) {
    if (strcmp(msg, "TOGGLE") == 0) {
      ledState = !ledState;
    }
    else if (strcmp(msg, "ON") == 0) {
      ledState = true;
    }
    else if (strcmp(msg, "OFF") == 0) {
      ledState = false;
    }

    digitalWrite(LED, ledState ? HIGH : LOW);

    Serial.printf("LED: %s\n", ledState ? "ON" : "OFF");
  }

  // Buzzer command from dashboard
  else if (strcmp(topic, T_BUZZER) == 0) {
    if (strcmp(msg, "TRIGGER") == 0 || strcmp(msg, "ON") == 0) {
      buzzerOn();
      Serial.println("Buzzer triggered by dashboard.");
    }
    else if (strcmp(msg, "OFF") == 0) {
      buzzerOff();
      Serial.println("Buzzer muted by dashboard.");
    }
  }
}

// ─────────────────────────────────────────────────────────────
// WIFI CONNECT
// ─────────────────────────────────────────────────────────────
void connectWiFi() {
  Serial.printf("Connecting to Wi-Fi: %s\n", WIFI_SSID);

  lcd.setCursor(0, 1);
  printPaddedLCD("WiFi connecting");

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.printf("\nWi-Fi connected. IP: %s\n", WiFi.localIP().toString().c_str());

  lcd.setCursor(0, 1);
  printPaddedLCD("WiFi: OK");
  delay(800);
}

// ─────────────────────────────────────────────────────────────
// MQTT CONNECT / RECONNECT
// ─────────────────────────────────────────────────────────────
void connectMQTT() {
  Serial.print("Connecting to MQTT...");

  lcd.setCursor(0, 1);
  printPaddedLCD("MQTT connecting");

  String clientId = "ESP32_Tracker_";
  clientId += String((uint32_t)ESP.getEfuseMac(), HEX);

  if (mqttClient.connect(clientId.c_str(), MQTT_USERNAME, MQTT_PASSWD)) {
    Serial.println(" connected!");

    lcd.setCursor(0, 1);
    printPaddedLCD("MQTT: connected");

    mqttClient.subscribe(T_MODE);
    mqttClient.subscribe(T_PAN_CMD);
    mqttClient.subscribe(T_TILT_CMD);
    mqttClient.subscribe(T_LED);
    mqttClient.subscribe(T_BUZZER);

    Serial.println("Subscribed to dashboard control topics.");
  }
  else {
    Serial.printf(" failed, rc=%d\n", mqttClient.state());

    lcd.setCursor(0, 1);
    printPaddedLCD("MQTT: FAILED");
  }
}

// ─────────────────────────────────────────────────────────────
// SETUP
// ─────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(500);

  pinMode(BUTTON, INPUT_PULLUP);
  pinMode(BUZZER, OUTPUT);
  pinMode(LED, OUTPUT);

  digitalWrite(BUZZER, LOW);
  digitalWrite(LED, LOW);

  Wire.begin(21, 22);

  lcd.begin();
  lcd.backlight();

  lcd.setCursor(0, 0);
  printPaddedLCD("Solar Tracker");

  lcd.setCursor(0, 1);
  printPaddedLCD("Starting...");

  if (lightMeter.begin(BH1750::CONTINUOUS_HIGH_RES_MODE)) {
    Serial.println("BH1750 ready.");
  }
  else {
    Serial.println("BH1750 not detected.");
  }

  servoHori.attach(SERVO_H);
  servoVerti.attach(SERVO_V);

  servoHori.write(servoH);
  servoVerti.write(servoV);

  connectWiFi();

  wifiClient.setInsecure();

  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  mqttClient.setCallback(onMessage);
  mqttClient.setBufferSize(256);

  connectMQTT();

  Serial.println("System ready.");
}

// ─────────────────────────────────────────────────────────────
// LOOP
// ─────────────────────────────────────────────────────────────
void loop() {
  // Keep Wi-Fi connected
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
  }

  // MQTT keepalive and reconnect
  if (!mqttClient.connected()) {
    unsigned long nowReconnect = millis();

    if (nowReconnect - lastReconnect >= RECONNECT_MS) {
      lastReconnect = nowReconnect;
      connectMQTT();
    }
  }

  mqttClient.loop();

  // Physical button triggers buzzer while pressed
  bool buttonPressed = digitalRead(BUTTON) == LOW;

  if (buttonPressed) {
    digitalWrite(BUZZER, HIGH);
  }
  else if (!buzzerPulseActive) {
    digitalWrite(BUZZER, LOW);
  }

  // Automatically turn off dashboard-triggered buzzer pulse
  if (buzzerPulseActive && millis() - buzzerStartedAt >= BUZZER_PULSE_MS) {
    buzzerOff();
  }

  // ───────────────────────────────────────────────────────────
  // READ SENSORS
  // ───────────────────────────────────────────────────────────
  float lux = lightMeter.readLightLevel();

  int left  = analogRead(LDR_LEFT);
  int right = analogRead(LDR_RIGHT);
  int top   = analogRead(LDR_TOP);
  int bot   = analogRead(LDR_BOT);

  int humReading = dht.readHumidity();
  int tempReading = dht.readTemperature();

  if (humReading == -1 || tempReading == -1) {
    Serial.println("DHT11 read error.");

    humReading = 0;
    tempReading = 0;
  }

  float battery = readBatteryVoltage();

  // ───────────────────────────────────────────────────────────
  // AUTO TRACKING
  // ───────────────────────────────────────────────────────────
  if (autoMode) {
    int horizontalError = left - right;
    int verticalError = top - bot;

    if (abs(horizontalError) > tolerance) {
      if (horizontalError > 0) {
        servoH -= 3;
      }
      else {
        servoH += 3;
      }
    }

    if (abs(verticalError) > tolerance) {
      if (verticalError > 0) {
        servoV += 3;
      }
      else {
        servoV -= 3;
      }
    }

    servoH = constrain(servoH, 0, 180);
    servoV = constrain(servoV, 0, 90);

    servoHori.write(servoH);
    servoVerti.write(servoV);
  }

  // ───────────────────────────────────────────────────────────
  // LCD DISPLAY
  // ───────────────────────────────────────────────────────────
  lcd.setCursor(0, 0);

  String line1 = autoMode ? "AUTO " : "MAN  ";
  line1 += "Lux:";
  line1 += String((int)lux);

  printPaddedLCD(line1);

  lcd.setCursor(0, 1);

  String line2 = "P:";
  line2 += String(servoH);
  line2 += " T:";
  line2 += String(servoV);
  line2 += " C:";
  line2 += String(tempReading);

  printPaddedLCD(line2);

  // ───────────────────────────────────────────────────────────
  // PUBLISH TO DASHBOARD
  // ───────────────────────────────────────────────────────────
  unsigned long now = millis();

  if (now - lastPublish >= PUBLISH_MS) {
    lastPublish = now;

    char buf[20];

    dtostrf((float)tempReading, 1, 1, buf);
    mqttClient.publish(T_TEMP, buf);

    dtostrf((float)humReading, 1, 1, buf);
    mqttClient.publish(T_HUM, buf);

    dtostrf(lux, 1, 0, buf);
    mqttClient.publish(T_LUX, buf);

    dtostrf(battery, 1, 2, buf);
    mqttClient.publish(T_BATTERY, buf);

    itoa(servoH, buf, 10);
    mqttClient.publish(T_PAN_FB, buf);

    itoa(servoV, buf, 10);
    mqttClient.publish(T_TILT_FB, buf);

    Serial.printf(
      "[PUBLISH] Temp=%d Hum=%d Lux=%.0f Bat=%.2fV Pan=%d Tilt=%d Mode=%s\n",
      tempReading,
      humReading,
      lux,
      battery,
      servoH,
      servoV,
      autoMode ? "AUTO" : "MANUAL"
    );
  }

  delay(50);
}