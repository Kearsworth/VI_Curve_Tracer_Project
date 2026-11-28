# CLAUDE.md — AI Electronic Components Tester (COE2026-15)

> This file is read automatically by Claude Code at the start of a session.
> It is the single source of truth for how this project works. Read it fully
> before making changes. `docs/` holds the deeper detail.

## 1. What this project is (one paragraph)

A senior project that decides whether an electronic component is **good or faulty**
from its **V-I signature** (the voltage-current loop a component traces when driven
by a sine wave). A hardware "V-I curve tracer" captures the loop; a **machine-learning
software pipeline** turns that loop into a fixed set of numbers and classifies it.
This repo holds both: the ESP32 firmware, and the PC side in Python (ML pipeline, serial
reader, auto-range, tests), which is most of the code.

## 2. Current status (read this — it changes what is safe to assume)

A 60-second summary; `docs/ROADMAP.md` is the source of truth. **Phase A is done in its Case 1
form; Phase B (real data) is under way.**

- **Board: the Case 1 front end, built 2026-11-26/27** (`docs/CASE1_WIRING.md` has the wiring and
  every measurement, `docs/BOM.md` the parts). One OPA4134PA on ±15 V from a DD1718PA: ch A turns
  the DAC into the drive (gain 5.92), ch B buffers V_REF, ch C/D follow node A / node B into
  dividers to GPIO34/35. DUT from node A to node B, Rr from node B to GND, picked by a jumper:
  220 Ω / 1k / 10k / 100k (221.4 / 1022 / 10290 / 101300 Ω in circuit).
- **Firmware: `firmware/esp32/case1/case1_frontend_mf`.** Core 0 drives the DAC, core 1 reads the
  ADC by DMA; drive 1 kHz … 1 Hz (`f <hz>`), 50 points per cycle, A ≈ 4.66 V. After each burst it
  reads a GPIO32 offset reference that `reader.py` uses to cancel ADC offset drift.
- **PC: `hardware/reader.py` → the unchanged ML pipeline.** `hardware/autorange.py` picks frequency
  and Rr with `synth.auto_range`, then `autorange.judge` gives the final answer: the model's
  verdict, FAULTY for open/short, or OUT_OF_RANGE when |Z|/Rr is outside 0.25–4.
- **ML: trained on synthetic data only** (14,400 samples since 2026-11-28): any value of
  R/C/L/D/LED/Zener, simulated auto-range, measured board imperfections, 14 features. On 7,200
  unseen synthetic samples (`python3 vi_ml/eval_synth.py`): health 97.8 % (good called GOOD
  98.8 %), type 100 % on good parts, anomaly ROC-AUC 0.82.
- **Real data: `python3 hardware/eval_real.py` → 52/52** (24 kit resistors 100 Ω–300 kΩ, C,
  diode, LED; open, short, reversed, graded soft faults). Lock-in values are within ±1.5 % of a
  multimeter.
- **Open:** a ~1 % value error at 91–333 Hz (cause unknown; re-check after C5/C6 → 1 nF, parts
  not here yet); drift correction checked over 2 minutes only; no real L, Zener or electrolytic
  yet; soft faults are the weak classes (§7).

## 3. Architecture & data flow

```
[ESP32]  DAC ─ drive sine ─► [Case 1 front end + DUT] ─ node A, node B ─► ADC ─USB─► [PC / Python]
                                                                                        │
   hardware/reader.py: counts → volts, V = V_A − V_B, I = V_B / Rr, measured A          ▼
   raw {v, i, phase, A, Rr}
        │  calibrate.py   → resample to 360 points (1 per drive-phase degree) + normalize
        ▼
   signature  (360 × 2 array)
        │  features.py    → 14 interpretable geometric/electrical features
        ▼
   feature vector (14,)
        │  train.py (offline)  → fits Random Forest + Isolation Forest, saves to models/
        │  verify.py (online)  → loads models, predicts
        ▼
   verdict:  GOOD / FAULTY  (+ confidence, detected type, anomaly flag)
        │  hardware/autorange.judge → open/short and range check from the lock-in |Z|
        ▼
   final answer:  GOOD / FAULTY / OUT_OF_RANGE  (+ measured value)
```

**Golden rule:** the *same* `calibrate` + `features` code runs at training time and at
inference time. If you change one, it must stay identical for both, or predictions break.

## 4. Directory map

```
vi_ml/            The ML pipeline (Python; run from inside this folder or by path)
  synth.py        Synthetic signatures: 6 component types, good + faulty, any value, board model
  calibrate.py    raw dict → 360-point normalized signature   (Periodic Resampling)
  features.py     signature → 14-feature vector
  train.py        build dataset → train 3 models → save to models/*.joblib
  verify.py       load models → verify(raw) → {type, verdict, confidence, anomaly}
  demo.py         end-to-end: train then verify a few fresh samples
  eval_synth.py   the synthetic numbers the docs quote, on a set the models never saw
  compare_models.py  health classifier benchmark: RF vs SVM vs MLP vs gradient boosting
  plot_signatures.py  renders the 6-component good-vs-faulty figure
  models/         trained models land here (git-ignored)
tests/            pytest tests that encode the invariants (run these after changes!)
hardware/         PC side of the board: reader.py (serial frames → raw dict, zero-cal, drift
                  correction), autorange.py (frequency + Rr per part; judge() = final answer),
                  collect.py (guided batch capture), eval_real.py (model on the labelled real
                  captures), plot_real_signatures.py (README figure), demo_r.py, adc_check.py,
                  and the two-board-era live demos
  captures/       labelled real Case 1 captures + labels.csv (also run by
                  tests/test_real_captures.py; how to add one: captures/README.md)
  sim/            ngspice/Falstad checks, breadboard layout + schematic generators
firmware/esp32/   case1/ = the board in use: case1_frontend_mf (current), case1_frontend_1k and
                  case1_frontend (fallbacks); dual_core/ and loopback/ (bring-up), standalone/
                  (±5 V plan, not built), dual_board/ (retired). Index: firmware/esp32/README.md
tools/            the owner's local tmux workspace (board pane, upload.sh, zero_capture.txt,
                  board.log): git-excluded, not in the public repo
CONTEXT.md        glossary for hardware terms (node A/B, Rr, zero-cal, burst, ...) — read
                  before using these terms loosely
docs/             DESIGN.md (the "why"), DATA_CONTRACT.md (formats), ROADMAP.md (tasks,
                  the actual source of truth for status), CASE1_WIRING.md (the build and
                  every measurement, in Thai), LITERATURE.md (model-choice check),
                  research/ (side investigations, not scheduled tasks)
```

## 5. How to run

```bash
cd vi_ml
pip install -r ../requirements.txt          # numpy scipy scikit-learn joblib matplotlib pytest pyserial
python3 demo.py                             # train + test end-to-end (prints accuracy)
python3 train.py                            # train and save models/*.joblib
python3 verify.py                           # inference demo on fresh samples

# from repo root:
pytest -q                                   # run the invariant tests (do this after edits)
python3 hardware/eval_real.py               # the model on the labelled real captures
python3 vi_ml/eval_synth.py                 # synthetic numbers on an unseen set (~1 min)
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
   `docs/LITERATURE.md` before treating this as settled or swapping the model. Our own
   benchmark (2026-11-28, `vi_ml/compare_models.py`) has RF ahead of SVM and an MLP here.
5. **Faults are shape-changing by design** (open/short/reversed/ESR/DCR/leak/...).
   Mild value drift is NOT treated as a fault here (a healthy wrong-value part looks
   "good" from shape alone; catching that needs a reference-comparison path — roadmap).
6. **Type prediction is only meaningful when verdict = GOOD.** A shorted/open part
   looks like "short/open", not like its original type. This is expected, not a bug.
7. **14 interpretable features, not 720 raw points.** Interpretable + works with little data.
   12 original + 2 soft-fault features added 2026-11-27 with the owner's OK: `off_slope`
   (blocking-side dI/dV → junction leakage) and `on_res` (conducting-side dV/dI past the knee →
   degraded diode/LED). (A CNN could consume raw points later; separate roadmap item.)

## 7. Known limitations (state these honestly; don't hide them)

- The model is trained on **synthetic data only**. The real check is 52 labelled captures (all
  right): too few to compare with the synthetic numbers, and soft faults only at a few strengths.
- **Soft faults are the weak spot** (synthetic, `vi_ml/eval_synth.py`): high-ESR C 85 %, Zener
  leak 86 %, shorted turns 87 %, leaky C 90 %, high-DCR L 94 %, reversed/degraded diode ~97–98 %;
  hard faults 100 %. "Good" C allows DF up to 6% (class-II ceramics measured ~4–5%);
  healthy aluminium electrolytics can reach DF 10–20%, which this synth would call high-ESR —
  ESR limits really depend on the capacitor type (needs the reference/type path).
- **Measuring range:** the model judges |Z|/Rr from 0.25 to 4 with Rr 221 Ω … 101 kΩ, so
  resistive parts from ~55 Ω to ~400 kΩ (trained on 100 Ω–300 kΩ); outside that the tester
  answers OUT_OF_RANGE. The Rr jumper is moved by hand when autorange asks.
- **Drive amplitude:** synth trains A = 4–6 V and the firmware drives ≈ 4.66 V. At ±10 V the
  diode/LED/Zener knees fall outside the training data (`docs/BOM.md` §5). Electrolytic C can't
  be tested yet: the AC drive reverse-biases it (needs a DC bias or a low amplitude).
- Values read ~1 % off at 91–333 Hz with `case1_frontend_mf` (cause unknown).
- Requires knowing capture settings (A, Rr) for normalization — they travel with the raw data.

## 8. Conventions

- Python 3, standard scientific stack (numpy/scipy/scikit-learn/joblib/matplotlib).
- Determinism matters: keep the RNG seeds; tests rely on reproducibility.
- Thai is fine in comments/docs; keep identifiers and log messages readable.
- When you change `calibrate.py`, `features.py`, `synth.py` or `hardware/reader.py`, **run
  `pytest` before finishing** — those tests guard the invariants (shape, no NaN, C/L direction,
  accuracy floor) and every real-capture verdict.
- Small, surgical changes. Don't refactor the pipeline structure without being asked.
- This project doesn't use Gmail, Google Calendar, or Google Drive. Even if those MCP
  connector tools are available in the session (they're account-level, not project-scoped),
  don't invoke them for anything in this repo.

## 9. What we're working on next (docs/ROADMAP.md is the real list — this is a pointer, not a copy)

1. More real data (Phase B): inductors and Zeners; an electrolytic needs a DC bias or a low
   drive first.
2. Swap C5/C6 to 1 nF when the parts arrive, redo the zero-cal, then re-check the noise and the
   ~1 % error at 91–333 Hz.
3. A long run of the GPIO32 drift correction (tens of minutes, a power cycle).
4. Soft faults (Phase C): RF vs SVM/ANN on the 14 features, ESR tilt and knee features, a
   confidence "review band".
5. UI (not designed yet — will plan later).

## 10. Pointers

- `CONTEXT.md` — glossary for hardware vocabulary (node A/B, Rr, drive amplitude, zero-cal,
  offset reference, burst, auto-range, ...). Read before using these terms loosely in new docs/code.
- `firmware/esp32/README.md` — which sketch does what, which one to flash, and the bring-up
  history behind them.
- `firmware/esp32/dual_board/README.md` — the two-board bring-up: wiring, phase-sync design,
  what's verified vs. still open (the real-circuit sync plan lives here, not in ROADMAP.md).
- `docs/research/` — side investigations (e.g. serial-capture performance) that are
  deliberately *not* roadmap tasks; read before re-investigating the same thing.
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
