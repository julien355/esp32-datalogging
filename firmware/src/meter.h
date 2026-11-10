// Modbus RTU master for the power meters (FORT FCN300-3E4Y / 3EH4Y).
// The register table is built in (from docs/meter/fcn300-3e4y-modbus-guide.md, NOT VERIFIED)
// and can be replaced without reflashing by /config/registers.csv on the SD card, written by hand
// or sent by the platform's register page (GET /api/v1/registers, see net.cpp).
#pragma once
#include <Arduino.h>
#include <FS.h>

#include "config.h"

namespace meter {

enum Type : uint8_t { U16, S16, U32, S32, U32SW, S32SW, F32, F32SW };
// How the 1-minute record summarises the 15 s samples:
//   MEAN    one column, the mean
//   LAST    one column, the last value (energy counters)
//   MINMAX  three columns: mean, _min, _max (power quality)
enum Agg : uint8_t { MEAN, LAST, MINMAX };

struct Reg {
  char name[8];   // column suffix: EM01_<name>
  uint8_t fc;     // 3 = holding, 4 = input registers
  uint16_t addr;  // 0-based
  Type type;
  double scale;   // raw x scale = value in the column's unit
  bool ct;        // multiplied by the ct_mult setting
  Agg agg;
};

struct Meter {
  char id[8];     // EM01
  uint8_t slave;
};

void begin(fs::FS *sd);            // sd may be null (no override file)
int count();                       // meters configured
const Meter &get(int i);
int regCount();
const Reg &reg(int i);
// Reads every register of meter i. ok[j] false for values that failed.
bool read(int i, double *values, bool *ok);

// Modbus link of one meter, kept by read() since boot. Shown by the console's status and the setup
// portal, and sent in every live snapshot as sys.mb (sampler.cpp), so the site page shows whether the
// meter answers. A read "answers" when at least one of its requests (register blocks) is answered.
const uint8_t ERR_NO_PORT = 0xF0;   // err: RS485 pins not set, the meter is never asked
struct Link {
  bool known;               // read at least once since boot
  bool ok;                  // the last read answered
  time_t since;             // when ok last changed (0: the clock was not set then)
  time_t lastOk;            // last read that answered (0: none since boot, or the clock was not set)
  uint32_t reads, fails;    // reads since boot, of them with no answer at all
  uint8_t req, reqOk;       // requests of the last read, of them answered
  uint8_t err;              // ModbusMaster code of the last read's failed request, 0 = every request answered
};
const Link &link(int i);
const char *errKey(uint8_t err);    // short name for the live snapshot: "timeout", "crc", "illegal_address"...
const char *errHelp(uint8_t err);   // for a person: what it means and what to check
String linkText(int i);             // one line for the console and the portal
// Console helper: raw dump of registers.
void dump(uint8_t slave, uint8_t fc, uint16_t start, uint16_t count, Print &out);
String describeTable();
// "sd" (/config/registers.csv) or "builtin" (firmware table): the table in use since boot.
const char *source();
// Remote register table (net.cpp). Both check the table with the strict rules (every line valid,
// names a-z0-9 of 1 to 7 characters and unique, at most MAX_REGS lines) before touching the card.
// The new table is used after a restart. err says why on false.
bool installFile(const String &csv, String &err);   // writes /config/registers.csv (old one kept as .bak)
bool removeFile(String &err);                       // back to the built-in table (file renamed to .bak)

}  // namespace meter
