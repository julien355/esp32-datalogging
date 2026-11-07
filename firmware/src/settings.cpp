#include "settings.h"

#include <Preferences.h>
#include <map>

namespace cfg {

// Every setting of the logger. Keep docs/FIRMWARE.md in step with this table.
const Def DEFS[] = {
    // Identity
    {"dev_id", "LOG-0001", "Identity", "Logger code, as registered on the platform", 0},
    // WiFi
    {"wifi_ssid", "", "WiFi", "Main WiFi network (2.4 GHz)", 0},
    {"wifi_pass", "", "WiFi", "Main WiFi password", SECRET},
    {"wifi_ssid2", "", "WiFi", "Backup WiFi network (for example a 4G router), empty = none", 0},
    {"wifi_pass2", "", "WiFi", "Backup WiFi password", SECRET},
    // Server
    {"srv_url", "https://arkan-monitoring.duckdns.org", "Server", "Platform base URL (http://IP:8800 for an office test)", 0},
    {"dev_token", "", "Server", "Device token given by tools/manage.py add-device", SECRET},
    {"tls_verify", "1", "Server", "1 = check the server certificate, 0 = do not (bench only)", 0},
    {"upload_s", "60", "Server", "Seconds between upload attempts", 0},
    {"batch_rows", "60", "Server", "Records per upload request", 0},
    {"live_on", "1", "Server", "1 = send a live snapshot after every sample", 0},
    {"ota_on", "0", "Server", "1 = check the platform for firmware updates", 0},
    {"ota_check_h", "6", "Server", "Hours between firmware update checks", 0},
    // Sampling
    {"sample_s", "15", "Sampling", "Seconds between samples (meter and sensors), divides 60", 0},
    // Meter
    {"meters", "EM01:1", "Meter", "Meters on RS485 as id:slave, comma separated (EM01:1,EM02:2)", 0},
    {"mb_baud", "9600", "Meter", "RS485 baud rate", 0},
    {"mb_format", "8N1", "Meter", "RS485 frame: 8N1, 8E1, 8O1 or 8N2", 0},
    {"ct_mult", "1", "Meter", "Multiplier for currents and powers if the meter gives secondary values (CT ratio), else 1", 0},
    // Sensors
    {"th1_type", "auto", "Sensors", "TH1 on-board I2C sensor: auto, aht, sht3x, htu21, none", 0},
    {"th1_off_t", "0", "Sensors", "TH1 temperature offset (C), from the install-day calibration", 0},
    {"th1_off_rh", "0", "Sensors", "TH1 humidity offset (%RH)", 0},
    {"th2_on", "1", "Sensors", "1 = AM2301 (TH2) connected", 0},
    {"th2_off_t", "0", "Sensors", "TH2 temperature offset (C)", 0},
    {"th2_off_rh", "0", "Sensors", "TH2 humidity offset (%RH)", 0},
    // Pins (provisional pin map, to verify in Lab 1)
    {"pin_sda", "8", "Pins", "I2C SDA", 0},
    {"pin_scl", "9", "Pins", "I2C SCL", 0},
    {"pin_sd_sck", "12", "Pins", "SD card SCK", 0},
    {"pin_sd_miso", "13", "Pins", "SD card MISO", 0},
    {"pin_sd_mosi", "11", "Pins", "SD card MOSI", 0},
    {"pin_sd_cs", "10", "Pins", "SD card CS (10 or 21)", 0},
    {"pin_rs_tx", "-1", "Pins", "RS485 TX (to verify, -1 = not set)", 0},
    {"pin_rs_rx", "-1", "Pins", "RS485 RX (to verify, -1 = not set)", 0},
    {"pin_rs_de", "-1", "Pins", "RS485 DE/RE, -1 if the board switches by itself", 0},
    {"pin_dht", "4", "Pins", "AM2301 data", 0},
    {"pin_led", "-1", "Pins", "Status LED, -1 = none", 0},
    {"pin_btn", "0", "Pins", "Setup button (BOOT = 0): hold 3 s to open the setup portal", 0},
    // Robustness
    {"reboot_hr", "19", "Robustness", "Daily reboot at this UTC hour, minute 05 (19 = 03:05 WITA), -1 = never", 0},
    {"offline_rbt_h", "6", "Robustness", "Reboot after this many hours without WiFi, 0 = never", 0},
    {"min_heap_kb", "30", "Robustness", "Reboot if free memory stays below this (kB)", 0},
    {"sd_min_free", "5", "Robustness", "Below this % free on the SD card, delete the oldest uploaded day files", 0},
    // Setup portal
    {"portal_pass", "arkan-setup", "Portal", "Password of the setup WiFi (8 characters at least)", SECRET},
    {"portal_min", "15", "Portal", "Minutes the setup portal stays open without activity", 0},
    // Time
    {"ntp1", "pool.ntp.org", "Time", "First NTP server", 0},
    {"ntp2", "time.google.com", "Time", "Second NTP server", 0},
};
const size_t NDEFS = sizeof(DEFS) / sizeof(DEFS[0]);

static Preferences prefs;
static std::map<String, String> cache;
static SemaphoreHandle_t mtx;

const Def *find(const char *key) {
  for (size_t i = 0; i < NDEFS; i++)
    if (strcmp(DEFS[i].key, key) == 0) return &DEFS[i];
  return nullptr;
}

void begin() {
  mtx = xSemaphoreCreateMutex();
  prefs.begin("logger", false);
  for (size_t i = 0; i < NDEFS; i++) {
    const char *k = DEFS[i].key;
    cache[k] = prefs.isKey(k) ? prefs.getString(k, DEFS[i].def) : String(DEFS[i].def);
  }
}

String get(const char *key) {
  xSemaphoreTake(mtx, portMAX_DELAY);
  auto it = cache.find(key);
  String v = it != cache.end() ? it->second : String();
  xSemaphoreGive(mtx);
  return v;
}

long getInt(const char *key) { return get(key).toInt(); }
float getFloat(const char *key) { return get(key).toFloat(); }

bool isDefault(const char *key) {
  const Def *d = find(key);
  return d && get(key) == d->def;
}

bool set(const char *key, const String &value) {
  const Def *d = find(key);
  if (!d) return false;
  xSemaphoreTake(mtx, portMAX_DELAY);
  prefs.putString(d->key, value);
  cache[d->key] = value;
  xSemaphoreGive(mtx);
  return true;
}

bool unset(const char *key) {
  const Def *d = find(key);
  if (!d) return false;
  xSemaphoreTake(mtx, portMAX_DELAY);
  prefs.remove(d->key);
  cache[d->key] = d->def;
  xSemaphoreGive(mtx);
  return true;
}

void factoryReset() {
  xSemaphoreTake(mtx, portMAX_DELAY);
  prefs.clear();
  for (size_t i = 0; i < NDEFS; i++) cache[DEFS[i].key] = DEFS[i].def;
  xSemaphoreGive(mtx);
}

int importFile(fs::FS &fs, const char *path) {
  File f = fs.open(path, FILE_READ);
  if (!f) return 0;
  f.setTimeout(10);
  int n = 0;
  while (f.available()) {
    String line = f.readStringUntil('\n');
    line.trim();
    if (line.length() == 0 || line[0] == '#') continue;
    int eq = line.indexOf('=');
    if (eq <= 0) continue;
    String k = line.substring(0, eq), v = line.substring(eq + 1);
    k.trim();
    v.trim();
    if (set(k.c_str(), v)) n++;
  }
  f.close();
  return n;
}

// Counters live in their own namespace so "factory" does not clear them.
long getCounter(const char *key, long def) {
  Preferences p;
  p.begin("logger-c", true);
  long v = p.getLong(key, def);
  p.end();
  return v;
}

void setCounter(const char *key, long v) {
  Preferences p;
  p.begin("logger-c", false);
  p.putLong(key, v);
  p.end();
}

}  // namespace cfg
