// Shared state between the tasks, the event log and a few helpers.
#pragma once
#include <Arduino.h>
#include "config.h"

// Status read by the console, the setup portal and the live snapshot.
// Plain fields written by one task and read by others (single word writes).
struct Status {
  volatile bool timeValid = false;
  volatile bool rtcFound = false;
  volatile bool sdOk = false;
  volatile bool wifiUp = false;
  volatile bool portalOn = false;
  volatile bool safeMode = false;
  volatile int rssi = 0;
  volatile uint32_t wifiDownSince = 0;     // millis() when the link went down, 0 if up
  volatile time_t lastSampleTs = 0;
  volatile time_t lastRowTs = 0;           // last minute record written
  volatile time_t lastUploadOk = 0;        // time of the last accepted upload
  volatile int backlogMin = 0;             // age of the oldest unsent record, minutes
  volatile uint32_t uploadsOk = 0, uploadsFail = 0, liveOk = 0, liveFail = 0;
  volatile uint32_t rowsWritten = 0, sdErrors = 0;
  volatile int meterFailRun[MAX_METERS] = {0};   // Modbus failures in a row per meter
  volatile bool th1Ok = false, th2Ok = false;
  char th1Chip[12] = "none";
  char ip[16] = "";
  char bootReason[24] = "";
};
extern Status st;

extern SemaphoreHandle_t i2cMutex;   // Wire is shared by the sensors and the RTC
extern SemaphoreHandle_t sdMutex;    // SD card is shared by the sampler, uploader, console

// Event log: Serial + /log/YYYY-MM.log on the SD card. printf style.
void evlog(const char *fmt, ...) __attribute__((format(printf, 1, 2)));

// Logs the reason, waits for any SD write in progress, then restarts.
void safeRestart(const char *why);

// Small hash of a firmware version, kept in NVS when that version had to be rolled back,
// so the logger never installs it again (a counter is a number, not a string).
inline long fwHash(const char *v) {
  uint32_t h = 5381;
  while (*v) h = h * 33 + (uint8_t)*v++;
  return (long)(h & 0x7fffffff);
}

// Time helpers (UTC everywhere)
bool timeValid();
String isoTime(time_t t);                 // 2026-11-07T03:15:00Z
uint32_t ymdOf(time_t t);                 // 20261107
time_t epochOfYmd(uint32_t ymd);          // 00:00:00 UTC of that day
uint32_t nextYmd(uint32_t ymd);
time_t parseIso(const char *s);           // inverse of isoTime, 0 on error
