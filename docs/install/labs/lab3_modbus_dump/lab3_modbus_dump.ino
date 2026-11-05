// Lab 3: RS485 loopback with a laptop, then a Modbus register dump of the meter.
// NOT YET TESTED ON THE HARDWARE. The RS485 GPIOs are UNKNOWN: read them from the
// back silkscreen of the board in Lab 1 and fill them in below (TO VERIFY).
// The register map of the FCN300 is NOT VERIFIED (docs/meter/README.md).
//
// Two modes, chosen from the Serial Monitor (115200 baud):
//   "e"  ECHO: every byte received on RS485 is sent back, and printed in hex.
//        Use it with the laptop's USB-RS485 adapter and a serial terminal
//        (Lab 3 part A) to prove the TX, RX and DE pins and the A/B wiring.
//   "d"  DUMP: reads registers 0x0000 to 0x003F from slave 1 with FC03, then FC04,
//        and prints each word as hex, u16 and s16 (Lab 3 part C). It only reads:
//        it never writes to the meter.
//   "i<n>" sets the slave id (for example i1), "b<baud>" the baud rate (b9600).
//
// Library: "ModbusMaster" by Doc Walker.

#include <ModbusMaster.h>

// ---- RS485 pins: TO VERIFY from the back silkscreen ----
const int PIN_RS485_TX = -1;   // fill in, for example 17
const int PIN_RS485_RX = -1;   // fill in, for example 18
const int PIN_RS485_DE = -1;   // DE and /RE tied together; -1 if the board switches direction by itself

uint8_t slaveId = 1;           // default from the guide, to verify on the meter menu
uint32_t baud = 9600;          // default from the guide, 8-N-1
bool echoMode = false;

ModbusMaster node;

void preTx()  { if (PIN_RS485_DE >= 0) digitalWrite(PIN_RS485_DE, HIGH); }
void postTx() { if (PIN_RS485_DE >= 0) { Serial1.flush(); digitalWrite(PIN_RS485_DE, LOW); } }

void startPort() {
  Serial1.end();
  Serial1.begin(baud, SERIAL_8N1, PIN_RS485_RX, PIN_RS485_TX);
  node.begin(slaveId, Serial1);
  node.preTransmission(preTx);
  node.postTransmission(postTx);
  Serial.printf("RS485 on TX=%d RX=%d DE=%d, %lu baud 8-N-1, slave %u\n",
                PIN_RS485_TX, PIN_RS485_RX, PIN_RS485_DE, (unsigned long)baud, slaveId);
}

void dumpBlock(uint8_t fc, uint16_t start, uint16_t count) {
  uint8_t r = (fc == 3) ? node.readHoldingRegisters(start, count)
                        : node.readInputRegisters(start, count);
  if (r != node.ku8MBSuccess) {
    Serial.printf("  FC%02u 0x%04X..0x%04X: error 0x%02X (%s)\n", fc, start, start + count - 1, r,
                  r == node.ku8MBResponseTimedOut ? "timeout: wiring, A/B swap, id, baud" :
                  r == node.ku8MBIllegalDataAddress ? "illegal address: not mapped" :
                  r == node.ku8MBIllegalFunction ? "illegal function: try the other FC" : "see ModbusMaster codes");
    return;
  }
  for (uint16_t i = 0; i < count; i++) {
    uint16_t w = node.getResponseBuffer(i);
    Serial.printf("  FC%02u 0x%04X (%5u)  0x%04X  u16=%5u  s16=%6d\n",
                  fc, start + i, start + i, w, w, (int16_t)w);
  }
}

void dump() {
  for (uint8_t fc = 3; fc <= 4; fc++) {
    Serial.printf("\n--- FC%02u, registers 0x0000 to 0x003F ---\n", fc);
    // Read in blocks of 16 so one unmapped block does not hide the others.
    for (uint16_t s = 0; s < 0x40; s += 16) {
      dumpBlock(fc, s, 16);
      delay(100);
    }
  }
  Serial.println("\nDone. Copy this output into the record sheet; pair the words as u32 with modbus_dump.py.");
}

void setup() {
  Serial.begin(115200);
  delay(1500);
  Serial.println("\n=== Lab 3 RS485 / Modbus (not yet tested on the hardware) ===");
  if (PIN_RS485_TX < 0 || PIN_RS485_RX < 0) {
    Serial.println("Fill in PIN_RS485_TX and PIN_RS485_RX first (Lab 1, back silkscreen).");
  }
  if (PIN_RS485_DE >= 0) { pinMode(PIN_RS485_DE, OUTPUT); digitalWrite(PIN_RS485_DE, LOW); }
  startPort();
  Serial.println("Commands: e=echo mode  d=dump  i<n>=slave id  b<baud>=baud rate");
}

void loop() {
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line.length()) {
      switch (line[0]) {
        case 'e': echoMode = !echoMode; Serial.printf("Echo mode %s\n", echoMode ? "ON" : "OFF"); break;
        case 'd': echoMode = false; dump(); break;
        case 'i': slaveId = line.substring(1).toInt(); startPort(); break;
        case 'b': baud = line.substring(1).toInt(); startPort(); break;
        default: Serial.println("?");
      }
    }
  }
  if (echoMode && Serial1.available()) {
    uint8_t buf[64];
    size_t n = 0;
    unsigned long t0 = millis();
    while (millis() - t0 < 20 && n < sizeof(buf)) {   // gather a short burst
      if (Serial1.available()) { buf[n++] = Serial1.read(); t0 = millis(); }
    }
    Serial.print("RX:");
    for (size_t i = 0; i < n; i++) Serial.printf(" %02X", buf[i]);
    Serial.println();
    preTx();
    Serial1.write(buf, n);
    postTx();
  }
}
