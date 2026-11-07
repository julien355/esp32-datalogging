// Temperature and humidity sensors.
// TH1: the board's I2C sensor (type found automatically: AHT1x/2x, SHT3x, HTU21/SHT21/Si7021).
// TH2: AM2301 (DHT21) on a single-wire GPIO.
#pragma once
#include <Arduino.h>

namespace sensors {
void begin();
bool readTH1(float &t, float &rh);   // offsets from the settings applied
bool readTH2(float &t, float &rh);
bool th2Enabled();
}  // namespace sensors
