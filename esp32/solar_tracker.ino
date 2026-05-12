// we have to add that thing ye wifi nalento sir did in class ... the mqtt 

#include <Wire.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <LCD_I2C.h>
#include <ESP32Servo.h>
#include <DHT11.h>
#include <BH1750.h>

#define SERVO_H_PIN 18
#define SERVO_V_PIN 19

#define BUZZER_PIN 15
#define BUTTON_PIN 2

#define LDR_BOT 34
#define LDR_TOP 35
#define LDR_LEFT 32
#define LDR_RIGHT 33

// GLOBAL VARIABLES
bool buzzerState = false;

int left;
int right;
int top;
int bot;

float lux;

int h;
int t;

// WIFI
#define SSID "Drugless"
#define PASS "BuYdaTa80085"

const char* mqtt_server = "broker.hivemq.com";

WiFiClient espClient;
PubSubClient client(espClient);

LCD_I2C lcd(0x27, 16, 2);
DHT11 dht(4);
BH1750 lightMeter;

Servo servohori;
Servo servoverti;

int servoh = 90;
int servov = 90;

int tolerance = 75;

void setup() {

  Serial.begin(115200);

  Wire.begin(21, 22);

  lcd.begin();
  lcd.backlight();

  lightMeter.begin(BH1750::CONTINUOUS_HIGH_RES_MODE);

  servohori.attach(SERVO_H_PIN);
  servoverti.attach(SERVO_V_PIN);

  servohori.write(servoh);
  servoverti.write(servov);

  pinMode(BUTTON_PIN, INPUT_PULLUP);
  pinMode(BUZZER_PIN, OUTPUT);

  Serial.println("System Started...");

  // WIFI CONNECTION
  WiFi.begin(SSID, PASS);

  Serial.println("Connecting to WiFi");

  while (WiFi.status() != WL_CONNECTED) {

    delay(500);

    Serial.print(".");
  }

  Serial.println();
  Serial.println("WiFi Connected");

  Serial.print("IP Address: ");
  Serial.println(WiFi.localIP());

  // MQTT
  client.setServer(mqtt_server, 1883);
}

void loop() {

  // MQTT RECONNECT
  if (!client.connected()) {
    reconnect();
  }

  client.loop();

  // RESET BUZZER STATE
  buzzerState = false;

  // BUTTON CHECK
  if (digitalRead(BUTTON_PIN) == LOW) {

    buzzerState = true;

    Serial.println("BUTTON PRESSED");
  }

  // SENSOR READINGS
  lux = lightMeter.readLightLevel();

  left  = analogRead(LDR_LEFT);
  right = analogRead(LDR_RIGHT);
  top   = analogRead(LDR_TOP);
  bot   = analogRead(LDR_BOT);

  h = dht.readHumidity();
  t = dht.readTemperature();

  // DEBUG PRINT
  Serial.print("L:");
  Serial.print(left);

  Serial.print(" R:");
  Serial.print(right);

  Serial.print(" T:");
  Serial.print(top);

  Serial.print(" B:");
  Serial.print(bot);

  Serial.print(" | Lux:");
  Serial.println(lux);

  Serial.print(" Temp:");
  Serial.print(t);

  Serial.print(" Hum:");
  Serial.println(h);

  // DHT CHECK
  if (h == 0 && t == 0) {

    Serial.println("DHT NOT READING");
  }

  // HORIZONTAL TRACKING
  if (abs(left - right) > tolerance) {

    if (left > right) {
      servoh -= 3;
    }
    else {
      servoh += 3;
    }
  }

  // VERTICAL TRACKING
  if (abs(top - bot) > tolerance) {

    if (top > bot) {
      servov += 3;
    }
    else {
      servov -= 3;
    }
  }

  // SERVO LIMITS
  servoh = constrain(servoh, 0, 360);
  servov = constrain(servov, 0, 180);

  // MOVE SERVOS
  servohori.write(servoh);
  servoverti.write(servov);

  // LCD
  lcd.setCursor(0, 0);
  lcd.print("Lux:");
  lcd.print(lux);
  lcd.print("   ");

  lcd.setCursor(0, 1);
  lcd.print("H:");
  lcd.print(servoh);

  lcd.print(" V:");
  lcd.print(servov);
  lcd.print("   ");

  // LDR HEALTH CHECK
  checkLDRs();

  // APPLY BUZZER STATE
  if (buzzerState) {

    digitalWrite(BUZZER_PIN, HIGH);

  }
  else {

    digitalWrite(BUZZER_PIN, LOW);
  }

  // SEND MQTT DATA
  send();

  delay(1000);
}

// MQTT SEND FUNCTION
void send() {

  String payload = "{";

  payload += "\"left\":" + String(left) + ",";
  payload += "\"right\":" + String(right) + ",";
  payload += "\"top\":" + String(top) + ",";
  payload += "\"bottom\":" + String(bot) + ",";

  payload += "\"lux\":" + String(lux) + ",";

  payload += "\"temperature\":" + String(t) + ",";
  payload += "\"humidity\":" + String(h) + ",";

  payload += "\"servoH\":" + String(servoh) + ",";
  payload += "\"servoV\":" + String(servov) + ",";

  payload += "\"buzzer\":\"";

  if (buzzerState) {
    payload += "ON";
  }
  else {
    payload += "OFF";
  }

  payload += "\"}";

  client.publish("drugless/solartracker", payload.c_str());

  Serial.println(payload);
}

// LDR DIAGNOSTICS
void checkLDRs() {

  bool dead = false;

  if (left <= 5 || left >= 4090) dead = true;
  if (right <= 5 || right >= 4090) dead = true;
  if (top <= 5 || top >= 4090) dead = true;
  if (bot <= 5 || bot >= 4090) dead = true;

  if (dead) {

    buzzerState = true;

    Serial.println("LDR FAILURE DETECTED");
  }
}

// MQTT RECONNECT
void reconnect() {

  while (!client.connected()) {

    Serial.println("Connecting to MQTT...");

    if (client.connect("DruglessESP32")) {

      Serial.println("MQTT Connected");

    }
    else {

      Serial.print("Failed, rc=");
      Serial.println(client.state());

      delay(2000);
    }
  }
}
