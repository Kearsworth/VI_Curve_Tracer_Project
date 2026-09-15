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
- [ ] `hardware/reader.py`: read serial → counts→volts → build raw dict → hand to
      `calibrate.calibrate()`. (Start from `hardware/reader_stub.py`.)
- [ ] Verify a full real capture flows through calibrate→features→verify without changes
      to the ML code.

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
- [ ] (Later) Multi-frequency capture (e.g. 100 Hz / 1 k / 10 k) stacked, to separate soft
      C/L faults.

## Phase D — Product
- [ ] UI (not designed yet — plan first: likely a simple desktop or web app that shows the
      live signature + verdict). Reuse `verify.verify(raw)` as the backend call.
- [ ] Package as a single device flow (ESP32 does drive + capture; PC or phone shows result).

## Phase E — Optional / research
- [ ] 1D-CNN or Siamese network on the raw 360-point signature (this is where PyTorch
      finally enters). Compare against the Random Forest baseline.
