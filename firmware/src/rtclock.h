// DS3231 real-time clock (I2C 0x68) and NTP. The system clock runs in UTC.
// At boot the system clock is set from the RTC; when NTP syncs, the RTC is corrected.
#pragma once
#include <Arduino.h>

namespace rtclock {
bool begin();                 // finds the RTC, sets the system clock from it if valid
bool readRtc(time_t &t);      // false if absent or its oscillator stopped (lost power)
bool writeRtc(time_t t);
void startNtp();              // call once WiFi is up
void poll();                  // call from the network task: copies NTP time to the RTC
bool setManual(time_t t);     // console "time set"
}  // namespace rtclock
