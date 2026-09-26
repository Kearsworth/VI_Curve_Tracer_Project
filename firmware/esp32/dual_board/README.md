# Two-board bring-up: synthetic signature generator + capture unit

**Status: written 2026-09-26, compiles for the ESP32 DevKit, NOT yet run on real hardware.**

## Why this exists

Dr. Wathis's real circuit (drive stage + DUT + return path) isn't ready yet, and the return
path specifically is still unconfirmed (see `../README.md`). Rather than wait, this splits
the single-board loopback (`../loopback/sine_capture`) across **two** ESP32 boards:

- **ESP32 #1** (`signature_gen/`) is a **stand-in for the future real circuit + DUT**. It
  fakes a V-I signature (line / ellipse / diode knee) instead of a real component response.
  When Dr. Wathis's circuit is ready, **only this board gets unplugged and replaced** — the
  real circuit's V and I outputs (after the return path brings them into 0–3.3V) take over
  the same two wires.
- **ESP32 #2** (`signature_capture/`) is the **permanent capture unit** — the one that reads
  ADC + frames serial + streams to the PC, unchanged whether it's reading a fake signature
  today or the real circuit later. Its whole job is proven now, on real hardware bytes, not
  just on `tests/test_reader.py`'s simulated frames.

This is a software/plumbing test, not a physics one: the shapes traced by `signature_gen`
are not real component equations (that's `vi_ml/synth.py`, in Python, used to train the
models) — they only need to be recognizably a line/ellipse/knee so the hardware path can be
exercised end to end.

## Wiring

```
ESP32 #1 (signature_gen)        ESP32 #2 (signature_capture)
  GPIO25 (DAC1, "V")   ────wire────▶  GPIO34 (ADC, V)
  GPIO26 (DAC2, "I")   ────wire────▶  GPIO35 (ADC, I)   <- a REAL second channel, unlike the
                                                            single-board loopback where both
                                                            ADC pins alias the same node
  GPIO27 (sync pulse)  ────wire────▶  GPIO27 (sync in)
  GND                  ────wire────▶  GND                <- required: analog readings are
                                                            meaningless without a shared
                                                            ground reference between boards
  USB ──▶ PC (shape-select commands)   USB ──▶ PC (data stream, same 921600 baud as sine_capture)
```

Each board needs its **own** USB connection to the PC — #1 to receive shape commands, #2 to
stream capture data. (This wasn't drawn in the original whiteboard sketch, which only showed
the analog wire between the two boards; confirmed as the simplest way to send #1 commands
without a second signal wire.)

## Why a sync pulse (the phase problem)

On the single-board loopback, phase is free: the same chip drives and samples, so
`phase_rad` comes from its own clock (CLAUDE.md design decision #2 — phase from a known
reference, never estimated from the loop's geometry, because geometric angle is ambiguous
for a diode or a straight line).

Split across two boards, that's no longer automatic — ESP32 #2 has no way to know where in
the cycle ESP32 #1 currently is, just from watching a voltage. The sync pulse fixes this:
`signature_gen` pulses GPIO27 once per cycle (at the wrap back to phase 0); `signature_capture`
times the **interval between consecutive pulses** (not an assumed frequency) and uses that
measured period to convert elapsed time since the last pulse into `phase_rad`. This keeps the
"phase from a known reference" rule intact at the cost of one extra wire.

## Shape select

With `signature_gen` flashed and connected to the PC on its own port, send a single
character over serial (`R`, `C`/`L`, or `D`) to switch the shape live — no reflash needed.
Defaults to `R` (a straight line) at boot.

## Frame format — no ML-side changes needed

`signature_capture` emits the **same CSV shape** as `../loopback/sine_capture`
(`index,t_us,phase_rad,adc_v_counts,adc_i_counts`), confirmed by feeding a simulated capture
through `hardware/reader.py` → `calibrate.py` → `features.py` unchanged (see
`docs/ROADMAP.md`). Before the first sync pulse arrives (or if one is overdue),
`phase_rad` is sent as `-1` — `reader.py`'s existing row validation (`0 <= phase <= 2*pi`)
already rejects that as malformed and skips it, so "not synced yet" rows disappear on their
own rather than showing up as a misleading `phase=0`.

`A_nominal_v` / `Rr_ohm_placeholder` in the meta line are placeholders, same convention as
the single-board loopback — there's no real drive amplitude or sense resistor in a synthetic
signature test.

## What's proven vs. not (be honest about this)

- Both sketches **compile** for the ESP32 DevKit. **Neither has been run on real hardware
  yet** — the sync-timing behavior (interrupt jitter, whether the measured period is stable
  enough) is unverified until it's flashed to two real boards and wired up.
- `hardware/reader.py` was checked against a **simulated** two-board capture (matching this
  exact frame format, including unsynced `-1`-phase rows) and needs no changes — but that's
  simulated bytes, not a real capture yet.
- The volatile reads in `signature_capture.ino` (`lastSyncUs`/`prevPeriodUs`) aren't
  interrupt-guarded (no `noInterrupts()`/atomic section) — acceptable for this demo/bring-up
  tool, not something to carry into a production capture path without revisiting.

## Next steps

1. Flash `signature_gen` to board #1, `signature_capture` to board #2, wire per the diagram
   above (**don't forget GND**).
2. `python3 hardware/reader.py --port <capture board's port> --verify` (drop `--loopback` —
   the channels are real now, not aliased) to confirm a live capture reaches `verify()`.
3. Compare captured signatures for each shape (`R`/`C`/`D`) against what you'd expect —
   this is a plumbing check, not a physics one, so "looks like a line/ellipse/knee" is the
   bar, not exact values.
