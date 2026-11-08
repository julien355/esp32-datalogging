# Modbus meter simulator

A stand-in for the FORT FCN300 power meter, for practising and for testing the logger before the site visit.
Not a copy of the real meter: its register layouts are inventions (the real map is not verified yet, `docs/meter/README.md`).

```
python tools/modbus_sim/modbus_sim.py profiles                         # the fake meters
python tools/modbus_sim/modbus_sim.py check --regs my_registers.csv --ct-mult 50   # replay the logger's read, no hardware
python tools/modbus_sim/modbus_sim.py dump --profile float32-fc4 --fc 4            # what a register dump looks like
python tools/modbus_sim/modbus_sim.py serve --port COM7 -v                         # answer the logger on RS485 (pip install pyserial)
```

Read only: it never accepts a write. Python 3.8+; only `serve` needs `pyserial`.

Layouts: `proposed` (the proposed table, secondary values), `primary-16bit` (the meter applies its CT setting),
`float32-fc4` (floats, low word first, input registers). Your own: `--meter-table FILE`, same format as `registers.csv`
(`ct = 1` = this meter sends secondary values).

Tests: `python -m unittest discover -s tools/modbus_sim -v` (also run by CI). Some tests read `firmware/src/meter.cpp`
and fail when the firmware's register grouping or built-in table moves away from what this simulator copies.

Full guide with three exercises: [`docs/tutorials/4-MODBUS-REGISTERS.md`](../../docs/tutorials/4-MODBUS-REGISTERS.md).
