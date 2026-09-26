# V-I Curve Tracer

Language for the tracer hardware and the capture that feeds the ML pipeline. A tracer drives a component with a sine wave and records the voltage across it and the current through it.

## Language

**DUT**:
The component under test, connected between the DUT node and ground.
_Avoid_: part, device, load

**Sense resistor (Rr)**:
The series resistor between the drive node and the DUT node. Current is read as the voltage across it divided by Rr.
_Avoid_: shunt, range resistor

**Drive node**:
The point where the drive stage connects to the top of the sense resistor. Its voltage is what the tracer applies to the sense resistor and DUT in series.
_Avoid_: source, input

**DUT node**:
The junction of the sense resistor and the DUT. Its voltage, against ground, is the voltage across the DUT.
_Avoid_: output, middle node

**Drive stage**:
The hardware that turns the DAC's output into the signal at the drive node.
_Avoid_: level shifter (only one part of it), generator

**Return path**:
The hardware that brings the drive-node and DUT-node voltages into the ADC's input range.
_Avoid_: feedback, sense path

**Drive amplitude (A)**:
The measured peak voltage at the drive node during a capture, in real volts. Voltage and current are divided by it to make a signature unit-free.
_Avoid_: nominal amplitude, DAC amplitude, drive setting

**Capture**:
One recording of whole drive cycles: samples of voltage, current and drive phase, plus the settings needed to normalize them.
_Avoid_: frame (that is one serial line), trace, run

**Signature**:
The normalized 360-point voltage–current loop calibrated from a capture, indexed by drive phase.
_Avoid_: curve, loop (as a noun for the data)

**Signature generator**:
A board that fakes a plausible V-I signature (not real component physics) so the capture path can be tested before the real circuit exists. Today this is ESP32 #1 running `signature_gen`; it gets replaced by the drive stage + DUT + return path once those are confirmed, without the capture unit changing.
_Avoid_: fake DUT, simulator (ambiguous with `synth.py`, which simulates physics in Python, not hardware)

**Capture unit**:
The board that owns ADC + serial framing + streaming to the PC, regardless of what's feeding it (a signature generator today, the real circuit later). Today this is ESP32 #2 running `signature_capture`.
_Avoid_: reader (that's the PC-side `hardware/reader.py`), receiver

**Sync pulse**:
A digital pulse from the signature generator marking the start of each drive cycle, so the capture unit can derive phase from a *measured* period when it isn't the one generating the drive. Exists only in the two-board setup — the single-board loopback doesn't need it, since the same chip drives and samples.
_Avoid_: trigger, clock
