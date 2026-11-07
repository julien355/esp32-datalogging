// SD card storage: one CSV file per UTC day, and an upload pointer into those files.
// The day files ARE the send queue: nothing is written twice. See docs/DATA-FORMAT.md.
//
//   /data/2026/11/2026-11-07.csv     header line + one row per minute
//   /data/2026/11/2026-11-07_2.csv   only if the columns changed that day (new config)
//   /log/2026-11.log                 event log (boots, WiFi, errors, settings)
//   /state/upload.txt                "20261107 1 48211": day, part, byte offset sent so far
//   /config/settings.txt             optional settings import (deleted once applied)
//   /config/registers.csv            optional register table (replaces the built-in one)
#pragma once
#include <Arduino.h>
#include <FS.h>

namespace store {

bool begin();                      // mounts the card with the pins of the settings
fs::FS &fs();
bool appendRow(time_t minuteTs, const String &header, const String &row);

struct Batch {
  String header;
  String body;        // rows, each ending with '\n'
  int rows = 0;
  time_t firstTs = 0, lastTs = 0;
  bool fromRam = false;
  // pointer after this batch
  uint32_t ymd = 0;
  uint8_t part = 1;
  uint32_t offset = 0;
};
// Next rows to send, oldest first. false when everything is sent.
bool nextBatch(Batch &b, int maxRows, size_t maxBytes);
void commit(const Batch &b);       // the server has stored the batch
void resendFrom(uint32_t ymd);     // console: send again from this day
String pointerText();
int ramRows();
void housekeeping();               // remount after a failure, free space; call every minute
String dayPath(uint32_t ymd, uint8_t part);

}  // namespace store
