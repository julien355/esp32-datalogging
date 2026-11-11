// Adab energy and environment logger: Bluino ESP32-S3 board, FORT FCN300 meter (Modbus RTU),
// TH1 on-board temp/RH, TH2 AM2301 outdoor temp/RH, DS3231 RTC, microSD.
//
// Tasks:
//   sampler (core 1)  reads meter + sensors every 15 s, writes a 1-minute record to the SD card
//   net     (core 0)  WiFi, NTP, uploads the SD backlog, live snapshots, OTA check
//   loop    (core 1)  serial console, setup portal, button, LED, daily reboot, health checks
// Every task is under the task watchdog: a task stuck for 60 s reboots the board.
// See docs/FIRMWARE.md for the settings and functions, docs/OFFICE-PREP.md for the setup.

#include <Arduino.h>
#include <SD.h>
#include <WiFi.h>
#include <Wire.h>
#include <esp_ota_ops.h>
#include <esp_task_wdt.h>

#include "app.h"
#include "console.h"
#include "meter.h"
#include "net.h"
#include "portal.h"
#include "rtclock.h"
#include "sampler.h"
#include "sensors.h"
#include "settings.h"
#include "storage.h"

extern char g_restartWhy[16];
extern uint32_t g_restartMagic;

static int pinBtn = -1, pinLed = -1;

static const char *resetName(esp_reset_reason_t r) {
  switch (r) {
    case ESP_RST_POWERON: return "poweron";
    case ESP_RST_EXT: return "ext";
    case ESP_RST_SW: return "sw";
    case ESP_RST_PANIC: return "panic";
    case ESP_RST_INT_WDT: return "int_wdt";
    case ESP_RST_TASK_WDT: return "task_wdt";
    case ESP_RST_WDT: return "wdt";
    case ESP_RST_DEEPSLEEP: return "deepsleep";
    case ESP_RST_BROWNOUT: return "brownout";
    case ESP_RST_SDIO: return "sdio";
    default: return "unknown";
  }
}

void setup() {
  Serial.begin(115200);
  uint32_t t0 = millis();
  while (!Serial && millis() - t0 < 1500) delay(10);
  i2cMutex = xSemaphoreCreateMutex();
  sdMutex = xSemaphoreCreateMutex();

  esp_reset_reason_t rr = esp_reset_reason();
  String br = resetName(rr);
  if (rr == ESP_RST_SW && g_restartMagic == 0xB007CAFE) {
    g_restartWhy[sizeof(g_restartWhy) - 1] = 0;
    br = String("sw:") + g_restartWhy;
  }
  g_restartMagic = 0;
  strncpy(st.bootReason, br.c_str(), sizeof(st.bootReason) - 1);
  Serial.printf("\n=== Arkan logger, firmware %s, boot reason %s ===\n", FW_VERSION, st.bootReason);

  cfg::begin();
  net::prepare();   // before the first WiFi.mode() anywhere (portal::start() too)

  // Boot-loop guard: the counter is cleared after 10 min of uptime (loop()).
  long boots = cfg::getCounter("bootcnt") + 1;
  cfg::setCounter("bootcnt", boots);
  if (cfg::getCounter("ota_try") == 1 && boots >= 3) {
    // The firmware installed by OTA does not stay up: go back to the previous one.
    const esp_partition_t *prev = esp_ota_get_next_update_partition(nullptr);
    cfg::setCounter("ota_bad", fwHash(FW_VERSION));   // never install this version again
    cfg::setCounter("ota_try", 0);
    cfg::setCounter("bootcnt", 0);
    if (prev && esp_ota_set_boot_partition(prev) == ESP_OK) safeRestart("ota_rollback");
  }
  if (boots >= BOOTLOOP_LIMIT) {
    st.safeMode = true;
    Serial.printf("SAFE MODE: %ld unstable boots in a row, OTA disabled until 10 min of uptime\n", boots);
  }

  Wire.begin((int)cfg::getInt("pin_sda"), (int)cfg::getInt("pin_scl"), (uint32_t)100000);   // casts: pick the master overload
  rtclock::begin();
  store::begin();
  if (st.sdOk) {
    int n = cfg::importFile(SD, FILE_SETTINGS_IMPORT);
    if (n > 0) {
      SD.remove(FILE_SETTINGS_IMPORT);   // it may hold the WiFi password and the token
      evlog("%d setting(s) imported from %s (file deleted), restarting to apply", n, FILE_SETTINGS_IMPORT);
      safeRestart("import");
    }
  }
  evlog("BOOT fw=%s reason=%s boot#%ld dev=%s mac=%s heap=%u", FW_VERSION, st.bootReason, boots,
        cfg::get("dev_id").c_str(), WiFi.macAddress().c_str(), ESP.getFreeHeap());

  sensors::begin();
  meter::begin(st.sdOk ? &SD : nullptr);

  esp_task_wdt_init(WDT_TIMEOUT_S, true);   // panic + reboot when a watched task is stuck
  enableLoopWDT();

  sampler::begin();
  if (!cfg::get("wifi_ssid").length() && !cfg::get("wifi_ssid2").length()) portal::start();
  net::begin();

  pinBtn = cfg::getInt("pin_btn");
  pinLed = cfg::getInt("pin_led");
  if (pinBtn >= 0) pinMode(pinBtn, INPUT_PULLUP);
  if (pinLed >= 0) pinMode(pinLed, OUTPUT);
  Serial.println("Type 'help' for the console commands.");
}

static void everySecond() {
  static int btnHeld = 0, lowHeap = 0;
  static bool stable = false;
  static uint32_t lastHeapCheck = 0;
  uint32_t up = millis() / 1000;

  // Setup button held 3 s: open the portal.
  if (pinBtn >= 0) {
    btnHeld = digitalRead(pinBtn) == LOW ? btnHeld + 1 : 0;
    if (btnHeld == 3) portal::start();
  }

  // LED: on = online, blinking = setup portal, short flash every 4 s = offline.
  if (pinLed >= 0) {
    bool level = st.portalOn ? (up % 2) : st.wifiUp ? true : (up % 4 == 0);
    digitalWrite(pinLed, level);
  }

  // Stable boot: clear the boot-loop and OTA-rollback counters.
  if (!stable && up > STABLE_UPTIME_S) {
    stable = true;
    if (cfg::getCounter("bootcnt")) cfg::setCounter("bootcnt", 0);
    if (cfg::getCounter("ota_try")) {
      cfg::setCounter("ota_try", 0);
      evlog("New firmware %s confirmed after %d min of uptime", FW_VERSION, STABLE_UPTIME_S / 60);
    }
    st.safeMode = false;
  }

  // Daily reboot at reboot_hr:05:02 UTC, just after the 04 record is written (after 1 h of uptime).
  long rh = cfg::getInt("reboot_hr");
  if (rh >= 0 && up > 3600 && timeValid()) {
    time_t now = time(nullptr);
    struct tm tm;
    gmtime_r(&now, &tm);
    if (tm.tm_hour == rh && tm.tm_min == 5 && tm.tm_sec >= 2 && tm.tm_sec < 12) safeRestart("daily");
  }

  // Memory: three low readings a minute apart = reboot.
  if (millis() - lastHeapCheck > 60000) {
    lastHeapCheck = millis();
    uint32_t minFree = cfg::getInt("min_heap_kb") * 1024UL;
    lowHeap = ESP.getFreeHeap() < minFree ? lowHeap + 1 : 0;
    if (lowHeap >= 3) safeRestart("lowheap");
  }
}

void loop() {
  console::poll();
  portal::loop();
  static uint32_t lastSec = 0;
  if (millis() - lastSec >= 1000) {
    lastSec = millis();
    everySecond();
  }
  delay(portal::active() ? 2 : 20);
}
