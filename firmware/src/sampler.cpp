#include "sampler.h"

#include <ArduinoJson.h>
#include <esp_task_wdt.h>
#include <sys/time.h>

#include "app.h"
#include "meter.h"
#include "sensors.h"
#include "settings.h"
#include "storage.h"

namespace sampler {

struct Acc {
  double sum = 0, max = -1e300, last = 0;
  uint16_t n = 0;
  void add(double v) {
    sum += v;
    if (v > max) max = v;
    last = v;
    n++;
  }
  void reset() { *this = Acc(); }
  double mean() const { return sum / n; }
};

static Acc accM[MAX_METERS][MAX_REGS];
static uint16_t meterSamples[MAX_METERS];
static Acc acc1T, acc1H, acc2T, acc2H;
static time_t accMinute = 0;
static String hdr;
static bool th1Col = true, th2Col = true;
static int periodS = 15;
static bool firstRow = true;

static SemaphoreHandle_t snapMtx;
static String snapJson, lastText;
static uint32_t snapSeq = 0;

static int decimalsFor(double scale, bool mean) {
  int d = 0;
  while (d < 4 && scale < 0.999) {
    scale *= 10;
    d++;
  }
  return min(4, d + (mean ? 1 : 0));
}

static String buildHeader() {
  String h = "ts";
  for (int m = 0; m < meter::count(); m++) {
    String id = meter::get(m).id;
    for (int j = 0; j < meter::regCount(); j++) {
      const meter::Reg &r = meter::reg(j);
      h += "," + id + "_" + r.name;
      if (r.agg == meter::MEANMAX) h += "," + id + "_" + r.name + "_max";
    }
    h += "," + id + "_n";
  }
  if (th1Col) h += ",TH1_t,TH1_rh,TH1_n";
  if (th2Col) h += ",TH2_t,TH2_rh,TH2_n";
  h += ",rssi,heap_kb,up_s,backlog_min,boot";
  return h;
}

String header() { return hdr; }

static void num(String &s, const Acc &a, bool useMean, int dec) {
  s += ',';
  if (a.n) s += String(useMean ? a.mean() : a.last, dec);
}

static void flushMinute(time_t minute) {
  String row = isoTime(minute);
  for (int m = 0; m < meter::count(); m++) {
    for (int j = 0; j < meter::regCount(); j++) {
      const meter::Reg &r = meter::reg(j);
      bool mean = r.agg != meter::LAST;
      int dec = decimalsFor(r.scale, mean);
      num(row, accM[m][j], mean, dec);
      if (r.agg == meter::MEANMAX) {
        row += ',';
        if (accM[m][j].n) row += String(accM[m][j].max, dec);
      }
    }
    row += ',';
    row += String(meterSamples[m]);
  }
  if (th1Col) {
    num(row, acc1T, true, 2);
    num(row, acc1H, true, 1);
    row += "," + String(acc1T.n);
  }
  if (th2Col) {
    num(row, acc2T, true, 2);
    num(row, acc2H, true, 1);
    row += "," + String(acc2T.n);
  }
  row += ',';
  if (st.wifiUp) row += String((int)st.rssi);
  row += "," + String(ESP.getFreeHeap() / 1024);
  row += "," + String(millis() / 1000);
  row += "," + String((int)st.backlogMin);
  row += ',';
  if (firstRow) row += st.bootReason;   // only on the first record after a boot
  firstRow = false;
  store::appendRow(minute, hdr, row);
  st.lastRowTs = minute;
}

static void resetAcc() {
  for (int m = 0; m < MAX_METERS; m++) {
    meterSamples[m] = 0;
    for (int j = 0; j < MAX_REGS; j++) accM[m][j].reset();
  }
  acc1T.reset();
  acc1H.reset();
  acc2T.reset();
  acc2H.reset();
}

static void tick() {
  time_t now = time(nullptr);
  bool tv = timeValid();
  st.timeValid = tv;
  if (tv) {
    time_t minute = now - now % 60;
    if (minute != accMinute) {
      if (accMinute) flushMinute(accMinute);
      resetAcc();
      accMinute = minute;
    }
  }

  JsonDocument doc;
  doc["device"] = cfg::get("dev_id");
  if (tv) doc["ts"] = isoTime(now);
  JsonObject vals = doc["values"].to<JsonObject>();
  String text;

  static double v[MAX_REGS];
  static bool ok[MAX_REGS];
  for (int m = 0; m < meter::count(); m++) {
    String id = meter::get(m).id;
    bool any = meter::read(m, v, ok);
    if (any) meterSamples[m]++;
    for (int j = 0; j < meter::regCount(); j++) {
      if (!ok[j]) continue;
      accM[m][j].add(v[j]);
      const meter::Reg &r = meter::reg(j);
      vals[id + "_" + r.name] = serialized(String(v[j], decimalsFor(r.scale, false)));
      text += id + "_" + r.name + "=" + String(v[j], decimalsFor(r.scale, false)) + " ";
    }
    if (!any) text += id + ": no answer (" + String((int)st.meterFailRun[m]) + " in a row) ";
  }
  float t, h;
  if (th1Col && sensors::readTH1(t, h)) {
    acc1T.add(t);
    acc1H.add(h);
    vals["TH1_t"] = serialized(String(t, 2));
    vals["TH1_rh"] = serialized(String(h, 1));
    text += "TH1=" + String(t, 1) + "C/" + String(h, 0) + "% ";
  } else if (th1Col) {
    text += "TH1=fault ";
  }
  if (th2Col && sensors::readTH2(t, h)) {
    acc2T.add(t);
    acc2H.add(h);
    vals["TH2_t"] = serialized(String(t, 2));
    vals["TH2_rh"] = serialized(String(h, 1));
    text += "TH2=" + String(t, 1) + "C/" + String(h, 0) + "% ";
  } else if (th2Col) {
    text += "TH2=fault ";
  }
  JsonObject sys = doc["sys"].to<JsonObject>();
  if (st.wifiUp) sys["rssi"] = (int)st.rssi;
  sys["up_s"] = (uint32_t)(millis() / 1000);
  sys["backlog_min"] = (int)st.backlogMin;
  sys["sd"] = (bool)st.sdOk;
  sys["fw"] = FW_VERSION;
  st.lastSampleTs = now;

  if (tv) {
    String js;
    serializeJson(doc, js);
    xSemaphoreTake(snapMtx, portMAX_DELAY);
    snapJson = js;
    snapSeq++;
    lastText = text;
    xSemaphoreGive(snapMtx);
  } else {
    xSemaphoreTake(snapMtx, portMAX_DELAY);
    lastText = "(clock not set, nothing recorded) " + text;
    xSemaphoreGive(snapMtx);
  }
}

uint32_t snapshot(String &json) {
  xSemaphoreTake(snapMtx, portMAX_DELAY);
  json = snapJson;
  uint32_t s = snapSeq;
  xSemaphoreGive(snapMtx);
  return s;
}

String lastValuesText() {
  xSemaphoreTake(snapMtx, portMAX_DELAY);
  String s = lastText;
  xSemaphoreGive(snapMtx);
  return s;
}

static void task(void *) {
  esp_task_wdt_add(nullptr);
  uint32_t lastHouse = 0;
  for (;;) {
    // Wait for the next multiple of the period on the clock (or just the period without a clock).
    struct timeval tv;
    gettimeofday(&tv, nullptr);
    long waitMs = periodS * 1000L;
    if (timeValid()) waitMs = periodS * 1000L - ((tv.tv_sec % periodS) * 1000L + tv.tv_usec / 1000);
    while (waitMs > 0) {
      long d = min(waitMs, 1000L);
      vTaskDelay(pdMS_TO_TICKS(d));
      waitMs -= d;
      esp_task_wdt_reset();
    }
    tick();
    esp_task_wdt_reset();
    if (millis() - lastHouse > 60000) {
      lastHouse = millis();
      store::housekeeping();
    }
  }
}

void begin() {
  snapMtx = xSemaphoreCreateMutex();
  periodS = cfg::getInt("sample_s");
  if (periodS < 5 || periodS > 60 || 60 % periodS) periodS = 15;
  th1Col = cfg::get("th1_type") != "none";
  th2Col = sensors::th2Enabled();
  hdr = buildHeader();
  int cols = 1;
  for (size_t i = 0; i < hdr.length(); i++) cols += hdr[i] == ',';
  evlog("Sampling every %d s, %d columns", periodS, cols);
  xTaskCreatePinnedToCore(task, "sampler", 12288, nullptr, 2, nullptr, 1);
}

}  // namespace sampler
