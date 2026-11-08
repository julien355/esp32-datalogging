#include "meter.h"

#include <ModbusMaster.h>

#include <utility>

#include "app.h"
#include "settings.h"

namespace meter {

// Default register table: docs/meter/fcn300-3e4y-modbus-guide.md. NOT VERIFIED on a meter.
// Units of the columns: V, A, Hz, kW, kvar, kVA, PF (no unit), kWh, kvarh.
// Scales of currents and powers are guesses until the register check (docs/meter/README.md).
static const Reg DEFAULT_TABLE[] = {
    {"v1", 3, 0x0000, U16, 0.1, false, MINMAX},
    {"v2", 3, 0x0001, U16, 0.1, false, MINMAX},
    {"v3", 3, 0x0002, U16, 0.1, false, MINMAX},
    {"v12", 3, 0x0003, U16, 0.1, false, MINMAX},
    {"v23", 3, 0x0004, U16, 0.1, false, MINMAX},
    {"v31", 3, 0x0005, U16, 0.1, false, MINMAX},
    {"i1", 3, 0x0006, U16, 0.001, true, MINMAX},
    {"i2", 3, 0x0007, U16, 0.001, true, MINMAX},
    {"i3", 3, 0x0008, U16, 0.001, true, MINMAX},
    {"f", 3, 0x0009, U16, 0.01, false, MINMAX},
    {"p1", 3, 0x000A, S16, 0.001, true, MINMAX},
    {"p2", 3, 0x000B, S16, 0.001, true, MINMAX},
    {"p3", 3, 0x000C, S16, 0.001, true, MINMAX},
    {"p", 3, 0x000D, S16, 0.001, true, MINMAX},
    {"q", 3, 0x000E, S16, 0.001, true, MINMAX},
    {"s", 3, 0x000F, U16, 0.001, true, MINMAX},
    {"pf", 3, 0x0010, S16, 0.001, false, MINMAX},
    {"e", 3, 0x0018, U32, 0.01, false, LAST},
    {"eq", 3, 0x001A, U32, 0.01, false, LAST},
};

static Reg table[MAX_REGS];
static int nRegs = 0;
static Meter meters[MAX_METERS];
static int nMeters = 0;
static double ctMult = 1;
static int dePin = -1;
static bool portOk = false;   // RS485 pins set and the port started
static ModbusMaster node;

struct Block {
  uint8_t fc;
  uint16_t start, count;
};
static Block blocks[MAX_REGS];
static int nBlocks = 0;

static uint8_t words(Type t) { return (t == U16 || t == S16) ? 1 : 2; }

static void preTx() {
  if (dePin >= 0) digitalWrite(dePin, HIGH);
}
static void postTx() {
  if (dePin >= 0) {
    Serial1.flush();
    digitalWrite(dePin, LOW);
  }
}

static bool parseType(const String &s, Type &t) {
  const char *names[] = {"u16", "s16", "u32", "s32", "u32sw", "s32sw", "f32", "f32sw"};
  for (int i = 0; i < 8; i++)
    if (s.equalsIgnoreCase(names[i])) {
      t = (Type)i;
      return true;
    }
  return false;
}

// Line format: name,fc,addr,type,scale,ct,agg   e.g.  p,3,0x000D,s16,0.001,1,minmax
// Returns 1 for a register line, 0 for a blank, comment or header line, -1 for a bad line (why in err).
static int parseLine(String line, Reg &r, String &err) {
  line.trim();
  String low = line;
  low.toLowerCase();
  if (!line.length() || line[0] == '#' || low.startsWith("name,")) return 0;
  String p[7];
  int k = 0, from = 0;
  for (;;) {
    int c = line.indexOf(',', from);
    if (k == 7) {
      err = "more than 7 fields";
      return -1;
    }
    p[k++] = c < 0 ? line.substring(from) : line.substring(from, c);
    if (c < 0) break;
    from = c + 1;
  }
  if (k < 6) {
    err = "fewer than 6 fields";
    return -1;
  }
  for (int i = 0; i < k; i++) p[i].trim();
  p[0].toLowerCase();
  r = {};
  if (!p[0].length() || p[0].length() > sizeof(r.name) - 1) {
    err = "name must have 1 to 7 characters";
    return -1;
  }
  for (size_t i = 0; i < p[0].length(); i++) {
    char ch = p[0][i];
    if (!((ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9'))) {
      err = "name: a-z and 0-9 only";
      return -1;
    }
  }
  strncpy(r.name, p[0].c_str(), sizeof(r.name) - 1);
  if (p[1] != "3" && p[1] != "4") {
    err = "fc must be 3 or 4";
    return -1;
  }
  r.fc = p[1].toInt();
  char *end = nullptr;
  long a = strtol(p[2].c_str(), &end, 0);   // accepts 0x0018 or 24
  if (!p[2].length() || *end || a < 0 || a > 0xFFFF) {
    err = "bad addr";
    return -1;
  }
  r.addr = a;
  if (!parseType(p[3], r.type)) {
    err = "bad type";
    return -1;
  }
  r.scale = strtod(p[4].c_str(), &end);
  if (!p[4].length() || *end || r.scale == 0 || !isfinite(r.scale)) {
    err = "bad scale";
    return -1;
  }
  if (p[5] != "0" && p[5] != "1") {
    err = "ct must be 0 or 1";
    return -1;
  }
  r.ct = p[5] == "1";
  String agg = k > 6 ? p[6] : String("");
  agg.toLowerCase();
  if (agg == "last") r.agg = LAST;
  else if (agg == "minmax" || agg == "meanmax") r.agg = MINMAX;
  else if (agg == "mean" || agg == "") r.agg = MEAN;
  else {
    err = "agg must be mean, last or minmax";
    return -1;
  }
  return 1;
}

// Parses a whole table into out[]. strict (remote table): any bad or duplicate line refuses the whole
// table (returns -1). Not strict (file put on the card by hand): bad lines are logged and skipped.
static int parseText(const String &text, Reg *out, bool strict, String &err) {
  int n = 0, lineNo = 0, from = 0;
  while (from < (int)text.length()) {
    int nl = text.indexOf('\n', from);
    String line = nl < 0 ? text.substring(from) : text.substring(from, nl);
    from = nl < 0 ? text.length() : nl + 1;
    lineNo++;
    Reg r;
    String why;
    int res = parseLine(line, r, why);
    if (res == 0) continue;
    if (res > 0)
      for (int i = 0; i < n; i++)
        if (strcmp(out[i].name, r.name) == 0) {
          res = -1;
          why = String("name ") + r.name + " used twice";
        }
    if (res > 0 && n >= MAX_REGS) {
      res = -1;
      why = "more than " + String(MAX_REGS) + " values";
    }
    if (res < 0) {
      if (strict) {
        err = "line " + String(lineNo) + ": " + why;
        return -1;
      }
      line.trim();
      evlog("registers.csv: line %d skipped (%s): %s", lineNo, why.c_str(), line.c_str());
      continue;
    }
    out[n++] = r;
  }
  if (n == 0) err = "no register line";
  return n;
}

static fs::FS *sdFs = nullptr;
static bool fromSd = false;
#define FILE_REGISTERS_NEW "/config/registers.new"
#define FILE_REGISTERS_BAK "/config/registers.bak"

static bool loadOverride(fs::FS &fs) {
  File f = fs.open(FILE_REGISTERS, FILE_READ);
  if (!f) return false;
  if (f.size() > 8192) {
    f.close();
    evlog("registers.csv: larger than 8 kB, ignored");
    return false;
  }
  f.setTimeout(10);
  String text = f.readString();
  f.close();
  String err;
  int n = parseText(text, table, false, err);
  if (n <= 0) {
    evlog("registers.csv: %s, ignored", err.c_str());
    return false;
  }
  nRegs = n;
  return true;
}

static void buildBlocks() {
  // Registers sorted by (fc, addr); neighbours merged when the request stays small.
  int idx[MAX_REGS];
  for (int i = 0; i < nRegs; i++) idx[i] = i;
  for (int i = 1; i < nRegs; i++)
    for (int j = i; j > 0; j--) {
      const Reg &a = table[idx[j - 1]], &b = table[idx[j]];
      if (a.fc > b.fc || (a.fc == b.fc && a.addr > b.addr)) std::swap(idx[j - 1], idx[j]);
      else break;
    }
  nBlocks = 0;
  for (int k = 0; k < nRegs; k++) {
    const Reg &r = table[idx[k]];
    uint16_t end = r.addr + words(r.type);
    if (nBlocks) {
      Block &b = blocks[nBlocks - 1];
      // Merge only registers that touch: a meter may answer "illegal data address" to a request that
      // spans registers it does not have, and the whole block would be lost (tools/modbus_sim shows it).
      if (b.fc == r.fc && r.addr <= b.start + b.count && end - b.start <= 60) {
        if (end > b.start + b.count) b.count = end - b.start;
        continue;
      }
    }
    blocks[nBlocks++] = {r.fc, r.addr, (uint16_t)(end - r.addr)};
  }
}

static void parseMeters(const String &s) {
  nMeters = 0;
  int from = 0;
  while (from < (int)s.length() && nMeters < MAX_METERS) {
    int c = s.indexOf(',', from);
    String item = c < 0 ? s.substring(from) : s.substring(from, c);
    item.trim();
    int colon = item.indexOf(':');
    if (colon > 0) {
      Meter m = {};
      strncpy(m.id, item.substring(0, colon).c_str(), sizeof(m.id) - 1);
      m.slave = item.substring(colon + 1).toInt();
      if (m.slave >= 1 && m.slave <= 247) meters[nMeters++] = m;
    }
    if (c < 0) break;
    from = c + 1;
  }
}

void begin(fs::FS *sd) {
  sdFs = sd;
  ctMult = cfg::getFloat("ct_mult");
  if (ctMult <= 0) ctMult = 1;
  fromSd = sd && loadOverride(*sd);
  if (!fromSd) {
    nRegs = sizeof(DEFAULT_TABLE) / sizeof(DEFAULT_TABLE[0]);
    memcpy(table, DEFAULT_TABLE, sizeof(DEFAULT_TABLE));
    evlog("Meter: built-in FCN300 register table (%d values, not verified)", nRegs);
  } else {
    evlog("Meter: register table from SD %s (%d values)", FILE_REGISTERS, nRegs);
  }
  buildBlocks();
  parseMeters(cfg::get("meters"));

  int tx = cfg::getInt("pin_rs_tx"), rx = cfg::getInt("pin_rs_rx");
  dePin = cfg::getInt("pin_rs_de");
  if (tx < 0 || rx < 0) {
    // Keep the meters in the configuration: their columns stay in the record (empty, EM01_n = 0),
    // so the platform raises A03 "Meter not answering" instead of the fault going unnoticed.
    evlog("Meter: RS485 pins not set (pin_rs_tx / pin_rs_rx): meter NOT read, records show EM01_n = 0");
    return;
  }
  if (dePin >= 0) {
    pinMode(dePin, OUTPUT);
    digitalWrite(dePin, LOW);
  }
  String fmt = cfg::get("mb_format");
  uint32_t serialCfg = fmt == "8E1" ? SERIAL_8E1 : fmt == "8O1" ? SERIAL_8O1 : fmt == "8N2" ? SERIAL_8N2 : SERIAL_8N1;
  Serial1.begin(cfg::getInt("mb_baud"), serialCfg, rx, tx);
  portOk = true;
  node.preTransmission(preTx);
  node.postTransmission(postTx);
  evlog("Meter: %d meter(s), RS485 TX=%d RX=%d DE=%d %ld %s, %d request(s) per read", nMeters, tx, rx,
        dePin, cfg::getInt("mb_baud"), fmt.c_str(), nBlocks);
}

int count() { return nMeters; }
const Meter &get(int i) { return meters[i]; }
int regCount() { return nRegs; }
const Reg &reg(int i) { return table[i]; }

static double decode(const Reg &r, uint16_t w0, uint16_t w1) {
  union {
    uint32_t u;
    float f;
  } x;
  double v = 0;   // double: a kWh counter above 167,772 kWh needs more than float's 24 bits
  switch (r.type) {
    case U16: v = w0; break;
    case S16: v = (int16_t)w0; break;
    case U32: v = (double)(((uint32_t)w0 << 16) | w1); break;
    case S32: v = (double)(int32_t)(((uint32_t)w0 << 16) | w1); break;
    case U32SW: v = (double)(((uint32_t)w1 << 16) | w0); break;
    case S32SW: v = (double)(int32_t)(((uint32_t)w1 << 16) | w0); break;
    case F32: x.u = ((uint32_t)w0 << 16) | w1; v = x.f; break;
    case F32SW: x.u = ((uint32_t)w1 << 16) | w0; v = x.f; break;
  }
  v *= r.scale;
  if (r.ct) v *= ctMult;
  return v;
}

bool read(int i, double *values, bool *ok) {
  for (int j = 0; j < nRegs; j++) ok[j] = false;
  if (i >= nMeters) return false;
  if (!portOk) {
    st.meterFailRun[i] = st.meterFailRun[i] + 1;
    return false;
  }
  node.begin(meters[i].slave, Serial1);
  bool any = false;
  for (int b = 0; b < nBlocks; b++) {
    const Block &bl = blocks[b];
    uint8_t res = 0xFF;
    for (int attempt = 0; attempt < 2 && res != node.ku8MBSuccess; attempt++) {
      if (attempt) delay(50);
      res = bl.fc == 3 ? node.readHoldingRegisters(bl.start, bl.count)
                       : node.readInputRegisters(bl.start, bl.count);
    }
    if (res != node.ku8MBSuccess) continue;
    any = true;
    for (int j = 0; j < nRegs; j++) {
      const Reg &r = table[j];
      if (r.fc != bl.fc || r.addr < bl.start || r.addr + words(r.type) > bl.start + bl.count) continue;
      uint16_t off = r.addr - bl.start;
      uint16_t w0 = node.getResponseBuffer(off);
      uint16_t w1 = words(r.type) == 2 ? node.getResponseBuffer(off + 1) : 0;
      values[j] = decode(r, w0, w1);
      ok[j] = isfinite(values[j]);
    }
    delay(5);
  }
  st.meterFailRun[i] = any ? 0 : st.meterFailRun[i] + 1;
  return any;
}

void dump(uint8_t slave, uint8_t fc, uint16_t start, uint16_t cnt, Print &out) {
  if (cfg::getInt("pin_rs_tx") < 0) {
    out.println("RS485 pins not set");
    return;
  }
  node.begin(slave, Serial1);
  for (uint16_t s = start; s < start + cnt; s += 16) {
    uint16_t n = min<uint16_t>(16, start + cnt - s);
    uint8_t r = fc == 3 ? node.readHoldingRegisters(s, n) : node.readInputRegisters(s, n);
    if (r != node.ku8MBSuccess) {
      out.printf("FC%02u 0x%04X..0x%04X error 0x%02X%s\n", fc, s, s + n - 1, r,
                 r == node.ku8MBResponseTimedOut ? " (timeout: wiring, A/B, id, baud)" : "");
      continue;
    }
    for (uint16_t k = 0; k < n; k++) {
      uint16_t w = node.getResponseBuffer(k);
      out.printf("FC%02u 0x%04X (%5u) 0x%04X u16=%5u s16=%6d\n", fc, s + k, s + k, w, w, (int16_t)w);
    }
  }
}

String describeTable() {
  const char *tn[] = {"u16", "s16", "u32", "s32", "u32sw", "s32sw", "f32", "f32sw"};
  const char *an[] = {"mean", "last", "minmax"};
  String s = "name,fc,addr,type,scale,ct,agg\n";
  char b[64];
  for (int i = 0; i < nRegs; i++) {
    const Reg &r = table[i];
    snprintf(b, sizeof(b), "%s,%u,0x%04X,%s,%g,%d,%s\n", r.name, r.fc, r.addr, tn[r.type], r.scale, r.ct,
             an[r.agg]);
    s += b;
  }
  return s;
}

const char *source() { return fromSd ? "sd" : "builtin"; }

bool installFile(const String &csv, String &err) {
  static Reg check[MAX_REGS];   // static: 32 x 24 bytes kept off the net task's stack
  if (csv.length() > 6144) {
    err = "table larger than 6 kB";
    return false;
  }
  if (parseText(csv, check, true, err) <= 0) return false;
  if (!sdFs || !st.sdOk) {
    err = "no working SD card";
    return false;
  }
  xSemaphoreTake(sdMutex, portMAX_DELAY);
  sdFs->mkdir("/config");
  bool ok = false;
  File f = sdFs->open(FILE_REGISTERS_NEW, FILE_WRITE);
  if (f) {
    ok = f.print(csv) == csv.length();
    f.close();
  }
  if (ok) {   // read back the size: a full or failing card shows here
    File r = sdFs->open(FILE_REGISTERS_NEW, FILE_READ);
    ok = r && r.size() == csv.length();
    if (r) r.close();
  }
  if (ok) {
    sdFs->remove(FILE_REGISTERS_BAK);
    if (sdFs->exists(FILE_REGISTERS)) ok = sdFs->rename(FILE_REGISTERS, FILE_REGISTERS_BAK);
    if (ok) ok = sdFs->rename(FILE_REGISTERS_NEW, FILE_REGISTERS);
    if (!ok && !sdFs->exists(FILE_REGISTERS) && sdFs->exists(FILE_REGISTERS_BAK))
      sdFs->rename(FILE_REGISTERS_BAK, FILE_REGISTERS);   // put the old table back
  }
  if (!ok) {
    sdFs->remove(FILE_REGISTERS_NEW);
    err = "SD card write failed";
  }
  xSemaphoreGive(sdMutex);
  return ok;
}

bool removeFile(String &err) {
  if (!sdFs || !st.sdOk) {
    err = "no working SD card";
    return false;
  }
  xSemaphoreTake(sdMutex, portMAX_DELAY);
  bool ok = true;
  if (sdFs->exists(FILE_REGISTERS)) {
    sdFs->remove(FILE_REGISTERS_BAK);
    ok = sdFs->rename(FILE_REGISTERS, FILE_REGISTERS_BAK);
  }
  xSemaphoreGive(sdMutex);
  if (!ok) err = "SD card rename failed";
  return ok;
}

}  // namespace meter
