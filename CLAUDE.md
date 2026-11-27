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

**Phase: A (hardware/software integration), late stage — see `docs/ROADMAP.md` for the
full checklist. This section is a 60-second summary, not the source of truth; ROADMAP.md
is.**

- **ML pipeline: working** on **synthetic data**. Since 2026-11-27 `synth.py` draws R/C/L over
  the full value range (R 100 Ω–300 kΩ, C 1 nF–1000 µF, L 10 mH–10 H) with a simulated
  auto-range (drive frequency + Rr chosen so |Z|/Rr ≈ 1) and the measured Case 1 board
  imperfections (node noise/offset/quantization, ADC crosstalk, V-I skew, ADC spikes, 40–60
  points/cycle, phase-locked sampling like the real board). On that harder data with the 14
  features: health ≈ 98% (good parts called GOOD 99.5%), type ≈ 100% (good parts), anomaly
  ROC-AUC ≈ 0.83. The older one-value model
  (97.8% on its own data) scores ≈ 75% on it, mostly by calling good parts of other values
  FAULTY. First real-board check (50 Hz firmware): 4/4
  good-resistor captures → GOOD, 1/1 open socket → FAULTY. A 1 kHz DMA firmware
  (`firmware/esp32/case1/case1_frontend_1k`, 2026-11-27) also reads a 1k resistor as GOOD, with
  the V-I phase error down from 2.4° to ~0.4° and ADC crosstalk from ~4 % to ~0.1 %; with
  per-channel divider gains, zero-cal and phase labels aligned to node A, a 988 Ω resistor
  (meter) reads 988.8 Ω and verifies GOOD, and the first real capacitor (0.1 µF ceramic, Rr 1k)
  reads 97.3 nF and verifies C / GOOD (`docs/CASE1_WIRING.md`, ADC step 2). Since 2026-11-27
  `case1_frontend_mf` drives 1 kHz … 1 Hz by serial command (`f <hz>`, 50 points/cycle at every
  frequency) and `hardware/autorange.py` / board-page `auto` picks frequency + Rr per part with
  `synth.auto_range` (a 0.1 µF: chose 1 kHz + Rr 1k by itself → 100.6 nF, C / GOOD); real-data
  check: `python3 hardware/eval_real.py` (13/13).
- **Real-hardware capture: working**, as of 2026-09-29/30 — two ESP32 boards
  (`firmware/esp32/dual_board/`), one faking a V-I signature, one capturing it on two real
  ADC channels with sync-derived phase. Real captures flow through `hardware/reader.py` →
  `calibrate.py` → `features.py` → `verify.py` with **zero ML-code changes**. See
  `firmware/esp32/dual_board/README.md` for the evidence table and `CONTEXT.md` for the
  vocabulary (signature generator, capture unit, sync pulse).
- **Top open problem right now (updated 2026-10-04):** the drive is back to the ESP32's own
  DAC — not an external voltage source as the 2026-09-30 note said — through the confirmed
  0–3.3V→±10V drive stage. Per Dr. Wathis: split the ESP32 into **two FreeRTOS cores**, one
  driving the DAC sine, the other reading both ADC channels and streaming. Because it's one
  chip again, the inter-board sync-pulse problem is **gone** — both cores share the same
  hardware clock, so phase comes from elapsed time against one shared cycle-start timestamp,
  same principle the single-board loopback already used. The two-board `dual_board/` setup
  and the external-generator sync plan are **retired** — see `dual_board/README.md`. The real
  blocker now: the **return path** (±10V DUT response → 0–3.3V for the ADC) is still
  unconfirmed. See `firmware/esp32/README.md` "Dual-core single-board plan" and
  `docs/ROADMAP.md` Phase A.
- **Front end being built (decided 2026-11-25): Case 1** — Dr. Wathis's 0–3.3V→±10V drive
  stage, rebuilt with an **OPA4134PA** (4 channels: A drive ×6.1 difference amp, B V_REF
  buffer, C/D followers on node A/B for the return path) on ±15V rails from a **DD1718PA**.
  Parts and why: `docs/BOM.md` (its §4 sketch is wrong as drawn — see the note there).
  **Hole-by-hole wiring + 7-step power-up checks: `docs/CASE1_WIRING.md`** (layout generated
  and netlist-checked by `hardware/sim/make_case1_breadboard.py`). Software for it:
  `firmware/esp32/case1/case1_frontend` (inverted LUT, A ≈ 5V default) and
  `reader.FrontEnd.case1()`, auto-picked from the meta line's `frontend_case=1`. **Status
  2026-11-25: planned, not built; software untested on hardware; C5/C6 are 100 pF until the
  ordered 1 nF arrive.** The ±5V NE5532 design in `docs/STANDALONE_TESTER_PLAN.md` is the
  unbuilt alternative — don't mix the two BOMs. At ±10V the model is out-of-distribution for
  D/LED/Zener until `synth.py` is retrained at A=10 (`docs/BOM.md` §5, ROADMAP Phase B).
- **Not done yet:** connecting the real circuit (blocked on the above), UI, soft-fault
  improvements. See `docs/ROADMAP.md` for the live task list — this file is a summary of it,
  not a duplicate; when the two disagree, ROADMAP.md is right.

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
   feature vector (14,)
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
  features.py     signature → 14-feature vector
  train.py        build dataset → train 3 models → save to models/*.joblib
  verify.py       load models → verify(raw) → {type, verdict, confidence, anomaly}
  demo.py         end-to-end: train then verify a few fresh samples
  plot_signatures.py  renders the 6-component good-vs-faulty figure
  models/         trained models land here (git-ignored)
tests/            pytest tests that encode the invariants (run these after changes!)
hardware/         reader.py (serial frames → raw dict), live_pipeline_demo.py (live two-board
                  dashboard), dual_board_signature_check.py, adc_check.py, live_plot_demo.py,
                  demo_r.py (live R meter), eval_real.py (model on labelled real captures)
  captures/       labelled real Case 1 captures + labels.csv (also run by
                  tests/test_real_captures.py; how to add one: captures/README.md)
firmware/esp32/   loopback/ (single-board, verified) and dual_board/ (two-board, verified) —
                  both implemented and run on real hardware, not just spec anymore;
                  case1/case1_frontend (Case 1 front end, compiles, not yet on hardware)
CONTEXT.md        glossary for hardware terms (DUT, sense resistor, signature generator,
                  capture unit, sync pulse, ...) — read before using these terms loosely
docs/             DESIGN.md (the "why"), DATA_CONTRACT.md (formats), ROADMAP.md (tasks,
                  the actual source of truth for status), LITERATURE.md (model-choice check),
                  research/ (side investigations, not scheduled tasks)
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
7. **14 interpretable features, not 720 raw points.** Interpretable + works with little data.
   12 original + 2 soft-fault features added 2026-11-27 with the owner's OK: `off_slope`
   (blocking-side dI/dV → junction leakage) and `on_res` (conducting-side dV/dI past the knee →
   degraded diode/LED). (A CNN could consume raw points later; separate roadmap item.)

## 7. Known limitations (state these honestly; don't hide them)

- All numbers are on **synthetic data**; real hardware will differ — must re-validate.
- **Soft faults are the weak spot** (2026-11-27 synth, 14 features): high-ESR cap ~82%,
  shorted turns ~83%, Zener leak ~85%, leaky cap ~93%, degraded diode/LED and reversed diode
  ~95–96%; hard faults ~100%. "Good" C allows DF up to 6% (class-II ceramics measured ~4–5%);
  healthy aluminium electrolytics can reach DF 10–20%, which this synth would call high-ESR —
  ESR limits really depend on the capacitor type (needs the reference/type path).
- **"Any value" assumes auto-ranging hardware that doesn't exist yet:** synth picks the drive
  frequency from 1 Hz–1 kHz and Rr from 220 Ω/1k/10k/100k (`synth.TEST_FREQS_HZ`,
  `RR_OPTIONS`). The board today has 1k/10k/100k by jumper and one drive frequency per
  firmware, so big C (above ~10 µF) and small L can't yet be measured for real.
- Requires knowing capture settings (A, Rr) for normalization — they travel with the raw data.

## 8. Conventions

- Python 3, standard scientific stack (numpy/scipy/scikit-learn/joblib/matplotlib).
- Determinism matters: keep the RNG seeds; tests rely on reproducibility.
- Thai is fine in comments/docs; keep identifiers and log messages readable.
- When you change `calibrate.py` or `features.py`, **run `pytest` before finishing** —
  those tests guard the invariants (shape, no NaN, C/L direction, accuracy floor).
- Small, surgical changes. Don't refactor the pipeline structure without being asked.
- This project doesn't use Gmail, Google Calendar, or Google Drive. Even if those MCP
  connector tools are available in the session (they're account-level, not project-scoped),
  don't invoke them for anything in this repo.

## 9. What we're working on next (docs/ROADMAP.md is the real list — this is a pointer, not a copy)

1. Build the Case 1 front end on breadboard step by step per `docs/CASE1_WIRING.md`, then
   capture real R/D signatures with `case1_frontend` (the sync-plan item that used to be here
   is retired — see `dual_board/README.md`).
2. ADC decision experiment (internal vs. external) — not yet run.
3. Validate the trained model on real captured data; retrain/fine-tune as needed.
4. Soft-fault features (reverse-leakage slope, ESR tilt, knee sharpness) + a confidence
   "review band".
5. UI (not designed yet — will plan later).

## 10. Pointers

- `CONTEXT.md` — glossary for hardware vocabulary (DUT, drive node, signature generator,
  capture unit, sync pulse, ...). Read before using these terms loosely in new docs/code.
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
