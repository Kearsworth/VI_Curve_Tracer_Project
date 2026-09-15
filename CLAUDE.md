# CLAUDE.md — AI Electronic Components Tester (COE2026-15)

> This file is read automatically by Claude Code at the start of a session.
> It is the single source of truth for how this project works. Read it fully
> before making changes. `docs/` holds the deeper detail.

## 1. What this project is (one paragraph)

A senior project that decides whether an electronic component is **good or faulty**
from its **V-I signature** (the voltage-current loop a component traces when driven
by a sine wave). A hardware "V-I curve tracer" captures the loop; a **machine-learning
software pipeline** turns that loop into a fixed set of numbers and classifies it.
This repo is mainly the **software (ML) side**, plus the ESP32 firmware that will feed
it real data.

## 2. Current status (read this — it changes what is safe to assume)

- **ML pipeline: working** on **synthetic data**. Health (good/faulty) ≈ 97.8%,
  component-type ≈ 100% (only meaningful for good parts), anomaly detector ROC-AUC ≈ 0.87.
- **Hardware (V-I tracer): in progress** — being tested by the advisor (Dr. Wathis).
- **Right now** we test the data path with an **ADC↔DAC loopback** (ESP32 sends a
  waveform out of the DAC and reads it straight back on the ADC, bypassing the real
  circuit/DUT) so we can build the software before the hardware is ready.
- **Not done yet:** real-hardware data capture, validation on real data, UI, ESP32
  firmware for the real circuit, soft-fault improvements.

## 3. Architecture & data flow

```
[ESP32]  DAC ── drive sine ──►  [circuit + DUT]  ── V, I ──►  ADC  ──USB──►  [PC / Python]
                                     (loopback: DAC→ADC directly for now)          │
                                                                                    ▼
   raw {v, i, phase, A, Rr}
        │  calibrate.py   → resample to 360 points (1 per drive-phase degree) + normalize
        ▼
   signature  (360 × 2 array)
        │  features.py    → 12 interpretable geometric/electrical features
        ▼
   feature vector (12,)
        │  train.py (offline)  → fits Random Forest + Isolation Forest, saves to models/
        │  verify.py (online)  → loads models, predicts
        ▼
   verdict:  GOOD / FAULTY  (+ confidence, detected type, anomaly flag)
```

**Golden rule:** the *same* `calibrate` + `features` code runs at training time and at
inference time. If you change one, it must stay identical for both, or predictions break.

## 4. Directory map

```
vi_ml/            The ML pipeline (Python, run from inside this folder)
  synth.py        Generates synthetic signatures for 6 components (good + faulty)
  calibrate.py    raw dict → 360-point normalized signature   (Periodic Resampling)
  features.py     signature → 12-feature vector
  train.py        build dataset → train 3 models → save to models/*.joblib
  verify.py       load models → verify(raw) → {type, verdict, confidence, anomaly}
  demo.py         end-to-end: train then verify a few fresh samples
  plot_signatures.py  renders the 6-component good-vs-faulty figure
  models/         trained models land here (git-ignored)
tests/            pytest tests that encode the invariants (run these after changes!)
hardware/         reader_stub.py — how a PySerial reader will produce the raw dict
firmware/esp32/   plan/spec for the ESP32 firmware (DAC out, ADC in, serial, loopback)
docs/             DESIGN.md (the "why"), DATA_CONTRACT.md (formats), ROADMAP.md (tasks),
                  LITERATURE.md (external check on the model-choice claims)
```

## 5. How to run

```bash
cd vi_ml
pip install -r ../requirements.txt          # numpy scipy scikit-learn joblib matplotlib
python3 demo.py                             # train + test end-to-end (prints accuracy)
python3 train.py                            # train and save models/*.joblib
python3 verify.py                           # inference demo on fresh samples

# from repo root:
pytest -q                                   # run the invariant tests (do this after edits)
```

## 6. Key design decisions — DO NOT silently undo these

These were made deliberately and validated. If you think one should change, explain
why and ask first. (Full reasoning in `docs/DESIGN.md`.)

1. **Classification, not regression.** Output is a label (good/faulty, or type), not a
   value. Don't turn it into a regressor.
2. **360 points, indexed by DRIVE PHASE (not geometric angle).** Drive phase (ωt) is
   single-valued so it works for diodes/lines where a geometric angle is multi-valued.
   Ablation showed accuracy is flat from ~30 to 720 points, so 360 is generous, not
   arbitrary. Don't switch to geometric-angle indexing.
3. **Common-factor normalization, NOT per-axis min-max.** We divide V and I by fixed
   constants (drive amplitude A, and Rr) so the V/I ratio is preserved. Per-axis
   min-max would stretch every signature to fill the frame and erase the value
   differences we need to detect faults. Never normalize each axis independently.
4. **Random Forest is the main model** (accurate on small data, low-tuning, explainable
   via feature importance). Isolation Forest is the anomaly path (trained on good only).
   RMS-distance is a no-training baseline. PyTorch is reserved for FUTURE deep learning
   (1D-CNN/Siamese) — it is NOT used yet; don't add it to the runtime path.
   **Caveat (2026-09-14):** the literature citation backing "RF beats SVM/KNN" couldn't be
   verified, and the closest real study found the opposite on soft faults — see
   `docs/LITERATURE.md` before treating this as settled or swapping the model.
5. **Faults are shape-changing by design** (open/short/reversed/ESR/DCR/leak/...).
   Mild value drift is NOT treated as a fault here (a healthy wrong-value part looks
   "good" from shape alone; catching that needs a reference-comparison path — roadmap).
6. **Type prediction is only meaningful when verdict = GOOD.** A shorted/open part
   looks like "short/open", not like its original type. This is expected, not a bug.
7. **12 features, not 720 raw points.** Interpretable + works with little data. (A CNN
   could consume raw points later; that's a separate roadmap item.)

## 7. Known limitations (state these honestly; don't hide them)

- All numbers are on **synthetic data**; real hardware will differ — must re-validate.
- **Soft faults are the weak spot:** degraded diode ~72%, Zener Vz-shift ~75%, leaky
  cap ~82% recall (hard faults are ~100%). Improving these is a roadmap item.
- Requires knowing capture settings (A, Rr) for normalization — they travel with the raw data.

## 8. Conventions

- Python 3, standard scientific stack (numpy/scipy/scikit-learn/joblib/matplotlib).
- Determinism matters: keep the RNG seeds; tests rely on reproducibility.
- Thai is fine in comments/docs; keep identifiers and log messages readable.
- When you change `calibrate.py` or `features.py`, **run `pytest` before finishing** —
  those tests guard the invariants (shape, no NaN, C/L direction, accuracy floor).
- Small, surgical changes. Don't refactor the pipeline structure without being asked.

## 9. What we're working on next (see docs/ROADMAP.md for the full list)

1. ESP32 firmware: DAC drive + 2-channel ADC read + serial framing + loopback mode.
2. `hardware/reader.py`: read serial → convert to physical units → raw dict → calibrate.
3. Validate the trained model on real captured data; retrain/fine-tune as needed.
4. Soft-fault features (reverse-leakage slope, ESR tilt, knee sharpness) + a confidence
   "review band".
5. UI (not designed yet — will plan later).

## 10. Pointers

- `docs/DESIGN.md` — the reasoning behind every decision above (why 360, why RF, etc.).
- `docs/DATA_CONTRACT.md` — exact input/output formats (raw dict, signature, features, verdict, serial frame).
- `docs/ROADMAP.md` — concrete next tasks.
- `docs/WORKING_WITH_CLAUDE.md` — how to drive Claude Code effectively on this project.
- `docs/LITERATURE.md` — external literature check on the model-choice and soft-fault
  claims in DESIGN.md, plus how our pipeline's flow compares to closely related published
  work. Read this before changing `train.py`'s classifier stack or `verify.py`'s
  evaluation, or before citing "Selim et al., 2025" as settled. §7 covers the V-I
  loop/Lissajous-feature-engineering choice specifically (separate from the §1-3
  classifier-choice check) — read it before changing `features.py`'s feature set.
