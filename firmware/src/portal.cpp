#include "portal.h"

#include <DNSServer.h>
#include <WebServer.h>
#include <WiFi.h>

#include "app.h"
#include "net.h"
#include "sampler.h"
#include "settings.h"

namespace portal {

static WebServer *server = nullptr;
static DNSServer dns;
static bool on = false;
static uint32_t lastActivity = 0;
static bool keepOpen = false;   // no WiFi configured: stay open

static String esc(const String &s) {
  String o;
  o.reserve(s.length() + 8);
  for (size_t i = 0; i < s.length(); i++) {
    char c = s[i];
    if (c == '&') o += "&amp;";
    else if (c == '<') o += "&lt;";
    else if (c == '>') o += "&gt;";
    else if (c == '"') o += "&quot;";
    else o += c;
  }
  return o;
}

static const char CSS[] PROGMEM =
    "body{font-family:sans-serif;margin:0 auto;max-width:640px;padding:8px;color:#222}"
    "h1{font-size:1.3em}h2{font-size:1.05em;margin:18px 0 4px;border-bottom:1px solid #ccc}"
    "label{display:block;margin-top:8px;font-weight:bold;font-size:.9em}"
    "input{width:100%;box-sizing:border-box;padding:7px;font-size:1em}"
    "small{color:#666;display:block}pre{background:#f3f3f3;padding:8px;white-space:pre-wrap;font-size:.85em}"
    "button{margin-top:16px;padding:12px;width:100%;font-size:1.1em;background:#1d4ed8;color:#fff;border:0}";

static void handleRoot() {
  lastActivity = millis();
  String h;
  h.reserve(12000);
  h += F("<!DOCTYPE html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
         "<title>Logger setup</title><style>");
  h += FPSTR(CSS);
  h += F("</style></head><body><h1>Logger ");
  h += esc(cfg::get("dev_id"));
  h += F(" setup</h1><pre>");
  h += "Firmware " FW_VERSION ", up " + String(millis() / 1000) + " s, boot: " + st.bootReason + "\n";
  h += "Time (UTC): " + (timeValid() ? isoTime(time(nullptr)) : String("NOT SET")) + "\n";
  h += "SD card: " + String(st.sdOk ? "ok" : "FAILED") + ", TH1 chip: " + st.th1Chip + "\n";
  h += esc(net::statusText()) + "\n";
  h += "Last sample: " + esc(sampler::lastValuesText());
  h += F("</pre><form method='POST' action='/save'>");
  h += F("<p>WiFi networks seen: ");
  int n = WiFi.scanComplete();
  if (n >= 0) {
    for (int i = 0; i < n && i < 12; i++) h += esc(WiFi.SSID(i)) + " (" + String(WiFi.RSSI(i)) + " dBm), ";
    WiFi.scanDelete();
  } else {
    h += F("scanning, reload in a few seconds");
  }
  if (n != WIFI_SCAN_RUNNING) WiFi.scanNetworks(true);
  h += F("</p>");
  const char *group = "";
  for (size_t i = 0; i < cfg::NDEFS; i++) {
    const cfg::Def &d = cfg::DEFS[i];
    if (strcmp(group, d.group) != 0) {
      group = d.group;
      h += "<h2>" + String(group) + "</h2>";
    }
    bool secret = d.flags & cfg::SECRET;
    h += "<label>" + String(d.key) + "</label><input name='" + String(d.key) + "' ";
    if (secret) {
      h += F("type='password' placeholder='");
      h += cfg::get(d.key).length() ? F("(set: leave empty to keep)") : F("(not set)");
      h += "'>";
    } else {
      h += "value='" + esc(cfg::get(d.key)) + "'>";
    }
    h += "<small>" + esc(d.help) + " (default: " + esc(secret ? String("hidden") : String(d.def)) + ")</small>";
  }
  h += F("<button type='submit'>Save and restart</button></form>"
         "<form method='POST' action='/close'><button style='background:#555'>Close the setup WiFi</button></form>"
         "</body></html>");
  server->send(200, "text/html", h);
}

static void handleSave() {
  lastActivity = millis();
  int changed = 0;
  for (size_t i = 0; i < cfg::NDEFS; i++) {
    const cfg::Def &d = cfg::DEFS[i];
    if (!server->hasArg(d.key)) continue;
    String v = server->arg(d.key);
    v.trim();
    if ((d.flags & cfg::SECRET) && v.length() == 0) continue;   // empty = keep
    if (v != cfg::get(d.key)) {
      cfg::set(d.key, v);
      changed++;
      evlog("Setting %s changed from the setup portal", d.key);
    }
  }
  server->send(200, "text/html",
               "<meta name='viewport' content='width=device-width'><h2>" + String(changed) +
                   " setting(s) saved. Restarting...</h2><p>Reconnect your phone to the normal WiFi.</p>");
  delay(1500);
  safeRestart("portal");
}

static void handleClose() {
  server->send(200, "text/html", "<h2>Setup WiFi closed.</h2>");
  delay(500);
  stop();
}

void start() {
  if (on) return;
  String ap = "ARKAN-" + cfg::get("dev_id");
  String pass = cfg::get("portal_pass");
  if (pass.length() < 8) pass = "arkan-setup";
  WiFi.mode(WIFI_AP_STA);
  WiFi.softAP(ap.c_str(), pass.c_str());
  dns.start(53, "*", WiFi.softAPIP());
  if (!server) {
    server = new WebServer(80);
    server->on("/", HTTP_GET, handleRoot);
    server->on("/save", HTTP_POST, handleSave);
    server->on("/close", HTTP_POST, handleClose);
    server->onNotFound([]() {   // captive portal: every address leads to the setup page
      server->sendHeader("Location", "http://192.168.4.1/", true);
      server->send(302, "text/plain", "");
    });
  }
  server->begin();
  WiFi.scanNetworks(true);
  on = true;
  st.portalOn = true;
  lastActivity = millis();
  keepOpen = cfg::get("wifi_ssid").length() == 0 && cfg::get("wifi_ssid2").length() == 0;
  evlog("Setup portal open: WiFi \"%s\", page http://192.168.4.1%s", ap.c_str(),
        keepOpen ? " (stays open: no WiFi set)" : "");
}

void stop() {
  if (!on) return;
  server->stop();
  dns.stop();
  WiFi.softAPdisconnect(true);
  WiFi.mode(WIFI_STA);
  on = false;
  st.portalOn = false;
  evlog("Setup portal closed");
}

void loop() {
  if (!on) return;
  dns.processNextRequest();
  server->handleClient();
  uint32_t idleMs = cfg::getInt("portal_min") * 60000UL;
  if (!keepOpen && millis() - lastActivity > idleMs) stop();
}

bool active() { return on; }

}  // namespace portal
