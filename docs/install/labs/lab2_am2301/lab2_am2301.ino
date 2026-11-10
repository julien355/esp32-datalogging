// Lab 2: read the AM2301 (DHT21) outdoor sensor TH2 and the on-board sensor TH1.
// NOT YET TESTED ON THE HARDWARE. Pins are provisional (docs/PLAN.md section 2):
// TO VERIFY in Lab 1 and Lab 2.
//
// Wiring (drawing docs/install/schematics/d-am2301-wiring.svg):
//   AM2301 red (VCC) -> 3V3, black (GND) -> GND, yellow (DATA) -> GPIO 1,
//   4.7 kohm resistor from DATA to 3V3 at the board end. NEVER to 5 V.
//
// Every 5 s it prints one line:
//   TH1 temp, hum | TH2 temp, hum | dew point TH2 | read errors
// The offsets below are the corrections found in Lab 2 (reference minus reading).
//
// Libraries: "DHT sensor library" by Adafruit (+ "Adafruit Unified Sensor"),
//            "Adafruit AHTX0" (TH1, only if the I2C scan found 0x38).

#include <Wire.h>
#include <DHT.h>
#include <Adafruit_AHTX0.h>
#include <math.h>

const int PIN_SDA = 8;       // TO VERIFY
const int PIN_SCL = 9;       // TO VERIFY
const int PIN_AM2301 = 1;    // wired on IO1

// Offsets found in Lab 2, step 6 (reference minus sensor). Start at 0.
float TH1_T_OFFSET = 0.0, TH1_H_OFFSET = 0.0;
float TH2_T_OFFSET = 0.0, TH2_H_OFFSET = 0.0;

DHT dht(PIN_AM2301, DHT21);   // DHT21 = AM2301
Adafruit_AHTX0 aht;
bool th1Found = false;
unsigned long th2Errors = 0, th2Reads = 0;

// Magnus formula, valid about -45 to +60 C. Returns the dew point in C.
float dewPoint(float t, float rh) {
  const float a = 17.62, b = 243.12;
  float g = log(rh / 100.0) + a * t / (b + t);
  return b * g / (a - g);
}

void setup() {
  Serial.begin(115200);
  delay(1500);
  Serial.println("\n=== Lab 2 AM2301 + TH1 (not yet tested on the hardware) ===");
  Wire.begin(PIN_SDA, PIN_SCL);
  th1Found = aht.begin(&Wire);   // address 0x38; if TH1 is another type, adapt
  Serial.printf("TH1 (AHTx0 at 0x38): %s\n", th1Found ? "found" : "NOT found (other chip? see Lab 1 scan)");
  dht.begin();
  Serial.println("time_s, TH1_T, TH1_RH, TH2_T, TH2_RH, TH2_dewpoint, TH2_errors/reads");
}

void loop() {
  static unsigned long last = 0;
  if (millis() - last < 5000) return;   // the AM2301 needs 2 s or more between reads
  last = millis();

  float t1 = NAN, h1 = NAN;
  if (th1Found) {
    sensors_event_t hum, temp;
    if (aht.getEvent(&hum, &temp)) {
      t1 = temp.temperature + TH1_T_OFFSET;
      h1 = hum.relative_humidity + TH1_H_OFFSET;
    }
  }

  th2Reads++;
  float t2 = dht.readTemperature();
  float h2 = dht.readHumidity();
  if (isnan(t2) || isnan(h2)) {
    delay(2100);                         // one retry, as the firmware will do
    t2 = dht.readTemperature(false, true);  // Celsius, force a new read
    h2 = dht.readHumidity();
  }
  if (isnan(t2) || isnan(h2)) {
    th2Errors++;
    Serial.printf("%lu, %.1f, %.1f, ERR, ERR, -, %lu/%lu\n",
                  millis() / 1000, t1, h1, th2Errors, th2Reads);
    return;
  }
  t2 += TH2_T_OFFSET;
  h2 += TH2_H_OFFSET;
  Serial.printf("%lu, %.1f, %.1f, %.1f, %.1f, %.1f, %lu/%lu\n",
                millis() / 1000, t1, h1, t2, h2, dewPoint(t2, h2), th2Errors, th2Reads);
}
