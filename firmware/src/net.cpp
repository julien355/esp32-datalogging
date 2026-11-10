#include "net.h"

#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <Update.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <esp_task_wdt.h>

#include "app.h"
#include "certs.h"
#include "meter.h"
#include "rtclock.h"
#include "sampler.h"
#include "settings.h"
#include "storage.h"

namespace net {

static WiFiClientSecure tls;
static WiFiClient plain;
static bool https = true;
static String baseUrl, token, devId;
static uint32_t uploadPeriodMs = 60000, otaPeriodMs = 6UL * 3600000UL;
static int batchRows = 60;
static bool liveOn = true, otaOn = false, rcfgOn = true;
static uint32_t rcfgPeriodMs = 15UL * 60000UL, lastRcfg = 0;
static bool rcfgReported = false;
static volatile bool forceRcfg = false;
static long regRefused = 0;          // remote register table version refused since boot (not retried)
static String regError;

static volatile bool forceUpload = false, forceOta = false, hintOta = false;
static uint32_t lastUploadTry = 0, lastOta = 0, authBlockedUntil = 0, liveBlockedUntil = 0;
static uint32_t nextWifiAttempt = 0, lastStackReset = 0;
static int wifiAttempts = 0, uploadFailRun = 0, rejectRun = 0, liveFailRun = 0;
static String wifiSeen = "not scanned";   // configured networks in range at the last scan (log, status)
static uint32_t lastLiveSeq = 0;
static String lastUploadError = "none yet";

static WiFiClient &client() { return https ? (WiFiClient &)tls : plain; }

static void wdtDelay(uint32_t ms) {
  while (ms) {
    uint32_t d = ms > 500 ? 500 : ms;
    vTaskDelay(pdMS_TO_TICKS(d));
    ms -= d;
    esp_task_wdt_reset();
  }
}

// ---------------------------------------------------------------- WiFi

static bool tryConnect(const String &ssid, const String &pass) {
  Serial.printf("WiFi: connecting to \"%s\"\n", ssid.c_str());
  WiFi.disconnect(false, false);
  WiFi.begin(ssid.c_str(), pass.c_str());
  for (int i = 0; i < 80; i++) {   // 20 s
    if (WiFi.status() == WL_CONNECTED) return true;
    wdtDelay(250);
  }
  return false;
}

// The logger moves between sites: wifi_ssid and wifi_ssid2 are two networks of equal rank.
// One round scans first and tries only the configured networks in range (wifi_ssid first if both
// are), so it does not spend 20 s on a network of the other site. If the scan saw neither (hidden
// network, missed beacon, or the setup portal is open and no scan is made), it tries both.
// Once connected it stays on that network: nothing is looked for until the link drops.
static bool connectAvailable(const String &s1, const String &s2) {
  bool seen1 = false, seen2 = false;
  if (st.portalOn) {
    wifiSeen = "not scanned (setup portal open)";   // a scan would empty the portal's network list
  } else {
    WiFi.disconnect(false, false);   // stop any connection attempt still running, or the scan is refused
    int n = WiFi.scanNetworks(false, false, false, 150);
    for (int i = 0; i < n; i++) {
      String s = WiFi.SSID(i);
      if (s1.length() && s == s1) seen1 = true;
      if (s2.length() && s == s2) seen2 = true;
    }
    WiFi.scanDelete();
    wifiSeen = n < 0 ? String("scan failed")
               : seen1 && seen2 ? "\"" + s1 + "\" and \"" + s2 + "\""
               : seen1 ? "\"" + s1 + "\""
               : seen2 ? "\"" + s2 + "\""
                       : String("none of the two (") + n + " other networks)";
  }
  bool any = seen1 || seen2;
  if (s1.length() && (seen1 || !any) && tryConnect(s1, cfg::get("wifi_pass"))) return true;
  if (s2.length() && (seen2 || !any) && tryConnect(s2, cfg::get("wifi_pass2"))) return true;
  return false;
}

static void handleOffline() {
  String s1 = cfg::get("wifi_ssid"), s2 = cfg::get("wifi_ssid2");
  if (!s1.length() && !s2.length()) {   // nothing configured: the setup portal is open
    wdtDelay(1000);
    return;
  }
  uint32_t now = millis();
  uint32_t downMs = st.wifiDownSince ? now - st.wifiDownSince : 0;

  long rebootH = cfg::getInt("offline_rbt_h");
  if (rebootH > 0 && downMs > (uint32_t)rebootH * 3600000UL && !st.portalOn) safeRestart("offline");

  // Every 30 min offline: restart the WiFi driver (cures most stuck radios).
  if (downMs > 1800000UL && now - lastStackReset > 1800000UL) {
    lastStackReset = now;
    evlog("WiFi offline for %lu min: restarting the WiFi driver", (unsigned long)(downMs / 60000));
    WiFi.disconnect(true);
    WiFi.mode(WIFI_OFF);
    wdtDelay(1000);
    WiFi.mode(st.portalOn ? WIFI_AP_STA : WIFI_STA);
    WiFi.setSleep(false);
  }

  if ((int32_t)(now - nextWifiAttempt) < 0) {
    wdtDelay(500);
    return;
  }
  if (connectAvailable(s1, s2)) {
    wifiAttempts = 0;
    return;
  }
  wifiAttempts++;
  // Back-off: 10, 20, 40, 80, 160, then every 300 s. Slower while the setup portal is open,
  // because scanning for the network moves the portal's channel.
  uint32_t backoff = min<uint32_t>(300, 10u << min(wifiAttempts - 1, 5));
  if (st.portalOn) backoff = max<uint32_t>(backoff, 120);
  nextWifiAttempt = millis() + backoff * 1000;
  if (wifiAttempts == 1 || wifiAttempts % 10 == 0)
    evlog("WiFi: connection failed (attempt %d, status %d, in range: %s), next try in %lu s", wifiAttempts,
          WiFi.status(), wifiSeen.c_str(), (unsigned long)backoff);
}

// ---------------------------------------------------------------- HTTP

static int request(const char *method, const String &path, const char *contentType, const String &body,
                   String &resp, uint32_t timeoutMs) {
  HTTPClient http;
  http.setReuse(true);
  http.setConnectTimeout(10000);
  http.setTimeout(timeoutMs);
  if (!http.begin(client(), baseUrl + path)) return -100;
  http.addHeader("Authorization", "Bearer " + token);
  http.addHeader("X-Device", devId);
  http.addHeader("X-Fw", FW_VERSION);
  http.addHeader("X-Schema", String(CSV_SCHEMA));
  int code;
  if (strcmp(method, "GET") == 0) {
    code = http.GET();
  } else {
    http.addHeader("Content-Type", contentType);
    code = http.POST((uint8_t *)body.c_str(), body.length());
  }
  // 1xx, 204 and 304 have no body. Do not call getString() on them: with no Content-Length and a
  // kept-alive connection, HTTPClient reads until the server closes (no timeout), and the task
  // watchdog reboots the board.
  if (code >= 200 && code != 204 && code != 304) resp = http.getString();
  http.end();
  return code;
}

static void doUpload() {
  bool due = forceUpload || millis() - lastUploadTry >= uploadPeriodMs || lastUploadTry == 0;
  if (!due) return;
  if (!token.length()) {
    if (forceUpload || lastUploadTry == 0) evlog("Upload: no dev_token set, nothing sent (records stay on the SD card)");
    forceUpload = false;
    lastUploadTry = millis();
    return;
  }
  if ((int32_t)(millis() - authBlockedUntil) < 0 && !forceUpload) return;
  forceUpload = false;
  lastUploadTry = millis();
  for (int i = 0; i < CATCHUP_BATCHES; i++) {
    esp_task_wdt_reset();
    store::Batch b;
    if (!store::nextBatch(b, batchRows, MAX_BATCH_BYTES)) {
      st.backlogMin = 0;
      return;
    }
    if (timeValid() && b.firstTs) {
      long m = (long)(time(nullptr) - b.firstTs) / 60 - 1;   // the row of minute M is written at M+1
      st.backlogMin = m > 0 ? m : 0;
    }
    String resp;
    int code = request("POST", "/api/v1/ingest", "text/csv", b.header + "\n" + b.body, resp, HTTP_TIMEOUT_MS);
    if (code == 200) {
      store::commit(b);
      st.uploadsOk++;
      st.lastUploadOk = time(nullptr);
      uploadFailRun = rejectRun = 0;
      if (b.rows < batchRows) {   // that was the tail
        st.backlogMin = 0;
        return;
      }
      continue;   // backlog: next batch at once
    }
    st.uploadsFail++;
    lastUploadError = String(code) + " " + resp.substring(0, 80);
    if (code == 400 || code == 413 || code == 422) {
      if (++rejectRun >= 3) {
        evlog("Upload: server refused a batch 3 times (%s): skipped, rows %s..%s stay on the SD card",
              lastUploadError.c_str(), isoTime(b.firstTs).c_str(), isoTime(b.lastTs).c_str());
        store::commit(b);
        rejectRun = 0;
      }
    } else if (code == 401 || code == 403) {
      evlog("Upload: token refused (%d): check dev_token. Retrying in 10 min", code);
      authBlockedUntil = millis() + 600000UL;
    } else {
      if (++uploadFailRun % 5 == 0) {
        evlog("Upload: %d failures in a row (last: %s): new connection", uploadFailRun, lastUploadError.c_str());
        client().stop();
      }
    }
    return;
  }
}

static void doLive() {
  if (!liveOn || !token.length()) return;
  if ((int32_t)(millis() - liveBlockedUntil) < 0) return;
  String js;
  uint32_t seq = sampler::snapshot(js);
  if (seq == lastLiveSeq || !js.length()) return;
  lastLiveSeq = seq;
  String resp;
  int code = request("POST", "/api/v1/live", "application/json", js, resp, LIVE_TIMEOUT_MS);
  if (code == 200 || code == 204) {
    st.liveOk++;
    liveFailRun = 0;
    // 200 {"ota":1}: someone offered this logger a firmware on the platform: check at once
    // instead of waiting for the next periodic check (doOta limits it to once per 5 min).
    if (code == 200 && resp.indexOf("\"ota\"") >= 0) hintOta = true;   // body {"ota": 1}
  } else {
    st.liveFail++;
    if (++liveFailRun >= 3) liveBlockedUntil = millis() + 120000UL;   // do not hold up the uploads
  }
}

// ---------------------------------------------------------------- OTA

static void doOta() {
  if (!otaOn && !forceOta) return;
  if (st.safeMode) return;
  bool hinted = hintOta && otaOn && millis() > 120000UL && (!lastOta || millis() - lastOta >= 300000UL);
  if (!forceOta && !hinted && (millis() < 120000UL || (lastOta && millis() - lastOta < otaPeriodMs))) return;
  bool byHand = forceOta;
  forceOta = hintOta = false;
  lastOta = millis();
  String resp;
  int code = request("GET", String("/api/v1/ota?fw=") + FW_VERSION, "", "", resp, HTTP_TIMEOUT_MS);
  if (code == 204) return;
  if (code != 200) {
    evlog("OTA check: HTTP %d", code);
    return;
  }
  JsonDocument doc;
  if (deserializeJson(doc, resp)) return;
  String ver = doc["version"] | "", url = doc["url"] | "", md5 = doc["md5"] | "";
  if (!ver.length() || ver == FW_VERSION || !url.length()) return;
  long bad = cfg::getCounter("ota_bad");
  if (bad && bad == fwHash(ver.c_str())) {
    if (!byHand) {
      static long told = 0;   // log it once, not at every check
      if (told != bad) evlog("OTA: %s skipped, it was rolled back before (console 'ota' to try it again)", ver.c_str());
      told = bad;
      return;
    }
    cfg::setCounter("ota_bad", 0);
  }
  evlog("OTA: updating %s -> %s", FW_VERSION, ver.c_str());

  HTTPClient http;
  http.setConnectTimeout(10000);
  http.setTimeout(HTTP_TIMEOUT_MS);
  if (!http.begin(client(), baseUrl + url)) return;
  http.addHeader("Authorization", "Bearer " + token);
  code = http.GET();
  int len = http.getSize();
  if (code != 200 || len <= 0) {
    evlog("OTA: download failed (HTTP %d, size %d)", code, len);
    http.end();
    return;
  }
  if (!Update.begin(len)) {
    evlog("OTA: not enough space (%d bytes)", len);
    http.end();
    return;
  }
  if (md5.length() == 32) Update.setMD5(md5.c_str());
  WiFiClient *s = http.getStreamPtr();
  uint8_t buf[1024];
  int done = 0;
  uint32_t lastData = millis();
  while (done < len && millis() - lastData < 30000) {
    esp_task_wdt_reset();
    size_t avail = s->available();
    if (!avail) {
      vTaskDelay(pdMS_TO_TICKS(10));
      continue;
    }
    int n = s->readBytes(buf, min(avail, sizeof(buf)));
    if (n <= 0) continue;
    if (Update.write(buf, n) != (size_t)n) break;
    done += n;
    lastData = millis();
  }
  http.end();
  if (done != len || !Update.end(true)) {
    evlog("OTA: failed after %d of %d bytes (%s)", done, len, Update.errorString());
    Update.abort();
    return;
  }
  cfg::setCounter("ota_try", 1);   // main.cpp rolls back if the new firmware keeps rebooting
  cfg::setCounter("bootcnt", 0);
  evlog("OTA: %s written and verified, restarting", ver.c_str());
  safeRestart("ota");
}

// ---------------------------------------------------------------- remote settings

// Never changed from the platform: a wrong value here would cut the logger off for good.
static const char *REMOTE_BLOCKED[] = {"dev_id", "dev_token", "srv_url", "tls_verify", "wifi_ssid",
                                       "wifi_pass", "wifi_ssid2", "wifi_pass2", "portal_pass"};

static bool remoteAllowed(const char *key) {
  const cfg::Def *d = cfg::find(key);
  if (!d || (d->flags & cfg::SECRET)) return false;
  for (const char *b : REMOTE_BLOCKED)
    if (strcmp(b, key) == 0) return false;
  return true;
}

// After each boot: tell the platform the firmware, settings (secrets left out) and sensors found.
static void reportSettings() {
  JsonDocument doc;
  doc["fw"] = FW_VERSION;
  doc["env"] = FW_VARIANT;
  doc["fw_tag"] = FW_TAG;   // also keeps the marker in the binary for the platform's check
  doc["schema"] = CSV_SCHEMA;
  doc["cfg_version"] = cfg::getCounter("cfg_ver");
  doc["boot"] = st.bootReason;
  doc["th1_chip"] = st.th1Chip;
  doc["header"] = sampler::header();
  doc["reg_version"] = cfg::getCounter("reg_ver");
  doc["reg_source"] = meter::source();
  doc["registers"] = meter::describeTable();
  if (regRefused) {
    doc["reg_refused"] = regRefused;
    doc["reg_error"] = regError;
  }
  JsonObject set = doc["settings"].to<JsonObject>();
  for (size_t i = 0; i < cfg::NDEFS; i++) {
    const cfg::Def &d = cfg::DEFS[i];
    if (d.flags & cfg::SECRET) set[d.key] = cfg::get(d.key).length() ? "(set)" : "(empty)";
    else set[d.key] = cfg::get(d.key);
  }
  String js, resp;
  serializeJson(doc, js);
  int code = request("POST", "/api/v1/config/report", "application/json", js, resp, HTTP_TIMEOUT_MS);
  if (code == 200 || code == 204) rcfgReported = true;
}

// Register table sent by the platform's register page. Returns true when a new table was written to the
// card (the caller restarts so that the meter reads it). A table that fails the checks is refused, logged
// and reported, and not tried again until the next boot.
static bool doRemoteRegisters() {
  String resp;
  int code = request("GET", "/api/v1/registers", "", "", resp, HTTP_TIMEOUT_MS);
  if (code != 200) return false;   // 204: nothing set; 404: older server
  JsonDocument doc;
  if (deserializeJson(doc, resp)) return false;
  long ver = doc["version"] | 0L;
  if (ver <= cfg::getCounter("reg_ver") || ver == regRefused) return false;
  bool builtin = doc["builtin"] | false;
  String csv = doc["csv"].as<String>();
  String err;
  bool ok = builtin ? meter::removeFile(err) : meter::installFile(csv, err);
  if (!ok) {
    regRefused = ver;
    regError = err;
    rcfgReported = false;   // tell the platform why
    evlog("Remote register table version %ld refused: %s", ver, err.c_str());
    return false;
  }
  cfg::setCounter("reg_ver", ver);
  evlog("Remote register table version %ld: %s", ver,
        builtin ? "back to the built-in table" : "written to " FILE_REGISTERS);
  return true;
}

static void doRemoteConfig() {
  if (!token.length()) return;
  if (!rcfgReported) reportSettings();
  if (!rcfgOn && !forceRcfg) return;
  if (!forceRcfg && lastRcfg && millis() - lastRcfg < rcfgPeriodMs) return;
  forceRcfg = false;
  lastRcfg = millis();
  bool regs = doRemoteRegisters();
  String resp;
  int code = request("GET", "/api/v1/config", "", "", resp, HTTP_TIMEOUT_MS);
  JsonDocument doc;
  long ver = 0;
  if (code == 200 && !deserializeJson(doc, resp)) ver = doc["version"] | 0L;   // 204: nothing set
  if (ver <= cfg::getCounter("cfg_ver")) {
    if (regs) safeRestart("remote_regs");
    return;
  }
  int changed = 0;
  for (JsonPair kv : doc["settings"].as<JsonObject>()) {
    const char *key = kv.key().c_str();
    String val = kv.value().as<String>();
    if (!remoteAllowed(key)) {
      evlog("Remote setting %s refused (unknown or not allowed remotely)", key);
      continue;
    }
    if (val == "@default") {
      if (!cfg::isDefault(key)) {
        cfg::unset(key);
        evlog("Remote setting %s back to default", key);
        changed++;
      }
    } else if (val != cfg::get(key)) {
      evlog("Remote setting %s: %s -> %s", key, cfg::get(key).c_str(), val.c_str());
      cfg::set(key, val);
      changed++;
    }
  }
  cfg::setCounter("cfg_ver", ver);
  evlog("Remote settings version %ld applied: %d change(s)", ver, changed);
  if (changed || regs) safeRestart(regs ? "remote_regs" : "remote_cfg");
  rcfgReported = false;   // report the new version
}

// ---------------------------------------------------------------- task

static void task(void *) {
  esp_task_wdt_add(nullptr);
  WiFi.persistent(false);   // credentials come from our settings, not the WiFi driver's flash
  WiFi.setAutoReconnect(false);
  WiFi.mode(st.portalOn ? WIFI_AP_STA : WIFI_STA);
  WiFi.setHostname(devId.c_str());
  WiFi.setSleep(false);
  st.wifiDownSince = millis();
  for (;;) {
    esp_task_wdt_reset();
    bool up = WiFi.status() == WL_CONNECTED;
    if (up && !st.wifiUp) {
      st.wifiUp = true;
      uint32_t downS = (millis() - st.wifiDownSince) / 1000;
      st.wifiDownSince = 0;
      strncpy(st.ip, WiFi.localIP().toString().c_str(), sizeof(st.ip) - 1);
      st.rssi = WiFi.RSSI();
      evlog("WiFi connected to \"%s\" ip=%s rssi=%d ch=%d (after %lu s offline)", WiFi.SSID().c_str(), st.ip,
            (int)st.rssi, WiFi.channel(), (unsigned long)downS);
      rtclock::startNtp();
      forceUpload = true;
    } else if (!up && st.wifiUp) {
      st.wifiUp = false;
      st.wifiDownSince = millis();
      st.ip[0] = 0;
      nextWifiAttempt = millis() + 2000;
      evlog("WiFi lost (status %d)", WiFi.status());
    }
    if (!up) {
      handleOffline();
      continue;
    }
    st.rssi = WiFi.RSSI();
    rtclock::poll();
    doLive();
    doUpload();
    doRemoteConfig();
    doOta();
    wdtDelay(200);
  }
}

void begin() {
  baseUrl = cfg::get("srv_url");
  while (baseUrl.endsWith("/")) baseUrl.remove(baseUrl.length() - 1);
  https = baseUrl.startsWith("https://");
  token = cfg::get("dev_token");
  devId = cfg::get("dev_id");
  uploadPeriodMs = max(10L, cfg::getInt("upload_s")) * 1000UL;
  batchRows = constrain(cfg::getInt("batch_rows"), 1, 60);
  liveOn = cfg::getInt("live_on") == 1;
  otaOn = cfg::getInt("ota_on") == 1;
  otaPeriodMs = max(1L, cfg::getInt("ota_check_h")) * 3600000UL;
  rcfgOn = cfg::getInt("rcfg_on") == 1;
  rcfgPeriodMs = max(1L, cfg::getInt("rcfg_check_m")) * 60000UL;
  if (https) {
    if (cfg::getInt("tls_verify") == 1) tls.setCACert(CA_BUNDLE);
    else tls.setInsecure();
  }
  if (cfg::get("wifi_ssid").length() && cfg::get("wifi_ssid2").length())
    evlog("WiFi: networks \"%s\" and \"%s\": joins the one in range, stays on it until the link drops",
          cfg::get("wifi_ssid").c_str(), cfg::get("wifi_ssid2").c_str());
  evlog("Server %s (%s), upload every %lu s, live %s, OTA %s, remote settings %s", baseUrl.c_str(),
        https ? (cfg::getInt("tls_verify") == 1 ? "TLS verified" : "TLS NOT verified") : "plain HTTP",
        (unsigned long)(uploadPeriodMs / 1000), liveOn ? "on" : "off", otaOn ? "on" : "off", rcfgOn ? "on" : "off");
  xTaskCreatePinnedToCore(task, "net", 16384, nullptr, 1, nullptr, 0);
}

void uploadNow() { forceUpload = true; }
void otaCheckNow() { forceOta = true; }
void configCheckNow() { forceRcfg = true; }

String statusText() {
  String s;
  s += "WiFi: ";
  s += st.wifiUp ? String("up, ") + WiFi.SSID() + " " + st.ip + " rssi " + String((int)st.rssi) + " dBm"
                 : String("down for ") + String(st.wifiDownSince ? (millis() - st.wifiDownSince) / 1000 : 0) +
                       " s, in range at the last scan: " + wifiSeen;
  s += "\nServer: " + baseUrl + (token.length() ? "" : " (NO TOKEN)");
  s += "\nUploads: ok " + String((unsigned long)st.uploadsOk) + ", failed " + String((unsigned long)st.uploadsFail) +
       ", last ok " + (st.lastUploadOk ? isoTime(st.lastUploadOk) : String("never")) + ", last error " +
       lastUploadError;
  s += "\nBacklog: " + String((int)st.backlogMin) + " min, pointer " + store::pointerText() + ", RAM queue " +
       String(store::ramRows()) + " rows";
  s += "\nLive: ok " + String((unsigned long)st.liveOk) + ", failed " + String((unsigned long)st.liveFail);
  return s;
}

}  // namespace net
