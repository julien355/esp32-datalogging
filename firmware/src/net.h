// Network task (core 0): WiFi (two networks, joins the one in range) with back-off, NTP, uploads of the
// SD backlog, live snapshots, and the optional firmware update check.
#pragma once
#include <Arduino.h>

namespace net {
void begin();               // starts the task
void uploadNow();           // console: try an upload at once
void otaCheckNow();         // console: check for a firmware update at once (also retries a
                            // version that was rolled back before)
void configCheckNow();      // console: check for remote settings at once
String statusText();
}  // namespace net
