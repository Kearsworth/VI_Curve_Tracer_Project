# ROADMAP.md — Next steps (concrete tasks)

Ordered roughly by priority. Check items off as they land.

## Phase A — Hardware/software integration (current focus)
- [x] ESP32 firmware: generate sine on DAC, read 2 channels on ADC at a fixed, known
      sample rate, stream over USB serial. See `firmware/esp32/README.md`.
      — Stage 3 (`firmware/esp32/loopback/sine_capture`) written and **verified on real
      hardware 2026-09-15**: live capture shows a clean sine in `adc_v_counts`/`adc_i_counts`.
      Caveat: "2 channels" is still code-level only — `adc_i_counts` reads the same physical
      pin as V (no real sense resistor exists yet), so this isn't a true 2-channel capture
      until the real circuit exists. Sample rate is free-running (not a literal fixed-interval
      timer) by design — see `firmware/esp32/README.md` Stage 3 note for why that's still
      "fixed, known" enough.
- [x] Loopback mode: DAC wired to ADC directly (no circuit) to validate the data path
      end-to-end (send waveform, read it back, confirm it matches).
      — Stage 2 (ramp) verified wiring/peripherals. Stage 3 (sine) now verified the same way
      with a real sine drive, timed sampling, and phase-labeled framing — live capture matches
      expected sine shape (peak/trough land near phase ≈ π/2 and 3π/2 as expected).
- [x] `hardware/reader.py`: read serial → counts→volts → build raw dict → hand to
      `calibrate.calibrate()`. Written 2026-09-21, **run against live hardware repeatedly
      since 2026-09-29** (every two-board capture below goes through it). Counts→volts is
      per-channel `ChannelCal`; the default is the ideal formula, which is known to be off on
      this ESP32 (Stage 2), so `--loopback` re-centres each channel on its own sine midpoint.
      That is loopback-only — the real circuit needs a proper offset/gain sweep plus the
      ±10V→0–3.3V return-path gain (still unconfirmed).
- [x] Verify a full real capture flows through calibrate→features→verify without changes
      to the ML code. **Done 2026-09-29/30** via the two-board setup below — real captures,
      zero ML-code changes, verdicts came back correctly for all three test shapes.
- [x] **Two-board bring-up** (`firmware/esp32/dual_board/`, written 2026-09-26,
      **verified on real hardware 2026-09-29**): ESP32 #1 (`signature_gen`) fakes a V-I
      signature (line/ellipse/knee, shape selectable live over its own serial port) as a
      stand-in for the real circuit + DUT; ESP32 #2 (`signature_capture`) reads it on two REAL
      non-aliased ADC channels, using a sync-pulse wire to derive phase from a *measured*
      period rather than an assumed frequency — see `dual_board/README.md` for the wiring and
      the phase-sync reasoning. Two physical boards flashed, wired, and run end-to-end through
      `hardware/reader.py` → `calibrate.py` → `features.py`: all three shapes came back
      geometrically correct (`R` correlation +0.9995/aspect 0.014, `C` correlation −0.013/
      aspect 0.981, `D` correlation +0.865/aspect 0.210 — see `dual_board/README.md`'s table).
      `R`'s measured slope (0.59) matched the firmware's hand-coded 0.6 within 2%.
      **Caveat:** sync-derived phase has visible jitter (`n_segments` ~160 vs. an expected
      ~2–4) — shapes are right, fine detail isn't perfectly smooth; likely the un-atomic
      volatile reads already flagged in the README, not yet fixed.
      `hardware/dual_board_signature_check.py` captures all three shapes and plots the
      calibrated V-I loop side by side — rerun this after any firmware change to the pair.
      `hardware/live_pipeline_demo.py` is the live version (both boards read continuously,
      shape switchable with r/c/d keys, shows raw→calibrated→verdict updating in real time) —
      used for the 2026-09-30 professor demo.
- [ ] **Real-circuit sync plan (updated 2026-09-30, not yet tested):** the drive is now
      planned as an external voltage source / function generator, not GEN's DAC — see
      `dual_board/README.md` Next steps item 3 for the two sync options worked out (generator's
      SYNC/TRIG OUT with a voltage divider, or Vs itself through a divider into GPIO27 reusing
      the existing interrupt unchanged) and the comparator-IC fallback if chatter shows up.
      Blocked on having the real generator + circuit in hand to test either option.

- [ ] **ADC decision experiment (this week):** flash `firmware/esp32/loopback/adc_step`, run
      `python3 hardware/adc_check.py --port <port>` with a multimeter on GPIO34. Budget ≈ 2
      counts (10 mV at the ±10 V return-path scale). PASS → internal ADC; BORDERLINE → also
      order the external ADC; FAIL → external ADC (AD7606-class: simultaneous, ±10 V input).
      Write ADR-0001 once chosen. Budget ceiling was $30 (external module may need ~$40);
      2–3 weeks lead time.
- [ ] Drive at ~1 kHz for real C/L captures (synthetic data is tuned to 1 kHz: 100 nF and
      100 mH look open/short at 50 Hz). 50 Hz is for bring-up and R/D/LED only. Needs fast
      capture: DMA on the internal ADC, or the external ADC.
- [ ] Measured `A` + amplitude leveling: a return-path/drive-node channel gives `A`; the PC
      sends an amplitude command over serial (small firmware addition) and re-captures until
      measured `A` = 5 V ± 1–2%. Then `reader.capture_to_raw` uses the measured value.
- [ ] Current = (V_drive − V_dut) / Rr from two matched channels, subtracted in software;
      calibrate the relative gain once with the DUT removed (open circuit) and once with a
      precision resistor. Fall back to a difference amp across Rr only if the numbers demand it.

## Phase B — Real data & validation
- [ ] Once the advisor's circuit is ready, capture real signatures for R/C/L/D/LED/Z,
      good and (deliberately created) faulty.
- [ ] Re-run evaluation on real held-out data; compare to the synthetic numbers.
- [ ] Fine-tune / retrain on a mix of synthetic + real; keep the synthetic pipeline as
      a bootstrap.

## Phase C — Model quality (soft faults)
- [ ] Quick experiment first: benchmark ANN and SVM against the current RF on the
      *existing* 12 features, focused on the 3 known-weak soft faults. Motivated by
      docs/LITERATURE.md §3 — a closely related published study found ANN/SVM beating RF
      specifically on soft faults. Cheaper to try than new features; do this before or
      alongside the item below.
- [ ] Add features targeting soft faults: reverse-leakage slope, ESR tilt / loss tangent,
      diode knee sharpness.
- [ ] Add a confidence "review band" (e.g. predict_proba in 0.4–0.6 ⇒ flag for human
      review) to catch the low-confidence misses.
- [ ] Consider a reference-comparison (RMS-distance) path to catch parametric value drift
      that the shape-only classifier can't.
- [ ] (Later) Electrolytic / polarized capacitors: a ±5 V AC drive reverse-biases them, so
      hardware tests use film and ceramic caps only for now. Supporting electrolytics needs a
      DC bias on the drive — a drive-stage change.
- [ ] Zener is deferred: keep it in `synth.py`/`train.py`, leave it out of hardware validation,
      and report accuracy on R, C, L, D, LED.
- [ ] (Later) Multi-frequency capture (e.g. 100 Hz / 1 k / 10 k) stacked, to separate soft
      C/L faults.

## Phase D — Product
- [ ] UI (not designed yet — plan first: likely a simple desktop or web app that shows the
      live signature + verdict). Reuse `verify.verify(raw)` as the backend call.
- [ ] Package as a single device flow (ESP32 does drive + capture; PC or phone shows result).

## Phase E — Optional / research
- [ ] 1D-CNN or Siamese network on the raw 360-point signature (this is where PyTorch
      finally enters). Compare against the Random Forest baseline.
