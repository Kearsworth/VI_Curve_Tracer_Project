# V-I Curve Tracer

Language for the tracer hardware and the capture that feeds the ML pipeline. A tracer drives a component with a sine wave and records the voltage across it and the current through it.

## Language

**DUT**:
The component under test. On the Case 1 board it sits between node A and node B.
_Avoid_: part, device, load

**Node A** (drive node):
The drive stage's output and the top of the DUT. Its voltage is the drive itself, so its measured phase is the drive phase that labels every sample.
_Avoid_: source, input

**Node B** (sense node):
The junction of the DUT and the sense resistor. The DUT voltage is V_A − V_B and the current is V_B / Rr.
_Avoid_: output, middle node, DUT node (an older plan put the DUT between this point and ground)

**Sense resistor (Rr)**:
The resistor from node B to ground that turns current into a voltage. Case 1 picks 220 Ω / 1k / 10k / 100k with a jumper; in circuit they measure 221.4 / 1022 / 10290 / 101300 Ω, and those are the values to pass as `Rr`.
_Avoid_: shunt, range resistor

**Drive stage**:
The hardware that turns the DAC's 0–3.3 V output into the signal at node A. In Case 1, OPA4134 channel A as a difference amp (gain 5.92) around a buffered 1.65 V V_REF (channel B).
_Avoid_: level shifter (only one part of it), generator

**Return path**:
The hardware that brings node A and node B into the ADC's input range. In Case 1, a unity follower per node (OPA4134 channels C/D) into a 100k / 20k / 20k divider, read on GPIO34 (node A) and GPIO35 (node B).
_Avoid_: feedback, sense path

**Drive amplitude (A)**:
The measured peak voltage at node A during a capture, in real volts. Voltage and current are divided by it to make a signature unit-free. Synth trains A = 4–6 V; the Case 1 firmware drives about 4.66 V.
_Avoid_: nominal amplitude, DAC amplitude, drive setting

**Capture**:
One recording of whole drive cycles: samples of voltage, current and drive phase, plus the settings needed to normalize them.
_Avoid_: frame (that is one serial line), trace, run

**Burst**:
The block of whole drive cycles the Case 1 firmware records into RAM and then prints: a meta line, the rows, and a closing `# burst=` line. With the burst firmware, a capture is one burst.
_Avoid_: stream (the 50 Hz sketches stream; the burst firmware doesn't)

**Signature**:
The normalized 360-point voltage–current loop calibrated from a capture, indexed by drive phase.
_Avoid_: curve, loop (as a noun for the data)

**Zero-cal**:
A capture taken with no DUT, from which `reader.py` takes each channel's offset at 0 V. Redo it when the board or firmware changes.
_Avoid_: calibration (too broad), tare

**Offset reference**:
A third divider like the return-path ones but with its input at ground, read on GPIO32 after every burst (`ref_counts=`). Its move since the zero-cal is subtracted from both channels, which cancels the ADC offset drift.
_Avoid_: V_REF (that is the 1.65 V drive-stage reference)

**Auto-range**:
Picking the drive frequency and Rr for a part so that |Z|/Rr is near 1 and its loop is readable. `hardware/autorange.py` does it with the same `synth.auto_range` rule the training data uses.
_Avoid_: range switching (the jumper move is only one step of it)

**Signature generator** (two-board setup, retired 2026-10-04):
A board that faked a plausible V-I signature (not real component physics) so the capture path could be tested before the real circuit existed: ESP32 #1 running `signature_gen`.
_Avoid_: fake DUT, simulator (ambiguous with `synth.py`, which simulates physics in Python, not hardware)

**Capture unit** (two-board setup, retired 2026-10-04):
The board that owned ADC + serial framing + streaming to the PC, whatever fed it: ESP32 #2 running `signature_capture`. On Case 1 one ESP32 does both jobs, on two cores.
_Avoid_: reader (that's the PC-side `hardware/reader.py`), receiver

**Sync pulse** (two-board setup, retired 2026-10-04):
A digital pulse from the signature generator marking the start of each drive cycle, so the capture unit could derive phase from a *measured* period. A single board doesn't need it: the same chip drives and samples on one clock.
_Avoid_: trigger, clock
