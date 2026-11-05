// Lab 1: bench bring-up of the Bluino ESP32-S3 TMP/RH RS485 RTC AI board.
// NOT YET TESTED ON THE HARDWARE. The pin numbers below are the provisional
// pin map of docs/PLAN.md section 2: every one of them is TO VERIFY in Lab 1.
//
// What it does, once, then on request from the Serial Monitor (115200 baud):
//   1. scans the I2C bus and prints every address that answers;
//   2. reads the DS3231 real-time clock; "t" sets it from the compile time,
//      "T2026-11-05 14:30:00" sets it to a given UTC time;
//   3. mounts the microSD card, appends a line to /lab1.txt and reads it back.
// Type "s" to scan again, "r" to read the clock, "d" to redo the SD test,
// "c" to try the other SD chip-select pin.
//
// Libraries (Arduino Library Manager): "RTClib" by Adafruit.
// Board: "ESP32S3 Dev Module" (Arduino-ESP32 core 2.x or 3.x),
// "USB CDC On Boot: Enabled" so Serial goes to the USB-C port.

#include <Wire.h>
#include <SPI.h>
#include <SD.h>
#include <RTClib.h>

// ---- Provisional pin map: TO VERIFY ----
const int PIN_SDA = 8;
const int PIN_SCL = 9;
const int PIN_SD_SCK = 12;
const int PIN_SD_MISO = 13;
const int PIN_SD_MOSI = 11;
const int SD_CS_CANDIDATES[] = {10, 21};  // header shows 21; plan says 10 or 21
int sdCsIndex = 0;

RTC_DS3231 rtc;
bool rtcFound = false;

const char *guessI2C(uint8_t a) {
  switch (a) {
    case 0x38: return "AHT10/AHT20 temp/RH (TH1?)";
    case 0x40: return "HTU21/SHT21/Si7021 temp/RH (TH1?)";
    case 0x44: case 0x45: return "SHT3x temp/RH (TH1?)";
    case 0x48: case 0x49: case 0x4A: case 0x4B: return "ADS1115 ADC";
    case 0x57: return "AT24C32 EEPROM (often on DS3231 modules)";
    case 0x68: return "DS3231 RTC";
    case 0x3C: case 0x3D: return "OLED display";
    default: return "unknown: look it up";
  }
}

void i2cScan() {
  Serial.printf("\nI2C scan on SDA=%d SCL=%d\n", PIN_SDA, PIN_SCL);
  int n = 0;
  for (uint8_t a = 1; a < 127; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) {
      Serial.printf("  0x%02X  %s\n", a, guessI2C(a));
      n++;
    }
  }
  Serial.printf("%d device(s) found\n", n);
  if (n == 0) Serial.println("  Nothing found: check SDA/SCL pins (swap 8 and 9?) and power.");
}

void rtcRead() {
  if (!rtcFound) { Serial.println("RTC not found at 0x68"); return; }
  DateTime t = rtc.now();
  Serial.printf("RTC (UTC): %04d-%02d-%02d %02d:%02d:%02d  lostPower=%s  temp=%.2f C\n",
                t.year(), t.month(), t.day(), t.hour(), t.minute(), t.second(),
                rtc.lostPower() ? "YES" : "no", rtc.getTemperature());
}

void rtcSetFromString(const String &s) {
  // Format: T2026-11-05 14:30:00 (UTC)
  int Y, M, D, h, m, sec;
  if (sscanf(s.c_str() + 1, "%d-%d-%d %d:%d:%d", &Y, &M, &D, &h, &m, &sec) == 6) {
    rtc.adjust(DateTime(Y, M, D, h, m, sec));
    Serial.println("RTC set.");
  } else {
    Serial.println("Format: T2026-11-05 14:30:00  (UTC, not WITA)");
  }
}

void sdTest() {
  int cs = SD_CS_CANDIDATES[sdCsIndex];
  Serial.printf("\nSD test: SCK=%d MISO=%d MOSI=%d CS=%d\n", PIN_SD_SCK, PIN_SD_MISO, PIN_SD_MOSI, cs);
  SD.end();
  SPI.end();
  SPI.begin(PIN_SD_SCK, PIN_SD_MISO, PIN_SD_MOSI, cs);
  if (!SD.begin(cs, SPI, 4000000)) {
    Serial.println("  SD.begin failed: card in? FAT32? try 'c' for the other CS pin.");
    return;
  }
  Serial.printf("  card type %d, size %llu MB\n", SD.cardType(), SD.cardSize() / (1024ULL * 1024ULL));
  File f = SD.open("/lab1.txt", FILE_APPEND);
  if (!f) { Serial.println("  open for append failed"); return; }
  DateTime t = rtcFound ? rtc.now() : DateTime(2000, 1, 1, 0, 0, 0);
  f.printf("lab1 write %04d-%02d-%02dT%02d:%02d:%02dZ millis=%lu\n",
           t.year(), t.month(), t.day(), t.hour(), t.minute(), t.second(), millis());
  f.close();
  f = SD.open("/lab1.txt", FILE_READ);
  Serial.println("  /lab1.txt now contains:");
  while (f && f.available()) Serial.write(f.read());
  if (f) f.close();
  Serial.println("  SD test done.");
}

void setup() {
  Serial.begin(115200);
  delay(1500);
  Serial.println("\n=== Lab 1 bring-up (not yet tested on the hardware) ===");
  Wire.begin(PIN_SDA, PIN_SCL);
  i2cScan();
  rtcFound = rtc.begin(&Wire);
  rtcRead();
  sdTest();
  Serial.println("\nCommands: s=scan  r=read RTC  t=set RTC from compile time  T<date time>=set UTC  d=SD test  c=other SD CS");
}

void loop() {
  if (!Serial.available()) return;
  String line = Serial.readStringUntil('\n');
  line.trim();
  if (line.length() == 0) return;
  switch (line[0]) {
    case 's': i2cScan(); break;
    case 'r': rtcRead(); break;
    case 't':
      // Compile time is local time of the PC: subtract the PC's UTC offset
      // (8 h for WITA) if the PC is not set to UTC.
      rtc.adjust(DateTime(F(__DATE__), F(__TIME__)));
      Serial.println("RTC set from compile time (PC local time: correct it to UTC with T...).");
      rtcRead();
      break;
    case 'T': rtcSetFromString(line); rtcRead(); break;
    case 'd': sdTest(); break;
    case 'c': sdCsIndex = 1 - sdCsIndex; sdTest(); break;
    default: Serial.println("?");
  }
}
