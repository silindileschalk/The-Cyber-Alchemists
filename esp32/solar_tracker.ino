// we have to add that thing ye wifi nalento sir did in class ... the mqtt 
#include <Wire.h>
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

// Defining WiFi values so be sure to change these
#define SSID "Drugless" // replace my ssid with your own
#define PASS "BuYdaTa80085" // use your own password there
const char* server = "websiteWithDashboard.com" // I'm unsure about this line

LCD_I2C lcd(0x27, 16, 2);
DHT11 dht(4);
BH1750 lightMeter;

Servo servohori;
Servo servoverti;

int servoh = 90;
int servov = 90;

int tolerance = 75;   //I know you said we need this to be atleast 80 for even better stability buh let's try out 75 and see if it's not stable enough... also I think the comment wasa lie/ wrong ... so incase just reset to 50

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

  Serial.println("System Started...");

  pinMode(BUTTON_PIN, INPUT_PULLUP);
  pinMode(BUZZER_PIN, OUTPUT);
  
  // came here to instate the Wifi module so ensure you check everything here, this is my first time playing with a esp
  WiFi.begin(Drugless, BuYdaTa80085); // remember to replace these
  while (WiFi.status()!= WL_CONNECTED); // this is just one of those, iof it's not connected say so.
  { 
  delay(500);
  serial.print("searching");
  }
  serial.println(" ");
  serial.println(" WiFi Connected");
  serial.println(WiFi.localIP());
}

void loop() {
  if (digitalRead(BUTTON_PIN) == LOW) {
    digitalWrite(BUZZER_PIN, HIGH);
} 
  else {
  digitalWrite(BUZZER_PIN, LOW);
}
  float lux = lightMeter.readLightLevel();

  int left  = analogRead(LDR_LEFT);
  int right = analogRead(LDR_RIGHT);
  int top   = analogRead(LDR_TOP);
  int bot   = analogRead(LDR_BOT);

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

  // HORIZONTAL 
  if (abs(left - right) > 30) {   // yo drugless i changed here from 40 to 30 and it gives a better reaction
    if (left > right) servoh -= 3; // i also swiped the signs from +=3 to -=3
    else servoh += 3;// you gotit right?
  }

  //  VERTICAL
  if (abs(top - bot) > 30) { // i did the same thing as horizontal
    if (top > bot) servov += 3;
    else servov -= 3;
  }

  // LIMITS
  servoh = constrain(servoh, 0, 360); // kinda thought the servos are limited to 180 degrees, so we'll alter this incase the PV shakes but I think It will ignore the extra scale
  servov = constrain(servov, 0, 360);

  servohori.write(servoh);
  servoverti.write(servov);

  // LCD
  lcd.setCursor(0, 0);
  lcd.print("lght(LUX):"); //prints in lux not %
  lcd.print(lux);
  lcd.print("   ");

  lcd.setCursor(0, 1);
  lcd.print("H:");
  lcd.print(servoh);
  lcd.print(" V:");
  lcd.print(servov);
  lcd.print("   ");

int h = dht.readHumidity(); // how come nothing depends on humidiy?
int t = dht.readTemperature();

if (h == 0 && t == 0) {
  Serial.println("DHT NOT READING");
}
  Serial.print("Temp:");
  Serial.print(t);
  Serial.print(" Hum:");
  Serial.println(h);

  delay(50); //we changed this from 100 to 50 for faster reaction
  
}
// the info we'll tranmit to the dasboard will be here... so what are we plotting exactly? temp, light on which sensor and humidity... 
void send() { 
}