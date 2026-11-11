#include "app.h"

#include <SD.h>
#include <stdarg.h>

Status st;
SemaphoreHandle_t i2cMutex = nullptr;
SemaphoreHandle_t sdMutex = nullptr;

// Restart cause kept across a software reset, so the next boot can report "sw:daily" etc.
RTC_NOINIT_ATTR char g_restartWhy[16];
RTC_NOINIT_ATTR uint32_t g_restartMagic;

void evlog(const char *fmt, ...) {
  char msg[256];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(msg, sizeof(msg), fmt, ap);
  va_end(ap);
  time_t now = time(nullptr);
  String ts = timeValid() ? isoTime(now) : String("uptime ") + String(millis() / 1000) + "s";
  Serial.printf("[%s] %s\n", ts.c_str(), msg);
  if (!st.sdOk || !sdMutex) return;
  if (xSemaphoreTake(sdMutex, pdMS_TO_TICKS(2000)) != pdTRUE) return;
  char path[32];
  if (timeValid()) {
    struct tm tm;
    gmtime_r(&now, &tm);
    snprintf(path, sizeof(path), DIR_LOG "/%04d-%02d.log", tm.tm_year + 1900, tm.tm_mon + 1);
  } else {
    snprintf(path, sizeof(path), DIR_LOG "/no-clock.log");
  }
  File f = SD.open(path, FILE_APPEND);
  if (f) {
    f.printf("%s %s\n", ts.c_str(), msg);
    f.close();
  }
  xSemaphoreGive(sdMutex);
}

void safeRestart(const char *why) {
  evlog("RESTART reason=%s uptime=%lus", why, (unsigned long)(millis() / 1000));
  strncpy(g_restartWhy, why, sizeof(g_restartWhy) - 1);
  g_restartWhy[sizeof(g_restartWhy) - 1] = 0;
  g_restartMagic = 0xB007CAFE;
  if (sdMutex) xSemaphoreTake(sdMutex, pdMS_TO_TICKS(5000));   // no write cut in half
  SD.end();
  delay(200);
  ESP.restart();
}

bool timeValid() { return time(nullptr) > TIME_VALID_AFTER; }

String isoTime(time_t t) {
  struct tm tm;
  gmtime_r(&t, &tm);
  char b[24];
  snprintf(b, sizeof(b), "%04d-%02d-%02dT%02d:%02d:%02dZ", tm.tm_year + 1900, tm.tm_mon + 1,
           tm.tm_mday, tm.tm_hour, tm.tm_min, tm.tm_sec);
  return String(b);
}

uint32_t ymdOf(time_t t) {
  struct tm tm;
  gmtime_r(&t, &tm);
  return (tm.tm_year + 1900) * 10000 + (tm.tm_mon + 1) * 100 + tm.tm_mday;
}

// Days from 1970-01-01 for a civil date (Howard Hinnant's algorithm).
static long daysFromCivil(long y, unsigned m, unsigned d) {
  y -= m <= 2;
  long era = (y >= 0 ? y : y - 399) / 400;
  unsigned yoe = (unsigned)(y - era * 400);
  unsigned doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1;
  unsigned doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
  return era * 146097 + (long)doe - 719468;
}

time_t epochOfYmd(uint32_t ymd) {
  return (time_t)daysFromCivil(ymd / 10000, (ymd / 100) % 100, ymd % 100) * 86400L;
}

uint32_t nextYmd(uint32_t ymd) { return ymdOf(epochOfYmd(ymd) + 86400L); }

time_t parseIso(const char *s) {
  int Y, M, D, h, m, sec;
  if (sscanf(s, "%4d-%2d-%2dT%2d:%2d:%2d", &Y, &M, &D, &h, &m, &sec) != 6) return 0;
  return epochOfYmd(Y * 10000 + M * 100 + D) + h * 3600L + m * 60L + sec;
}
