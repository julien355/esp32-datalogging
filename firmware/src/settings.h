// Runtime settings, stored in NVS (the ESP32's non-volatile memory).
// The full list with defaults and meaning is DEFS[] in settings.cpp and
// docs/FIRMWARE.md. Changes take effect after a reboot.
#pragma once
#include <Arduino.h>
#include <FS.h>

namespace cfg {

enum Flags : uint8_t { SECRET = 1 };

struct Def {
  const char *key;    // NVS key, 15 characters at most
  const char *def;    // default value, as text
  const char *group;  // heading on the setup page
  const char *help;   // one line shown on the setup page and by "show"
  uint8_t flags;
};

extern const Def DEFS[];
extern const size_t NDEFS;

void begin();
String get(const char *key);
long getInt(const char *key);
float getFloat(const char *key);
bool isDefault(const char *key);
bool set(const char *key, const String &value);   // false if the key is unknown
bool unset(const char *key);                        // back to the default
void factoryReset();
const Def *find(const char *key);
// Applies key=value lines from a file (office preparation), returns the number applied.
int importFile(fs::FS &fs, const char *path);
// Small counters that are not settings (boot count, OTA state).
long getCounter(const char *key, long def = 0);
void setCounter(const char *key, long v);

}  // namespace cfg
