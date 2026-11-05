// Lab 4 and Lab 5: WiFi signal survey with the logger board itself.
// NOT YET TESTED ON THE HARDWARE.
//
// Power the board from a USB power bank, hold it where the logger box will go
// (antenna clear of the steel panel), and read the Serial Monitor on a laptop
// (115200 baud). Every 3 s it scans and prints the RSSI of the networks whose
// name contains SSID_FILTER, with a running mean over the last 10 scans.
// It does not connect: no password is needed.

#include <WiFi.h>

const char *SSID_FILTER = "";   // part of the staff network name; "" lists all

float hist[10];
int nHist = 0, iHist = 0;

void setup() {
  Serial.begin(115200);
  delay(1500);
  Serial.println("\n=== Lab 4/5 RSSI survey (not yet tested on the hardware) ===");
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
}

void loop() {
  int n = WiFi.scanNetworks(false, true);
  int best = -127;
  Serial.printf("\nscan at %lu s: %d networks\n", millis() / 1000, n);
  for (int i = 0; i < n; i++) {
    String ssid = WiFi.SSID(i);
    if (strlen(SSID_FILTER) && ssid.indexOf(SSID_FILTER) < 0) continue;
    Serial.printf("  %-32s ch %2d  %4d dBm  %s\n", ssid.c_str(), WiFi.channel(i), WiFi.RSSI(i),
                  WiFi.encryptionType(i) == WIFI_AUTH_OPEN ? "OPEN" : "secured");
    if (WiFi.RSSI(i) > best) best = WiFi.RSSI(i);
  }
  if (best > -127) {
    hist[iHist] = best; iHist = (iHist + 1) % 10; if (nHist < 10) nHist++;
    float sum = 0; for (int i = 0; i < nHist; i++) sum += hist[i];
    float mean = sum / nHist;
    Serial.printf("  best %d dBm, mean of last %d scans %.1f dBm: %s\n", best, nHist, mean,
                  mean > -70 ? "OK (better than -70)" : "TOO WEAK for the box position");
  }
  WiFi.scanDelete();
  delay(3000);
}
