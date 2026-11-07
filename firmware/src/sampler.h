// Sampling task: every sample_s seconds (aligned on the clock: :00, :15, :30, :45) reads the
// meters and sensors, keeps a live snapshot, and at each new minute writes the 1-minute record
// (means, max of kW, last energy counter) to the SD card.
#pragma once
#include <Arduino.h>

namespace sampler {
void begin();                       // starts the task on core 1
String header();                    // CSV header of the current configuration
// Latest live snapshot (JSON) and its sequence number; seq changes when a new one is ready.
uint32_t snapshot(String &json);
String lastValuesText();            // for the console and the setup page
}  // namespace sampler
