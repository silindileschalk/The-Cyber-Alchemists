// The Cyber Alchemists 
// EPG317E Capstone Project
#include <WiFi.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <LCD_I2C.h>
#include <ESP32Servo.h>
#include <DHT11.h>
#include <BH1750.h>
#include <WiFiClientSecure.h>

const char* WIFI_SSID     = "The Cyber Alchemists IoT";
const char* WIFI_PASSWORD = "Cy13ER123";          

// ─────────────────────────────────────────────────────────────
// MQTT CONFIG — must match dashboard_v4.py exactly
// ─────────────────────────────────────────────────────────────
const char* MQTT_BROKER = "4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud";
const int   MQTT_PORT   = 8883;
const char* MQTT_CLIENT = "Cyber_Alchemy";
const char* MQTT_PASSWD = "P@ss123456";

// Publish topics (ESP32 → Dashboard)
const char* T_TEMP    = "epg317e/solar/TheCyberAlchemists/sensors/temperature";
const char* T_HUM     = "epg317e/solar/TheCyberAlchemists/sensors/humidity";
const char* T_LUX     = "epg317e/solar/TheCyberAlchemists/sensors/lux";
const char* T_BATTERY = "epg317e/solar/TheCyberAlchemists/sensors/battery";
const char* T_PAN_FB  = "epg317e/solar/TheCyberAlchemists/actuators/servo_pan";
const char* T_TILT_FB = "epg317e/solar/TheCyberAlchemists/actuators/servo_tilt";

// Subscribe topics (Dashboard → ESP32)
const char* T_MODE     = "epg317e/solar/TheCyberAlchemists/control/tracking_mode";
const char* T_PAN_CMD  = "epg317e/solar/TheCyberAlchemists/control/servo_pan";
const char* T_TILT_CMD = "epg317e/solar/TheCyberAlchemists/control/servo_tilt";
const char* T_LED      = "epg317e/solar/TheCyberAlchemists/control/led";
const char* T_BUZZER   = "epg317e/solar/TheCyberAlchemists/control/buzzer";

// ─────────────────────────────────────────────────────────────
// PIN DEFINITIONS  (unchanged from teammate's wiring)
// ─────────────────────────────────────────────────────────────
#define SERVO_H   18    // Pan  servo
#define SERVO_V   19    // Tilt servo
#define BUZZER    15
#define BUTTON    2
#define LDR_BOT   34
#define LDR_TOP   35
#define LDR_LEFT  32
#define LDR_RIGHT 33
#define BATTERY   36    // GPIO 36 (VP) — voltage divider to battery
#define LED       27    // External LED

// ─────────────────────────────────────────────────────────────
// HARDWARE OBJECTS
// ─────────────────────────────────────────────────────────────
LCD_I2C      lcd(0x27, 16, 2);
DHT11        dht(4);
BH1750       lightMeter;
Servo        servoHori;
Servo        servoVerti;
WiFiClientSecure   wifiClient;
PubSubClient mqttClient(wifiClient);

// ─────────────────────────────────────────────────────────────
// STATE VARIABLES
// ─────────────────────────────────────────────────────────────
int  servoH    = 90;
int  servoV    = 45;
int  tolerance = 25;
bool autoMode  = true;
bool ledState  = false;

unsigned long lastPublish   = 0;
unsigned long lastReconnect = 0;
const long    PUBLISH_MS    = 1000;  // Publish every 2 seconds
const long    RECONNECT_MS  = 5000;  // Retry MQTT every 5 seconds

// ─────────────────────────────────────────────────────────────
// Battery voltage reading
// Voltage divider: battery+ → R1(100kΩ) → GPIO36 → R2(100kΩ) → GND
// Adjust R1/R2 values below if you use different resistors
// ─────────────────────────────────────────────────────────────
float readBatteryVoltage() {
  const float R1      = 100000.0;
  const float R2      = 100000.0;
  const float VREF    = 3.3;
  const float ADC_MAX = 4095.0;

  int   raw  = analogRead(BATTERY);
  float vin  = (raw / ADC_MAX) * VREF;        // Voltage at ADC pin
  float vbat = vin * ((R1 + R2) / R2);        // Actual battery voltage
  return vbat;
}

// ─────────────────────────────────────────────────────────────
// MQTT: message received from dashboard
// ─────────────────────────────────────────────────────────────
void onMessage(char* topic, byte* payload, unsigned int len) {
  char msg[64];
  memset(msg, 0, sizeof(msg));
  memcpy(msg, payload, min((unsigned int)63, len));

  Serial.printf("[MQTT IN] %s → %s\n", topic, msg);

  // Tracking mode toggle
  if (strcmp(topic, T_MODE) == 0) {
    autoMode = (strcmp(msg, "AUTO") == 0);
    lcd.setCursor(0, 0);
    lcd.print(autoMode ? "Mode: AUTO" : "Mode: MANUAL ");
    Serial.printf("Mode: %s\n", autoMode ? "AUTO" : "MANUAL");
  }

  // Manual pan command (only active in MANUAL mode)
  else if (strcmp(topic, T_PAN_CMD) == 0 && !autoMode) {
    servoH = constrain(atoi(msg), 0, 180);
    servoHori.write(servoH);
    Serial.printf("Pan → %d°\n", servoH);
  }

  // Manual tilt command (only active in MANUAL mode)
  else if (strcmp(topic, T_TILT_CMD) == 0 && !autoMode) {
    servoV = constrain(atoi(msg), 0, 90);
    servoVerti.write(servoV);
    Serial.printf("Tilt → %d°\n", servoV);
  }

  // LED toggle from dashboard
  else if (strcmp(topic, T_LED) == 0) {
    if (strcmp(msg, "TOGGLE") == 0) {
      ledState = !ledState;
      digitalWrite(LED, ledState ? HIGH : LOW);
      Serial.printf("LED: %s\n", ledState ? "ON" : "OFF");
    }
  }

  // Buzzer trigger from dashboard
  else if (strcmp(topic, T_BUZZER) == 0) {
    if (strcmp(msg, "TRIGGER") == 0) {
      digitalWrite(BUZZER, HIGH);
      delay(300);
      digitalWrite(BUZZER, LOW);
      Serial.println("Buzzer triggered by dashboard.");
    }
  }
}

// ─────────────────────────────────────────────────────────────
// MQTT: connect / reconnect
// ─────────────────────────────────────────────────────────────
void connectMQTT() {
  Serial.print("Connecting to MQTT...");
  lcd.setCursor(0, 1);
  lcd.print("MQTT connecting ");

  if (mqttClient.connect("ESP32_Tracker", MQTT_CLIENT, MQTT_PASSWD)) {
    Serial.println(" connected!");
    lcd.setCursor(0, 1);
    lcd.print("MQTT: connected ");

    // Subscribe to all dashboard control topics
    mqttClient.subscribe(T_MODE);
    mqttClient.subscribe(T_PAN_CMD);
    mqttClient.subscribe(T_TILT_CMD);
    mqttClient.subscribe(T_LED);
    mqttClient.subscribe(T_BUZZER);
  } else {
    Serial.printf(" failed (rc=%d)\n", mqttClient.state());
    lcd.setCursor(0, 1);
    lcd.print("MQTT: FAILED    ");
  }
}

// ─────────────────────────────────────────────────────────────
// SETUP
// ─────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(500);

  // Pins
  pinMode(BUTTON, INPUT);
  pinMode(BUZZER, OUTPUT);
  pinMode(LED, OUTPUT);
  digitalWrite(BUZZER, LOW);   
  digitalWrite(LED, LOW);
  Wire.begin(21, 22);

  // LCD
  lcd.begin();
  lcd.backlight();
  lcd.setCursor(0, 0);
  lcd.print("Solar Tracker   ");
  lcd.setCursor(0, 1);
  lcd.print("Starting...     ");

  // BH1750
  lightMeter.begin(BH1750::CONTINUOUS_HIGH_RES_MODE);

  // Servos — starting position
  servoHori.attach(SERVO_H);
  servoVerti.attach(SERVO_V);
  servoHori.write(servoH);
  servoVerti.write(servoV);

  // Wi-Fi
  Serial.printf("Connecting to Wi-Fi: %s\n", WIFI_SSID);
  lcd.setCursor(0, 1);
  lcd.print("WiFi connecting ");
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.printf("\nWi-Fi connected. IP: %s\n", WiFi.localIP().toString().c_str());
  lcd.setCursor(0, 1);
  lcd.print("WiFi: OK....");
  delay(800);
  wifiClient.setInsecure(); 
  // MQTT
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  mqttClient.setCallback(onMessage);
  connectMQTT();

  Serial.println("System ready for communication.");
}

// ─────────────────────────────────────────────────────────────
// LOOP
// ─────────────────────────────────────────────────────────────
void loop() {
  // MQTT keepalive + non-blocking reconnect
  if (!mqttClient.connected()) {
    unsigned long now = millis();
    if (now - lastReconnect >= RECONNECT_MS) {
      lastReconnect = now;
      connectMQTT();
    }
  }
  mqttClient.loop();

  // Physical button triggers the buzzer
  bool buttonStatus = digitalRead(BUTTON);
  if (buttonStatus == LOW)
  {
    digitalWrite(BUZZER, LOW);
  } 

  else {
    digitalWrite(BUZZER, HIGH);
  }

  // ── Read sensors ────────────────────────────────────────────
  float lux = lightMeter.readLightLevel();
  int left  = analogRead(LDR_LEFT);
  int right = analogRead(LDR_RIGHT);
  int top   = analogRead(LDR_TOP);
  int bot   = analogRead(LDR_BOT);

  // DHT11 — check for -1 (error), not 0 (valid reading)
  int humReading  = dht.readHumidity();
  int tempReading = dht.readTemperature();
  if (humReading == -1 || tempReading == -1)
  {
    Serial.println("DHT NOT READING");
    humReading  = 0;
    tempReading = 0;
  }

  float battery = readBatteryVoltage();

  // Debug output for all sensor readings
  Serial.printf(
    "L:%d R:%d T:%d B:%d | Lux:%.1f | T:%d H:%d | Bat:%.2fV\n",
    left, right, top, bot, lux, tempReading, humReading, battery);

  // ── Auto tracking ───────────────────────────────────────────
  if (autoMode) {
    // Horizontal
    if (abs(left - right) > tolerance) {
      if (left > right) {
        servoH -= 3;
      } 
      else {
        servoH += 3;   // FIX: was "servoh" (wrong case)
      }
    }

    // Vertical
    if (abs(top - bot) > tolerance) {   // FIX: was outside autoMode block
      if (top > bot) {
        servoV += 3;
      } 
      else {
        servoV -= 3;
      }
    }
    else {
      servoV = 0;
    }

    // Enforce servo angle limits, then write
    servoH = constrain(servoH, 0, 180);  
    servoV = constrain(servoV, 0, 90);   

    servoHori.write(servoH);
    servoVerti.write(servoV);
  }
  // In MANUAL mode, servos are moved only by onMessage() above

  // ── LCD display ─────────────────────────────────────────────
  lcd.setCursor(0, 0);
  lcd.print(autoMode ? "AUTO " : "MAN  ");
  lcd.print("Lux:");
  lcd.print((int)lux);
  lcd.print("     ");

  lcd.setCursor(0, 1);
  lcd.print("H:");
  lcd.print(servoH);
  lcd.print(" V:");
  lcd.print(servoV);
  lcd.print(" T:");
  lcd.print(tempReading);
  lcd.print("   ");

  // ── Publish to MQTT every PUBLISH_MS ────────────────────────
  unsigned long now = millis();
  if (now - lastPublish >= PUBLISH_MS) {
    lastPublish = now;

    char buf[16];

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
      "[PUBLISH] T=%d H=%d Lux=%.0f Bat=%.2fV Pan=%d Tilt=%d\n",
      tempReading, humReading, lux, battery, servoH, servoV
    );
  }

  delay(50);
}
