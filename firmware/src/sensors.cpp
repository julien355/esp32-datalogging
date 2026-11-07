#include "sensors.h"

#include <DHT.h>
#include <Wire.h>

#include <initializer_list>

#include "app.h"
#include "settings.h"

namespace sensors {

enum Chip { NONE, AHT, SHT3X, HTU21 };
static Chip chip = NONE;
static uint8_t chipAddr = 0;
static DHT *dht = nullptr;
static float offT1, offRh1, offT2, offRh2;

static bool probe(uint8_t a) {
  Wire.beginTransmission(a);
  return Wire.endTransmission() == 0;
}

static uint8_t crc8(const uint8_t *d, int n, uint8_t init = 0xFF) {   // poly 0x31: SHT3x init 0xFF, HTU21 init 0x00
  uint8_t c = init;
  for (int i = 0; i < n; i++) {
    c ^= d[i];
    for (int b = 0; b < 8; b++) c = (c & 0x80) ? (c << 1) ^ 0x31 : (c << 1);
  }
  return c;
}

static bool writeBytes(uint8_t a, std::initializer_list<uint8_t> bytes) {
  Wire.beginTransmission(a);
  for (uint8_t b : bytes) Wire.write(b);
  return Wire.endTransmission() == 0;
}

static bool readBytes(uint8_t a, uint8_t *buf, uint8_t n) {
  if (Wire.requestFrom(a, n) != n) return false;
  for (int i = 0; i < n; i++) buf[i] = Wire.read();
  return true;
}

static bool readAht(float &t, float &rh) {
  if (!writeBytes(chipAddr, {0xAC, 0x33, 0x00})) return false;
  uint8_t b[6];
  for (int tries = 0; tries < 5; tries++) {
    delay(tries == 0 ? 80 : 20);
    if (!readBytes(chipAddr, b, 6)) return false;
    if (!(b[0] & 0x80)) break;   // not busy
    if (tries == 4) return false;
  }
  uint32_t hr = ((uint32_t)b[1] << 12) | ((uint32_t)b[2] << 4) | (b[3] >> 4);
  uint32_t tr = (((uint32_t)b[3] & 0x0F) << 16) | ((uint32_t)b[4] << 8) | b[5];
  rh = hr * 100.0f / 1048576.0f;
  t = tr * 200.0f / 1048576.0f - 50.0f;
  return true;
}

static bool readSht3x(float &t, float &rh) {
  if (!writeBytes(chipAddr, {0x24, 0x00})) return false;   // single shot, high repeatability
  delay(20);
  uint8_t b[6];
  if (!readBytes(chipAddr, b, 6)) return false;
  if (crc8(b, 2) != b[2] || crc8(b + 3, 2) != b[5]) return false;
  t = -45.0f + 175.0f * (((uint16_t)b[0] << 8) | b[1]) / 65535.0f;
  rh = 100.0f * (((uint16_t)b[3] << 8) | b[4]) / 65535.0f;
  return true;
}

static bool readHtu21(float &t, float &rh) {
  uint8_t b[3];
  if (!writeBytes(chipAddr, {0xF3})) return false;   // temperature, no hold
  delay(60);
  if (!readBytes(chipAddr, b, 3) || crc8(b, 2, 0x00) != b[2]) return false;
  uint16_t raw = (((uint16_t)b[0] << 8) | b[1]) & 0xFFFC;
  t = -46.85f + 175.72f * raw / 65536.0f;
  if (!writeBytes(chipAddr, {0xF5})) return false;   // humidity, no hold
  delay(30);
  if (!readBytes(chipAddr, b, 3) || crc8(b, 2, 0x00) != b[2]) return false;
  raw = (((uint16_t)b[0] << 8) | b[1]) & 0xFFFC;
  rh = -6.0f + 125.0f * raw / 65536.0f;
  return true;
}

void begin() {
  offT1 = cfg::getFloat("th1_off_t");
  offRh1 = cfg::getFloat("th1_off_rh");
  offT2 = cfg::getFloat("th2_off_t");
  offRh2 = cfg::getFloat("th2_off_rh");
  String type = cfg::get("th1_type");
  xSemaphoreTake(i2cMutex, portMAX_DELAY);
  if ((type == "auto" || type == "aht") && probe(0x38)) {
    chip = AHT;
    chipAddr = 0x38;
    delay(40);
    uint8_t s = 0;
    Wire.beginTransmission(0x38);
    Wire.write(0x71);
    if (Wire.endTransmission() == 0 && Wire.requestFrom((uint8_t)0x38, (uint8_t)1) == 1) s = Wire.read();
    if (!(s & 0x08)) {   // not calibrated: send the init command
      writeBytes(0x38, {0xBE, 0x08, 0x00});
      delay(10);
    }
  } else if ((type == "auto" || type == "sht3x") && (probe(0x44) || probe(0x45))) {
    chip = SHT3X;
    chipAddr = probe(0x44) ? 0x44 : 0x45;
  } else if ((type == "auto" || type == "htu21") && probe(0x40)) {
    chip = HTU21;
    chipAddr = 0x40;
    writeBytes(0x40, {0xFE});   // soft reset
    delay(20);
  }
  xSemaphoreGive(i2cMutex);
  const char *names[] = {"none", "aht", "sht3x", "htu21"};
  strncpy(st.th1Chip, names[chip], sizeof(st.th1Chip) - 1);
  evlog("TH1 sensor: %s (0x%02X)", names[chip], chipAddr);

  if (th2Enabled()) {
    int pin = cfg::getInt("pin_dht");
    dht = new DHT(pin, DHT21);
    dht->begin();
    evlog("TH2 sensor: AM2301 on GPIO %d", pin);
  }
}

bool th2Enabled() { return cfg::getInt("th2_on") == 1; }

static bool plausible(float t, float rh) {
  return !isnan(t) && !isnan(rh) && t > -40 && t < 85 && rh >= 0 && rh <= 100.5f;
}

bool readTH1(float &t, float &rh) {
  if (chip == NONE) return false;
  if (xSemaphoreTake(i2cMutex, pdMS_TO_TICKS(1000)) != pdTRUE) return false;
  bool ok = false;
  switch (chip) {
    case AHT: ok = readAht(t, rh); break;
    case SHT3X: ok = readSht3x(t, rh); break;
    case HTU21: ok = readHtu21(t, rh); break;
    default: break;
  }
  xSemaphoreGive(i2cMutex);
  ok = ok && plausible(t, rh);
  if (ok) {
    t += offT1;
    rh = constrain(rh + offRh1, 0.0f, 100.0f);
  }
  st.th1Ok = ok;
  return ok;
}

bool readTH2(float &t, float &rh) {
  if (!dht) return false;
  bool ok = false;
  for (int attempt = 0; attempt < 2 && !ok; attempt++) {   // one retry on a bad read
    if (attempt) delay(2100);                               // the AM2301 needs 2 s between reads
    if (dht->read(true)) {
      t = dht->readTemperature();
      rh = dht->readHumidity();
      ok = plausible(t, rh);
    }
  }
  if (ok) {
    t += offT2;
    rh = constrain(rh + offRh2, 0.0f, 100.0f);
  }
  st.th2Ok = ok;
  return ok;
}

}  // namespace sensors
