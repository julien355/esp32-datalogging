// Serial console (USB, 115200 baud): type "help". Used at the office to configure,
// test and read the SD card without removing it.
#pragma once
#include <Arduino.h>

namespace console {
void poll();
}
