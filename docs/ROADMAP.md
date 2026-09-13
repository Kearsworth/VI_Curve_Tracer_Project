# ROADMAP.md — Next steps (concrete tasks)

Ordered roughly by priority. Check items off as they land.

## Phase A — Hardware/software integration (current focus)
- [ ] ESP32 firmware: generate sine on DAC, read 2 channels on ADC at a fixed, known
      sample rate, stream over USB serial. See `firmware/esp32/README.md`.
- [ ] Loopback mode: DAC wired to ADC directly (no circuit) to validate the data path
      end-to-end (send waveform, read it back, confirm it matches).
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
