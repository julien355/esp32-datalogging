// Setup portal: the logger opens its own WiFi "ARKAN-<dev_id>" (password: portal_pass),
// a phone joins it and the page at http://192.168.4.1 shows the status and every setting.
// Logging goes on while the portal is open. Opens when no WiFi is set, when the setup button
// is held 3 s, or with the console command "portal".
#pragma once
#include <Arduino.h>

namespace portal {
void start();
void stop();
void loop();     // call often from the Arduino loop
bool active();
}  // namespace portal
