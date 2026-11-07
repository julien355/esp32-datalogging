#include "rtclock.h"

#include <Wire.h>
#include <esp_sntp.h>
#include <sys/time.h>

#include "app.h"
#include "settings.h"

namespace rtclock {

static const uint8_t ADDR = 0x68;
static volatile bool ntpEvent = false;
static bool ntpStarted = false;
static uint32_t lastRtcWriteMs = 0;

static uint8_t bcd2bin(uint8_t v) { return (v & 0x0F) + 10 * (v >> 4); }
static uint8_t bin2bcd(uint8_t v) { return ((v / 10) << 4) | (v % 10); }

bool readRtc(time_t &t) {
  if (xSemaphoreTake(i2cMutex, pdMS_TO_TICKS(1000)) != pdTRUE) return false;
  bool ok = false;
  uint8_t r[7];
  uint8_t status = 0;
  Wire.beginTransmission(ADDR);
  Wire.write(0x0F);
  if (Wire.endTransmission() == 0 && Wire.requestFrom(ADDR, (uint8_t)1) == 1) {
    status = Wire.read();
    Wire.beginTransmission(ADDR);
    Wire.write(0x00);
    if (Wire.endTransmission() == 0 && Wire.requestFrom(ADDR, (uint8_t)7) == 7) {
      for (int i = 0; i < 7; i++) r[i] = Wire.read();
      int sec = bcd2bin(r[0] & 0x7F), min = bcd2bin(r[1] & 0x7F), hour = bcd2bin(r[2] & 0x3F);
      int day = bcd2bin(r[4] & 0x3F), mon = bcd2bin(r[5] & 0x1F), year = 2000 + bcd2bin(r[6]);
      t = epochOfYmd(year * 10000 + mon * 100 + day) + hour * 3600L + min * 60L + sec;
      ok = !(status & 0x80) && t > TIME_VALID_AFTER;   // OSF bit: oscillator stopped
    }
  }
  xSemaphoreGive(i2cMutex);
  return ok;
}

bool writeRtc(time_t t) {
  struct tm tm;
  gmtime_r(&t, &tm);
  if (xSemaphoreTake(i2cMutex, pdMS_TO_TICKS(1000)) != pdTRUE) return false;
  Wire.beginTransmission(ADDR);
  Wire.write(0x00);
  Wire.write(bin2bcd(tm.tm_sec));
  Wire.write(bin2bcd(tm.tm_min));
  Wire.write(bin2bcd(tm.tm_hour));   // 24 h mode
  Wire.write(bin2bcd(tm.tm_wday + 1));
  Wire.write(bin2bcd(tm.tm_mday));
  Wire.write(bin2bcd(tm.tm_mon + 1));
  Wire.write(bin2bcd(tm.tm_year - 100));
  bool ok = Wire.endTransmission() == 0;
  if (ok) {   // clear the oscillator-stopped flag
    Wire.beginTransmission(ADDR);
    Wire.write(0x0F);
    Wire.write(0x00);
    ok = Wire.endTransmission() == 0;
  }
  xSemaphoreGive(i2cMutex);
  return ok;
}

static void setSystem(time_t t) {
  struct timeval tv = {t, 0};
  settimeofday(&tv, nullptr);
  st.timeValid = timeValid();
}

bool begin() {
  if (xSemaphoreTake(i2cMutex, pdMS_TO_TICKS(1000)) == pdTRUE) {
    Wire.beginTransmission(ADDR);
    st.rtcFound = Wire.endTransmission() == 0;
    xSemaphoreGive(i2cMutex);
  }
  setenv("TZ", "UTC0", 1);
  tzset();
  if (!st.rtcFound) {
    evlog("RTC not found at 0x68: time comes from NTP only");
    return false;
  }
  time_t t;
  if (readRtc(t)) {
    setSystem(t);
    evlog("RTC ok, system time set to %s", isoTime(t).c_str());
    return true;
  }
  evlog("RTC time invalid (battery or first use): waiting for NTP or 'time set'");
  return false;
}

static void onNtp(struct timeval *tv) { ntpEvent = true; }

void startNtp() {
  if (ntpStarted) return;
  ntpStarted = true;
  sntp_set_time_sync_notification_cb(onNtp);
  sntp_set_sync_interval(3600UL * 1000UL);   // re-sync every hour
  static String s1, s2;   // configTime keeps the pointers
  s1 = cfg::get("ntp1");
  s2 = cfg::get("ntp2");
  configTime(0, 0, s1.c_str(), s2.c_str());
}

void poll() {
  if (!ntpEvent) return;
  ntpEvent = false;
  time_t now = time(nullptr);
  bool wasValid = st.timeValid;
  st.timeValid = timeValid();
  if (!st.rtcFound) return;
  time_t r = 0;
  bool rtcOk = readRtc(r);
  long drift = rtcOk ? (long)(now - r) : 0;
  // Write the RTC when it is wrong by 2 s or more, or every 6 hours.
  if (!rtcOk || labs(drift) >= 2 || millis() - lastRtcWriteMs > 6UL * 3600UL * 1000UL ||
      lastRtcWriteMs == 0) {
    if (writeRtc(now)) {
      lastRtcWriteMs = millis();
      if (!rtcOk || labs(drift) >= 2 || !wasValid)
        evlog("NTP sync: RTC set to %s (drift was %lds%s)", isoTime(now).c_str(), drift,
              rtcOk ? "" : ", RTC was invalid");
    }
  }
}

bool setManual(time_t t) {
  setSystem(t);
  bool ok = st.rtcFound ? writeRtc(t) : true;
  evlog("Time set by hand to %s", isoTime(t).c_str());
  return ok;
}

}  // namespace rtclock
