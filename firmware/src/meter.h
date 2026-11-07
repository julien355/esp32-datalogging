// Modbus RTU master for the power meters (FORT FCN300-3E4Y / 3EH4Y).
// The register table is built in (from docs/meter/fcn300-3e4y-modbus-guide.md, NOT VERIFIED)
// and can be replaced without reflashing by /config/registers.csv on the SD card.
#pragma once
#include <Arduino.h>
#include <FS.h>

#include "config.h"

namespace meter {

enum Type : uint8_t { U16, S16, U32, S32, U32SW, S32SW, F32, F32SW };
enum Agg : uint8_t { MEAN, LAST, MEANMAX };   // how the 1-minute record summarises the samples

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
// Console helper: raw dump of registers.
void dump(uint8_t slave, uint8_t fc, uint16_t start, uint16_t count, Print &out);
String describeTable();

}  // namespace meter
