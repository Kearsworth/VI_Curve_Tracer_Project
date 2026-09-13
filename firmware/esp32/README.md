# ESP32 firmware (plan / spec) — not implemented yet

Goal: the ESP32 becomes the whole front-end — it *generates* the drive signal and *reads*
the response, then streams samples to the PC. See `../../docs/DATA_CONTRACT.md` §7.

## Responsibilities
1. **Drive (DAC):** output a sine wave (start ~1 kHz) as the source signal.
2. **Capture (ADC):** read two channels at a fixed, known sample rate:
   - CH_V  = voltage across the DUT
   - CH_I  = voltage across the sense resistor (∝ current)
3. **Stream (USB serial):** send samples to the PC (CSV line per sample, or a binary block).
4. **Phase reference:** because the ESP32 generates the drive itself, it knows the phase of
   every sample exactly — include a sample index or timestamp so the PC can compute phase.

## Current milestone: LOOPBACK
Wire DAC output directly to an ADC input (bypass the circuit + DUT). Send a known waveform,
read it back, and confirm the round-trip matches. This validates the send/receive path and
the counts→volts conversion before the real circuit is available.

## Things to decide when implementing
- Sample rate and samples-per-cycle (aim for enough that every 1° bin gets real data).
- ADC input range vs the ±signal: add **biasing** (offset) so the signal sits inside the
  ADC's allowed range; the PC removes the offset during counts→volts conversion.
- Serial baud / framing; whether to average on-device or send raw.

## Suggested language
Arduino C++ (or MicroPython). Keep the decoded output on the PC identical to the raw dict
in DATA_CONTRACT.md §1 so the ML pipeline never changes.
