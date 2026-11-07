#include "storage.h"

#include <SD.h>
#include <SPI.h>

#include <deque>

#include "app.h"
#include "settings.h"

namespace store {

static uint32_t curYmd = 0;
static uint8_t curPart = 0;
static String curHeader;

static uint32_t pYmd = 0;      // upload pointer
static uint8_t pPart = 1;
static uint32_t pOffset = 0;

static std::deque<String> ram;   // rows waiting while the SD card is down
static String ramHeader;
static SemaphoreHandle_t ramMtx;

static uint32_t lastRemountMs = 0, lastSpaceCheckMs = 0;

fs::FS &fs() { return SD; }

String dayPath(uint32_t ymd, uint8_t part) {
  char p[40];
  unsigned y = ymd / 10000, m = (ymd / 100) % 100, d = ymd % 100;
  if (part <= 1)
    snprintf(p, sizeof(p), DIR_DATA "/%04u/%02u/%04u-%02u-%02u.csv", y, m, y, m, d);
  else
    snprintf(p, sizeof(p), DIR_DATA "/%04u/%02u/%04u-%02u-%02u_%u.csv", y, m, y, m, d, part);
  return String(p);
}

static bool mount() {
  int sck = cfg::getInt("pin_sd_sck"), miso = cfg::getInt("pin_sd_miso");
  int mosi = cfg::getInt("pin_sd_mosi"), cs = cfg::getInt("pin_sd_cs");
  SD.end();
  SPI.end();
  SPI.begin(sck, miso, mosi, cs);
  if (!SD.begin(cs, SPI, 4000000, "/sd", 8)) return false;
  SD.mkdir(DIR_DATA);
  SD.mkdir(DIR_LOG);
  SD.mkdir("/state");
  SD.mkdir("/config");
  return true;
}

static void loadPointer() {
  pYmd = 0;
  File f = SD.open(FILE_UPLOAD_PTR, FILE_READ);
  if (f) {
    f.setTimeout(10);
    String s = f.readStringUntil('\n');
    f.close();
    unsigned long y = 0, p = 1, o = 0;
    if (sscanf(s.c_str(), "%lu %lu %lu", &y, &p, &o) == 3 && y > 20200101) {
      pYmd = y;
      pPart = p;
      pOffset = o;
    }
  }
}

static void savePointer() {
  File f = SD.open(FILE_UPLOAD_PTR, FILE_WRITE);
  if (f) {
    f.printf("%lu %u %lu\n", (unsigned long)pYmd, pPart, (unsigned long)pOffset);
    f.close();
  }
}

bool begin() {
  ramMtx = xSemaphoreCreateMutex();
  xSemaphoreTake(sdMutex, portMAX_DELAY);
  bool ok = mount();
  if (ok) loadPointer();
  xSemaphoreGive(sdMutex);
  st.sdOk = ok;
  if (ok)
    evlog("SD card ok: %llu MB, %llu MB used, upload pointer %s", SD.totalBytes() >> 20, SD.usedBytes() >> 20,
          pointerText().c_str());
  else
    evlog("SD card NOT mounted (card in? FAT32? pins?): records kept in RAM only (%d rows)", RAM_QUEUE_ROWS);
  return ok;
}

// The part of the day whose header matches; a new part if the columns changed.
static uint8_t findPart(uint32_t ymd, const String &header) {
  char dir[24];
  snprintf(dir, sizeof(dir), DIR_DATA "/%04lu", (unsigned long)(ymd / 10000));
  SD.mkdir(dir);
  snprintf(dir, sizeof(dir), DIR_DATA "/%04lu/%02lu", (unsigned long)(ymd / 10000),
           (unsigned long)((ymd / 100) % 100));
  SD.mkdir(dir);
  for (uint8_t p = 1; p < 50; p++) {
    String path = dayPath(ymd, p);
    if (!SD.exists(path)) {
      File f = SD.open(path, FILE_WRITE);
      if (!f) return 0;
      f.print(header);
      f.print('\n');
      f.close();
      return p;
    }
    File f = SD.open(path, FILE_READ);
    if (!f) return 0;
    f.setTimeout(10);
    String h = f.readStringUntil('\n');
    // A power cut during a write can leave a last line without its newline: close it.
    bool needNl = false;
    if (f.size() > 0) {
      f.seek(f.size() - 1);
      needNl = f.read() != '\n';
    }
    f.close();
    if (h == header) {
      if (needNl) {
        File a = SD.open(path, FILE_APPEND);
        if (a) {
          a.print('\n');
          a.close();
        }
      }
      return p;
    }
  }
  return 0;
}

bool appendRow(time_t minuteTs, const String &header, const String &row) {
  bool ok = false, wasOk = st.sdOk;
  if (st.sdOk && xSemaphoreTake(sdMutex, pdMS_TO_TICKS(5000)) == pdTRUE) {
    uint32_t ymd = ymdOf(minuteTs);
    if (ymd != curYmd || header != curHeader || curPart == 0) {
      curPart = findPart(ymd, header);
      curYmd = ymd;
      curHeader = header;
    }
    if (curPart) {
      File f = SD.open(dayPath(ymd, curPart), FILE_APPEND);
      if (f) {
        size_t n = f.print(row);
        n += f.print('\n');
        f.close();
        ok = n == row.length() + 1;
      }
    }
    if (pYmd == 0 && ok) {   // first ever record: start the upload pointer here
      pYmd = ymd;
      pPart = curPart;
      pOffset = 0;
      savePointer();
    }
    xSemaphoreGive(sdMutex);
  }
  if (ok) {
    st.rowsWritten++;
    return true;
  }
  if (wasOk) {
    st.sdOk = false;
    st.sdErrors++;
    curPart = 0;
    evlog("SD write FAILED: switching to the RAM queue (%d rows max)", RAM_QUEUE_ROWS);
  }
  xSemaphoreTake(ramMtx, portMAX_DELAY);
  if (ramHeader != header) {
    ram.clear();   // columns changed: rows with the old header cannot share a batch
    ramHeader = header;
  }
  ram.push_back(row);
  while (ram.size() > RAM_QUEUE_ROWS) ram.pop_front();
  xSemaphoreGive(ramMtx);
  return false;
}

static bool batchFromRam(Batch &b, int maxRows, size_t maxBytes) {
  xSemaphoreTake(ramMtx, portMAX_DELAY);
  b = Batch();
  b.fromRam = true;
  b.header = ramHeader;
  for (size_t i = 0; i < ram.size() && b.rows < maxRows && b.body.length() + ram[i].length() < maxBytes; i++) {
    b.body += ram[i];
    b.body += '\n';
    if (!b.rows) b.firstTs = parseIso(ram[i].c_str());
    b.lastTs = parseIso(ram[i].c_str());
    b.rows++;
  }
  xSemaphoreGive(ramMtx);
  return b.rows > 0;
}

bool nextBatch(Batch &b, int maxRows, size_t maxBytes) {
  if (!st.sdOk) return batchFromRam(b, maxRows, maxBytes);
  if (!timeValid()) return false;
  uint32_t today = ymdOf(time(nullptr));
  if (xSemaphoreTake(sdMutex, pdMS_TO_TICKS(5000)) != pdTRUE) return false;
  bool found = false;
  b = Batch();
  if (pYmd == 0) pYmd = today;
  for (int guard = 0; guard < 800 && !found; guard++) {
    if (pYmd > today) break;
    String path = dayPath(pYmd, pPart);
    File f = SD.open(path, FILE_READ);
    if (!f) {
      if (pYmd < today) {   // missing day (logger was off): go to the next day
        pYmd = nextYmd(pYmd);
        pPart = 1;
        pOffset = 0;
        continue;
      }
      break;   // today's file does not exist yet
    }
    f.setTimeout(10);   // readStringUntil must not wait at the end of the file
    b.header = f.readStringUntil('\n');
    uint32_t hdrEnd = f.position();
    if (pOffset < hdrEnd) pOffset = hdrEnd;
    f.seek(pOffset);
    uint32_t pos = pOffset;
    while (f.available() && b.rows < maxRows) {
      String line = f.readStringUntil('\n');
      uint32_t np = f.position();
      bool complete = np - pos == line.length() + 1;
      if (!complete) break;                                  // being written: next time
      if (b.body.length() + line.length() + 1 > maxBytes) break;
      pos = np;
      if (line.length() < 20) continue;                      // empty or broken line
      b.body += line;
      b.body += '\n';
      if (!b.rows) b.firstTs = parseIso(line.c_str());
      b.lastTs = parseIso(line.c_str());
      b.rows++;
    }
    f.close();
    if (b.rows) {
      b.ymd = pYmd;
      b.part = pPart;
      b.offset = pos;
      found = true;
      break;
    }
    if (pos != pOffset) {   // only broken lines: skip them
      pOffset = pos;
      continue;
    }
    // Nothing left in this file: move on if a later part or day exists.
    if (SD.exists(dayPath(pYmd, pPart + 1))) {
      pPart++;
      pOffset = 0;
    } else if (pYmd < today) {
      pYmd = nextYmd(pYmd);
      pPart = 1;
      pOffset = 0;
    } else {
      break;
    }
  }
  xSemaphoreGive(sdMutex);
  return found;
}

void commit(const Batch &b) {
  if (b.fromRam) {
    xSemaphoreTake(ramMtx, portMAX_DELAY);
    for (int i = 0; i < b.rows && !ram.empty(); i++) ram.pop_front();
    xSemaphoreGive(ramMtx);
    return;
  }
  if (xSemaphoreTake(sdMutex, pdMS_TO_TICKS(5000)) != pdTRUE) return;
  pYmd = b.ymd;
  pPart = b.part;
  pOffset = b.offset;
  savePointer();
  xSemaphoreGive(sdMutex);
}

void resendFrom(uint32_t ymd) {
  xSemaphoreTake(sdMutex, portMAX_DELAY);
  pYmd = ymd;
  pPart = 1;
  pOffset = 0;
  savePointer();
  xSemaphoreGive(sdMutex);
  evlog("Upload pointer moved back to %lu: those days are sent again (the server drops duplicates)",
        (unsigned long)ymd);
}

String pointerText() {
  char b[40];
  snprintf(b, sizeof(b), "%lu part %u offset %lu", (unsigned long)pYmd, pPart, (unsigned long)pOffset);
  return String(b);
}

int ramRows() {
  xSemaphoreTake(ramMtx, portMAX_DELAY);
  int n = ram.size();
  xSemaphoreGive(ramMtx);
  return n;
}

// Smallest entry name of a folder (folders when dirs is true, else files). One file open at a time
// below the folder itself: the SD driver allows few open files.
static String smallestEntry(const String &dir, bool dirs) {
  String best;
  File d = SD.open(dir);
  if (!d) return best;
  for (File e = d.openNextFile(); e; e = d.openNextFile()) {
    String n = e.name();
    bool isDir = e.isDirectory();
    e.close();
    if (isDir == dirs && (best.length() == 0 || n < best)) best = n;
  }
  d.close();
  return best;
}

// Deletes the oldest day file of the card if it is already uploaded. Returns its path, or "".
static String deleteOldest() {
  for (int tries = 0; tries < 4; tries++) {
    String y = smallestEntry(DIR_DATA, true);
    if (!y.length()) return "";
    String yp = String(DIR_DATA "/") + y;
    String m = smallestEntry(yp, true);
    if (!m.length()) {
      SD.rmdir(yp);
      continue;
    }
    String mp = yp + "/" + m;
    String n = smallestEntry(mp, false);
    if (!n.length()) {
      SD.rmdir(mp);
      continue;
    }
    if (n.length() < 14) return "";
    uint32_t ymd = n.substring(0, 4).toInt() * 10000 + n.substring(5, 7).toInt() * 100 + n.substring(8, 10).toInt();
    if (ymd >= pYmd) return "";   // never delete data that is not sent yet
    String path = mp + "/" + n;
    SD.remove(path);
    return path;
  }
  return "";
}

void housekeeping() {
  if (!st.sdOk) {
    if (millis() - lastRemountMs < 60000) return;
    lastRemountMs = millis();
    xSemaphoreTake(sdMutex, portMAX_DELAY);
    bool ok = mount();
    if (ok) loadPointer();
    xSemaphoreGive(sdMutex);
    if (!ok) return;
    st.sdOk = true;
    curPart = 0;
    evlog("SD card back: writing %d rows from the RAM queue to the card", ramRows());
    // Rows still in RAM go to the card; they are uploaded from there.
    xSemaphoreTake(ramMtx, portMAX_DELAY);
    std::deque<String> rows;
    rows.swap(ram);
    String hdr = ramHeader;
    xSemaphoreGive(ramMtx);
    for (auto &r : rows) {
      time_t t = parseIso(r.c_str());
      if (t) appendRow(t, hdr, r);
    }
    return;
  }
  if (lastSpaceCheckMs && millis() - lastSpaceCheckMs < 3600000UL) return;
  lastSpaceCheckMs = millis();
  int minFree = cfg::getInt("sd_min_free");
  if (minFree <= 0) return;
  int deleted = 0;
  String last;
  xSemaphoreTake(sdMutex, portMAX_DELAY);
  for (int i = 0; i < 60; i++) {
    uint64_t total = SD.totalBytes(), used = SD.usedBytes();
    if (!total || (total - used) * 100 / total >= (uint64_t)minFree) break;
    String p = deleteOldest();
    if (!p.length()) break;
    last = p;
    deleted++;
  }
  xSemaphoreGive(sdMutex);
  if (deleted) evlog("SD nearly full: deleted %d uploaded day file(s), the newest of them %s", deleted, last.c_str());
}

}  // namespace store
