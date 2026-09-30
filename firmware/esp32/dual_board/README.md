# Two-board bring-up: synthetic signature generator + capture unit

**Status: written 2026-09-26, verified on real hardware 2026-09-29** — both boards flashed,
wired per the diagram below, and all three shapes captured end-to-end through
`hardware/reader.py` → `calibrate.py` → `features.py`. See "What's proven vs. not" below for
exactly what that does and doesn't confirm.

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

**Confirmed on real hardware, 2026-09-29** — two physical ESP32 DevKits, wired per the
diagram above, both boards' own USB port connected to the same PC. Sent each shape command
to GEN, captured from CAP via `hardware/reader.py`, ran `calibrate.py` → `features.py`, and
checked the calibrated V-I loop's correlation and aspect ratio (see
`hardware/dual_board_signature_check.py`, the script that ran this check):

| shape | expected      | V-I correlation | aspect (minor/major) | reads as |
|-------|---------------|-----------------:|----------------------:|----------|
| `R`   | line          | +0.9995           | 0.014                 | line ✓ |
| `C`   | ellipse       | −0.013 (≈0)        | 0.981 (≈1)             | ellipse ✓ |
| `D`   | knee          | +0.865             | 0.210                  | knee ✓ (between line and ellipse, as a bent curve should be) |

All three land where they should: `R`'s near-zero aspect and near-1 correlation say "flat
line"; `C`'s near-zero correlation and near-1 aspect say "round, 90°-shifted"; `D` sits
between the two, consistent with a curve that's mostly one direction but bends. For `R`
specifically, the measured `slope0` (0.59) landed within 2% of the value hand-coded in
`signature_gen.ino` (`ii = 0.6f * v`), which is real evidence the whole chain — DAC → wire →
ADC → sync-derived phase → calibration — preserves the intended relationship on actual
hardware, not just in the simulated tests.

**Still open:**
- **Sync jitter is real, not zero.** `n_segments` came back ~160–167 for all three shapes,
  where a clean curve should be closer to 2–4. Visually this shows up as small staircase
  zigzags at the edges of an otherwise correct shape (see the saved figure from
  `dual_board_signature_check.py`) — the shape is right, the fine detail isn't perfectly
  smooth yet. Most likely cause: the un-atomic volatile reads below. Not investigated further
  yet — the boxes below just say why, not "fixed."
- The volatile reads in `signature_capture.ino` (`lastSyncUs`/`prevPeriodUs`) still aren't
  interrupt-guarded (no `noInterrupts()`/atomic section) — plausible source of the jitter
  above. Fine for this demo/bring-up tool, worth revisiting before trusting phase precision
  for anything more demanding than "does the shape look right."
- **A real quirk worth knowing, not a hardware fault:** opening a fresh connection to GEN or
  CAP after they've been running a while doesn't reliably re-print the boot `#` meta line
  (`A_nominal_v=...`), so `hardware/reader.py` needs `A=`/`Rr=` passed explicitly in that
  case (its own docstring already documents this fallback). Also: opening a connection to an
  ESP32 auto-resets it via DTR, and reading too soon after that (before ~2s) can show garbled
  data mid-reboot — not a real fault, just needs a settle wait.

## Next steps

1. ~~Flash both boards, wire per the diagram, confirm each shape reads back correctly~~ —
   done 2026-09-29, see the table above.
2. Look at the jitter (`n_segments` ~160) more closely — plot a raw (non-calibrated) capture
   and see whether it's the interrupt/volatile-read issue above or something else.
3. **Plan for the real-circuit swap (updated 2026-09-30 — supersedes the earlier note below):**
   the drive is now planned as an **external voltage source / function generator**, not
   GEN's DAC — it drives the DUT directly (through the confirmed drive stage and the
   still-unconfirmed return path) while CAP only ever reads the analog response on its two
   ADC pins, same as today. GEN is retired, not merged into CAP.
   - **Sync, option A (try first):** if the generator has a **SYNC/TRIG OUT**, wire it
     straight to CAP's GPIO27 — `onSync()`'s existing measured-period logic needs zero
     changes. Check the actual output level first: most bench generators put out 5V TTL,
     which exceeds the ESP32 GPIO's 3.3V max, so it needs a simple resistor voltage divider
     (e.g. 10kΩ/20kΩ → ~3.33V) before touching GPIO27, not a direct connection.
   - **Sync, option B (if no SYNC OUT exists):** wire the drive voltage `Vs` itself through
     a voltage divider straight into GPIO27, **no firmware change needed** — the GPIO's own
     ~1.6–1.7V logic threshold acts as a crude comparator, and since the interrupt is
     already `RISING`-only, it naturally fires once per cycle (of the 2 physical
     threshold-crossings per cycle) exactly like a real sync pulse would.
   - **Known risk with option B:** a slowly-changing sine crossing that threshold can
     "chatter" (multiple spurious interrupts per real crossing) if there's noise on the
     line. Verify by counting interrupts/sec against the known drive frequency before
     trusting a capture. If chatter shows up, add a real **comparator IC** (or an op-amp
     wired as one) between `Vs` and GPIO27 instead of relying on the raw GPIO threshold.
   - *(Original note, now superseded: this used to say "nothing on the sync pin" and treat
     CAP's `havePeriod` logic as needing a rewrite for the real-DUT case — that assumed the
     drive would disappear entirely. It doesn't: something must still tell CAP the phase,
     which is exactly what options A/B above solve.)*
