#include "console.h"

#include <SD.h>
#include <WiFi.h>
#include <Wire.h>

#include "app.h"
#include "meter.h"
#include "net.h"
#include "portal.h"
#include "rtclock.h"
#include "sampler.h"
#include "settings.h"
#include "storage.h"

namespace console {

static String line;

static const char HELP[] =
    "Commands:\n"
    "  status                 state of clock, SD, WiFi, uploads, last sample\n"
    "  show                   all settings (secrets hidden)\n"
    "  set <key> <value>      change a setting (then: reboot)\n"
    "  unset <key>            back to the default\n"
    "  reboot                 restart\n"
    "  factory                erase all settings (then: reboot)\n"
    "  portal                 open the setup WiFi and page\n"
    "  time                   show UTC time and RTC\n"
    "  time set <ISO UTC>     e.g. time set 2026-11-07T03:15:00 (UTC, not WITA)\n"
    "  i2c                    scan the I2C bus\n"
    "  wifi                   scan WiFi networks (RSSI)\n"
    "  mb [slave] [fc] [start] [count]  raw Modbus dump, e.g. mb 1 3 0 64\n"
    "  regs                   register table in use (copy to /config/registers.csv to edit)\n"
    "  header                 CSV columns\n"
    "  ls [dir]               list SD folder, e.g. ls /data/2026/11\n"
    "  cat <file>             print a file\n"
    "  tail <file> [n]        last n lines (default 10)\n"
    "  upload                 try an upload now\n"
    "  resend <YYYY-MM-DD>    send again from that day (server drops duplicates)\n"
    "  ota                    check for a firmware update now\n";

static void cmdStatus() {
  Serial.printf("Logger %s, firmware %s, CSV schema %d, up %lu s, boot %s%s\n", cfg::get("dev_id").c_str(),
                FW_VERSION, CSV_SCHEMA, (unsigned long)(millis() / 1000), st.bootReason,
                st.safeMode ? " (SAFE MODE: OTA off)" : "");
  Serial.printf("Time: %s (RTC %s)\n", timeValid() ? isoTime(time(nullptr)).c_str() : "NOT SET",
                st.rtcFound ? "found" : "NOT found");
  Serial.printf("SD: %s, rows written %lu, SD errors %lu\n", st.sdOk ? "ok" : "FAILED",
                (unsigned long)st.rowsWritten, (unsigned long)st.sdErrors);
  Serial.printf("Heap: %u free, %u min free\n", ESP.getFreeHeap(), ESP.getMinFreeHeap());
  Serial.println(net::statusText());
  Serial.printf("Portal: %s\n", st.portalOn ? "open" : "closed");
  Serial.printf("Last sample: %s\n", sampler::lastValuesText().c_str());
  Serial.printf("Last record: %s\n", st.lastRowTs ? isoTime(st.lastRowTs).c_str() : "none yet");
}

static void cmdShow() {
  const char *group = "";
  for (size_t i = 0; i < cfg::NDEFS; i++) {
    const cfg::Def &d = cfg::DEFS[i];
    if (strcmp(group, d.group)) {
      group = d.group;
      Serial.printf("[%s]\n", group);
    }
    String v = cfg::get(d.key);
    if ((d.flags & cfg::SECRET) && v.length()) v = "******";
    Serial.printf("  %-13s = %-28s %s%s\n", d.key, v.c_str(), cfg::isDefault(d.key) ? "" : "(changed) ",
                  d.help);
  }
}

static void cmdI2c() {
  xSemaphoreTake(i2cMutex, portMAX_DELAY);
  for (uint8_t a = 1; a < 127; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) Serial.printf("  0x%02X\n", a);
  }
  xSemaphoreGive(i2cMutex);
}

static void cmdLs(const String &dir) {
  xSemaphoreTake(sdMutex, portMAX_DELAY);
  File d = SD.open(dir.length() ? dir : String("/"));
  if (!d) Serial.println("no such folder");
  for (File e = d ? d.openNextFile() : File(); e; e = d.openNextFile()) {
    Serial.printf("  %-24s %s\n", e.name(), e.isDirectory() ? "<dir>" : String((unsigned long)e.size()).c_str());
    e.close();
  }
  if (d) d.close();
  xSemaphoreGive(sdMutex);
}

static void cmdCat(const String &path, int tailLines) {
  xSemaphoreTake(sdMutex, portMAX_DELAY);
  File f = SD.open(path, FILE_READ);
  if (!f) {
    xSemaphoreGive(sdMutex);
    Serial.println("no such file");
    return;
  }
  if (tailLines > 0) {   // start of the last n lines
    long size = f.size(), pos = size, start = 0;
    int count = 0;
    while (pos > 0) {
      pos--;
      f.seek(pos);
      if (f.read() == '\n' && pos != size - 1 && ++count == tailLines) {
        start = pos + 1;
        break;
      }
    }
    f.seek(start);
  }
  uint8_t buf[256];
  while (f.available()) {
    int n = f.read(buf, sizeof(buf));
    Serial.write(buf, n);
  }
  f.close();
  xSemaphoreGive(sdMutex);
  Serial.println();
}

static void exec(String cmd) {
  cmd.trim();
  if (!cmd.length()) return;
  String a1, a2;
  int sp = cmd.indexOf(' ');
  String c = sp < 0 ? cmd : cmd.substring(0, sp);
  String rest = sp < 0 ? "" : cmd.substring(sp + 1);
  rest.trim();
  int sp2 = rest.indexOf(' ');
  a1 = sp2 < 0 ? rest : rest.substring(0, sp2);
  a2 = sp2 < 0 ? "" : rest.substring(sp2 + 1);
  a2.trim();

  if (c == "help" || c == "?") Serial.print(HELP);
  else if (c == "status") cmdStatus();
  else if (c == "show") cmdShow();
  else if (c == "set") {
    if (!cfg::set(a1.c_str(), a2)) Serial.println("unknown key: see 'show'");
    else {
      Serial.printf("%s set. Type 'reboot' to apply.\n", a1.c_str());
      evlog("Setting %s changed from the console", a1.c_str());
    }
  } else if (c == "unset") Serial.println(cfg::unset(a1.c_str()) ? "back to default; reboot to apply" : "unknown key");
  else if (c == "reboot") safeRestart("console");
  else if (c == "factory") {
    cfg::factoryReset();
    Serial.println("All settings erased. Type 'reboot'.");
  } else if (c == "portal") portal::start();
  else if (c == "time") {
    if (a1 == "set") {
      time_t t = parseIso(a2.c_str());
      if (t > TIME_VALID_AFTER) rtclock::setManual(t);
      else Serial.println("format: time set 2026-11-07T03:15:00 (UTC)");
    }
    time_t r;
    bool ok = rtclock::readRtc(r);
    Serial.printf("System UTC %s, RTC %s\n", timeValid() ? isoTime(time(nullptr)).c_str() : "NOT SET",
                  ok ? isoTime(r).c_str() : "invalid or absent");
  } else if (c == "i2c") cmdI2c();
  else if (c == "wifi") {
    int n = WiFi.scanNetworks();
    for (int i = 0; i < n; i++)
      Serial.printf("  %-32s ch %2d %4d dBm\n", WiFi.SSID(i).c_str(), WiFi.channel(i), WiFi.RSSI(i));
    WiFi.scanDelete();
  } else if (c == "mb") {
    // mb [slave] [fc] [start] [count]
    long v[4] = {1, 3, 0, 64};
    int k = 0, from = 0;
    while (k < 4 && from < (int)rest.length()) {
      int e = rest.indexOf(' ', from);
      String t = e < 0 ? rest.substring(from) : rest.substring(from, e);
      if (t.length()) v[k++] = strtol(t.c_str(), nullptr, 0);
      if (e < 0) break;
      from = e + 1;
    }
    meter::dump(v[0], v[1], v[2], v[3], Serial);
  } else if (c == "regs") Serial.print(meter::describeTable());
  else if (c == "header") Serial.println(sampler::header());
  else if (c == "ls") cmdLs(a1);
  else if (c == "cat") cmdCat(a1, 0);
  else if (c == "tail") cmdCat(a1, a2.length() ? a2.toInt() : 10);
  else if (c == "upload") {
    net::uploadNow();
    Serial.println("upload requested: see 'status' in a few seconds");
  } else if (c == "resend") {
    time_t t = parseIso((a1 + "T00:00:00").c_str());
    if (t) store::resendFrom(ymdOf(t));
    else Serial.println("format: resend 2026-11-07");
  } else if (c == "ota") {
    net::otaCheckNow();
    Serial.println("OTA check requested");
  } else Serial.println("unknown command: type 'help'");
}

void poll() {
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\r') continue;
    if (ch == '\n') {
      Serial.printf("> %s\n", line.c_str());
      exec(line);
      line = "";
    } else if (line.length() < 200) {
      line += ch;
    }
  }
}

}  // namespace console
