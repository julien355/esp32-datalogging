# Fort FCN300 (3E4Y and 3EH4Y): what we know and what must be checked

Meter at Adab: **FORT FCN300**, 3-phase 4-wire multifunction meter, Modbus RTU over RS485. The label will say **FCN300-3E4Y** or **FCN300-3EH4Y** (the harmonic variant).

**Decision (owner, 31 October 2026): the same register map is used for both variants.** The firmware reads the registers of the guide (`fcn300-3e4y-modbus-guide.md`) whichever variant is installed. The 3EH4Y's harmonic values, if it has extra registers for them, are not read for now. The register check below still applies to whichever meter is there.

(`arkan-cmms` calls it "Fort FC300".)

Source: `fcn300-3e4y-modbus-guide.md`, received from the owner on 30 October 2026, kept as received.

## Status: **not verified**

The guide is the starting point for the firmware's register table. It is not a manufacturer document, and several lines in it do not hold together:

| # | Issue in the guide | Why it matters | How we settle it |
|---|---|---|---|
| 1 | No official manual found. The Scribd link is for a **different model** (FCN300-E13ZY-D). The fortindo.id and distributor pages could not be read from the cloud session (network allow-list) | The register map may be for a sibling model | Get the manual from the supplier, or read the registers on the bench (below) |
| 2 | Data types say "16-bit / 32-bit INT" for the same register, and addresses run one by one (0x0000, 0x0001, ...) | A 32-bit value takes two registers, so consecutive addresses mean 16-bit, or the map is wrong | Register dump: compare the raw words with the LCD |
| 3 | Current scale "x0.001 or x0.01"; power "Direct / Scaling" with no factor | Wrong scale = readings off by 10x or 1000x | Compare with the LCD at a known load |
| 4 | kVARh "32-bit" at a single address (0x001A) | A 32-bit value cannot fit in one register | Dump 0x0018 to 0x001F, watch which words count up |
| 5 | Section 4: values may be **secondary** (before the CT ratio) | Currents and powers could be 1/20 or 1/100 of the real value | Read CT1/CT2 (0x0030, 0x0031) and compare with the LCD |
| 6 | Both FC03 and FC04 listed for the same addresses | Only one may answer | Try both in the dump |
| 7 | RS485 port: resellers list Modbus RS485 for both 3E4Y and 3EH4Y | No port, no data | **Check for A/B (485) terminals on the back of the meter. Photo needed** |

## Defaults to start with (from the guide)

- Slave ID 1, 9600 baud, 8-N-1
- Readings: 0x0000 to 0x0010 (V, V L-L, I, Hz, P per phase, P/Q/S total, PF)
- Energy: 0x0018 (high word) + 0x0019 (low word), kWh = (high x 65536 + low) / 100
- CT ratio: 0x0030 / 0x0031

Everything above sits in a **register table in the logger's config**: address, function code, type (u16, s16, u32, s32, float), word order, scale. A correction found on the bench is a config change, not a firmware change.

## How to verify (session S4 or the first site visit)

1. Laptop + USB-RS485 adapter + a small Python script (`tools/modbus_dump.py`, written in S2):
   - read 0x0000 to 0x003F with FC03, then with FC04;
   - print each word as u16, s16, and pairs as u32/s32/float in both word orders.
2. Photograph the LCD pages at the same moment (V, A, kW, PF, Hz, kWh).
3. Match each LCD value to a register and a scale; write the result in `fcn300-3e4y-verified.md`.
4. **A spare meter is at the office** (owner, 7 November 2026): the check is done on the bench before the install (`docs/OFFICE-PREP.md` T4). **Check the ranges too:** with the guide's scales, a 16-bit current x 0.001 cannot exceed 65.5 A and a 16-bit power x 0.001 cannot exceed 32.8 kW, below what an 82.5 kVA hotel draws (up to 125 A per phase). If the meter really uses 16 bits, its values are secondary (before the CT ratio) or scaled differently; settle it with a load on the spare meter and the CT ratio in its menu.
