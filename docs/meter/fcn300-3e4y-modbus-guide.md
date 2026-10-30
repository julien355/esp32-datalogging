# FORT Digital Multifunction Power Meter (FCN300-3E4Y)
## Modbus RTU Register Map & Documentation

---

## 1. Device Overview & Specifications
* **Model:** FORT FCN300-3E4Y
* **Type:** 3-Phase 4-Wire AC Digital Multifunction Meter (LCD Display)
* **Measurement Functions:** $V$, $A$, $Hz$, $kW$, $kWh$, $kVAR$, $kVA$, $\cos\phi$ (Power Factor), $kVARh$, $kVAh$
* **Voltage Input Range:** 0 – 450 VAC
* **Current Input Range:** 0 – 9999 A / 5A / 1A (via CT)
* **Frequency Range:** 45 – 65 Hz
* **Operating Auxiliary Power:** 200 – 240 VAC
* **Dimensions:** $96 \times 96\text{ mm}$ panel mount

---

## 2. Serial Communication Parameters
* **Protocol:** Modbus RTU over RS485
* **Default Slave ID / Address:** `1` (Configurable: 1 – 247)
* **Default Baud Rate:** `9600 bps` (Options: 2400, 4800, 9600, 19200)
* **Data Format:** 8 Data Bits, No Parity, 1 Stop Bit (`8-N-1`)
* **Supported Function Codes:**
  * `0x03` – Read Holding Registers
  * `0x04` – Read Input Registers
  * `0x06` / `0x10` – Write Single / Multiple Registers

---

## 3. Modbus Register Map

> **Note on Addressing:** Register addresses are listed as 0-based Hex / Decimal offsets (used by most Modbus master libraries) and 1-based PLC reference addresses.

### 3.1. Real-Time Measurement Registers (Read-Only)

| Parameter | Unit | Hex Address | Dec Offset | PLC Address | Data Type | Multiplier / Scale |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Phase Voltage $V_1$ (L1-N)** | V | `0x0000` | 0 | 40001 / 30001 | 16-bit / 32-bit INT | $\times 0.1$ |
| **Phase Voltage $V_2$ (L2-N)** | V | `0x0001` | 1 | 40002 / 30002 | 16-bit / 32-bit INT | $\times 0.1$ |
| **Phase Voltage $V_3$ (L3-N)** | V | `0x0002` | 2 | 40003 / 30003 | 16-bit / 32-bit INT | $\times 0.1$ |
| **Line Voltage $V_{12}$** | V | `0x0003` | 3 | 40004 / 30004 | 16-bit INT | $\times 0.1$ |
| **Line Voltage $V_{23}$** | V | `0x0004` | 4 | 40005 / 30005 | 16-bit INT | $\times 0.1$ |
| **Line Voltage $V_{31}$** | V | `0x0005` | 5 | 40006 / 30006 | 16-bit INT | $\times 0.1$ |
| **Phase Current $I_1$** | A | `0x0006` | 6 | 40007 / 30007 | 16-bit / 32-bit INT | $\times 0.001$ or $\times 0.01$ |
| **Phase Current $I_2$** | A | `0x0007` | 7 | 40008 / 30008 | 16-bit / 32-bit INT | $\times 0.001$ |
| **Phase Current $I_3$** | A | `0x0008` | 8 | 40009 / 30009 | 16-bit / 32-bit INT | $\times 0.001$ |
| **Grid Frequency ($f$)** | Hz | `0x0009` | 9 | 40010 / 30010 | 16-bit INT | $\times 0.01$ (5000 = 50.00 Hz) |
| **Active Power Phase L1 ($P_1$)** | W / kW | `0x000A` | 10 | 40011 / 30011 | 16-bit / 32-bit | Direct / Scaling |
| **Active Power Phase L2 ($P_2$)** | W / kW | `0x000B` | 11 | 40012 / 30012 | 16-bit / 32-bit | Direct / Scaling |
| **Active Power Phase L3 ($P_3$)** | W / kW | `0x000C` | 12 | 40013 / 30013 | 16-bit / 32-bit | Direct / Scaling |
| **Total Active Power ($P_{total}$)** | kW | `0x000D` | 13 | 40014 / 30014 | 16-bit / 32-bit | Direct / Scaling |
| **Total Reactive Power ($Q_{total}$)**| kVAR | `0x000E` | 14 | 40015 / 30015 | 16-bit / 32-bit | Direct / Scaling |
| **Total Apparent Power ($S_{total}$)**| kVA | `0x000F` | 15 | 40016 / 30016 | 16-bit / 32-bit | Direct / Scaling |
| **Power Factor ($\cos\phi$)** | - | `0x0010` | 16 | 40017 / 30017 | 16-bit INT | $\times 0.001$ (985 = 0.985) |

---

### 3.2. Energy Accumulation Registers

| Parameter | Unit | Hex Address | Dec Offset | PLC Address | Data Type | Formula / Scaling |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Import Active Energy (kWh High)** | kWh | `0x0018` | 24 | 40025 | 16-bit INT | High Word |
| **Import Active Energy (kWh Low)** | kWh | `0x0019` | 25 | 40026 | 16-bit INT | Low Word: $\text{kWh} = \frac{(\text{High} \times 65536) + \text{Low}}{100}$ |
| **Import Reactive Energy (kVARh)** | kVARh | `0x001A` | 26 | 40027 | 32-bit INT | High/Low combined |

---

### 3.3. Configuration Registers (Read / Write)

| Parameter | Hex Address | Dec Offset | PLC Address | Description / Range |
| :--- | :--- | :--- | :--- | :--- |
| **CT Primary Ratio ($CT_1$)** | `0x0030` | 48 | 40049 | e.g., 100 for a 100/5A CT |
| **CT Secondary Ratio ($CT_2$)**| `0x0031` | 49 | 40050 | Options: 5 (5A) or 1 (1A) |
| **PT Primary Ratio ($PT_1$)** | `0x0032` | 50 | 40051 | Default: 1 |
| **PT Secondary Ratio ($PT_2$)**| `0x0033` | 51 | 40052 | Default: 1 |
| **Modbus Address** | `0x0034` | 52 | 40053 | Range: 1 – 247 |
| **Baud Rate Selection** | `0x0035` | 53 | 40054 | `0`: 2400 \| `1`: 4800 \| `2`: 9600 \| `3`: 19200 |

---

## 4. Formula Adjustments
If raw secondary values are returned directly by the unit, apply CT and PT ratios to convert to primary values:

$$\text{Real Voltage} = \text{Raw Voltage} \times \left( \frac{PT_1}{PT_2} \right)$$

$$\text{Real Current} = \text{Raw Current} \times \left( \frac{CT_1}{CT_2} \right)$$

---

## 5. Web Links & Reference Documentation

* **Product Specs & Manufacturer Page:** [FORT Indo Official Product Catalog (FCN300-3E4Y)](https://fortindo.id/product/power-multimeter-fcn300-3e4y-3-phase-ac-lcd-digital-meter/)
* **Alternative Model Details (Harmonic Variant):** [FORT Indo Official Product Catalog (FCN300-3EH4Y)](https://fortindo.id/product/power-multimeter-fcn300-3eh4y-3-phase-ac-lcd-digital-meter-fort/)
* **Manuals & Technical Datasheets:** [Scribd - FORT FCN300 Series Technical Manual & Programming Guide](https://www.scribd.com/document/973888794/Power-Meter-Fort-FCN300-E13ZY-D)
* **Distributor Specification Page:** [GMP Electric Product Page for FORT FCN300 Series](https://www.gmp-electric.com/products/digital-multimeter-fort-fcn300-3eh4y-200-240vac)