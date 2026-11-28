# DESIGN.md — Why the system is built this way

This document explains the *reasoning* behind each design decision so that future work
(and Claude Code) doesn't accidentally undo something intentional. If a change conflicts
with a point here, discuss it first.

## The core idea

Each electronic component, when driven by a sine wave through a series resistor, traces a
characteristic **V-I loop** ("signature") on an X-Y plot: a resistor is a line, a
capacitor/inductor is an ellipse, a diode is a bent "hockey stick". A fault distorts the
loop. We turn that loop into numbers and let a model decide good vs faulty. It's analogous
to a doctor reading an ECG: normal shape vs abnormal shape.

## Why an oscilloscope/ADC can measure current at all

A scope/ADC measures **voltage** only. We put a **series "sense" resistor** in the loop:
the same current flows through it and through the component, and by Ohm's law the voltage
across it is proportional to that current (V = I·R). So we read a voltage and treat it as
the current axis. The sense resistor is switchable so we can match components that draw
very different currents.

## Why classification (not regression)

The question is "is it good or faulty?" → a **label**, not a number. Health is binary;
type is 6-class. Predicting the exact component value (e.g. "2.1 kΩ") would be regression
and is explicitly out of scope for now.

The tester does print a value (e.g. "995 Ω", "100.6 nF"), but that is a measurement, not a
prediction: a lock-in of the drive-frequency component gives Z = V/I directly
(`hardware/autorange.lockin_z`). The model never sees or outputs it.

## Why 360 points, indexed by DRIVE PHASE

- **Fixed length**: raw captures vary in length (the Case 1 burst firmware sends 50 points per
  cycle for up to 32 cycles, the older 50 Hz sketches stream 50–65 per cycle, synth draws
  40–60).
  A model can't compare variable-length inputs point-by-point. Resampling to a fixed 360
  makes every signature the same shape → directly comparable, no time-warping needed.
- **Drive phase, not geometric angle**: we index by the phase of the *drive signal* (ωt,
  0–360°), which is monotonic and single-valued. A geometric angle around the loop is
  multi-valued for diodes and straight lines (one angle → several points), which breaks
  the mapping. Drive phase always has exactly one point per degree.
- **Direction preserved**: because points are ordered by phase/time, the loop's traversal
  direction is kept. This is the ONLY still-image cue that separates a capacitor
  (clockwise) from an inductor (counter-clockwise).
- **Why 360 specifically**: an ablation (N = 30, 45, 90, 180, 360, 400, 720) showed
  accuracy is essentially flat — the signal has few harmonics. 360 is generous (1 point /
  degree), clean, and leaves headroom for sharp features. 400 gives no measurable gain;
  smaller (e.g. 180) would also work. Don't "upgrade" to 400 expecting improvement.
- **Coverage**: we capture ≥1 full drive cycle (synth draws 8–24, the board sends up to 32),
  so all 0–360° are swept; calibration folds the cycles together, bins per degree, averages, and interpolates
  any empty bin. The loop is covered by construction; which quadrants it occupies is part
  of the signature (a resistor is Q1/Q3 only — that's correct, not a gap).

## Why common-factor normalization (never per-axis min-max)

We divide V by the drive amplitude A, and I·Rr by A — i.e. both axes by **fixed
constants**. This keeps signatures dimensionless and comparable **while preserving the
V/I ratio**, so a bigger/smaller loop still means something.

Per-axis min-max (stretch each axis to fill −1..1) would make a 1 kΩ and a 2 kΩ resistor
look identical, erasing exactly the value information we need. So different subplots having
different axis ranges is *correct* — the sizes are part of the signature. Never rescale
axes independently.

## Why these models (staged: simple → smart)

- **RMS-distance baseline (no training)**: measures distance from a known-good reference,
  thresholds it. It's the floor every real model must beat.
- **Random Forest (main)**: accurate with little data, needs almost no tuning, no feature
  scaling required, handles non-linear boundaries, and — crucially — is **explainable**
  via feature importance (we can say *which* features drove a decision). The originally
  cited backing ("Selim et al., 2025", RF beat SVM/KNN on I-V features) could not be
  independently verified — see `docs/LITERATURE.md` §1. The closest verified study on the
  same kind of problem (Dieste-Velasco, 2025, *Integration* 104, 102482) actually found
  ANN (97.9%) and SVM (97.2%) beating RF (93.1%, with a visible train/test overfitting gap)
  on soft-fault classification. RF stays our main model for its explainability and low
  tuning cost — that's a deliberate trade-off we're making, not a literature-settled fact.
  See `docs/LITERATURE.md` §3 before treating RF's superiority as proven. Our own benchmark
  (2026-11-28, `vi_ml/compare_models.py`, 300 training samples per class) agrees with keeping RF
  on our 14 features: RF and gradient boosting 97.3 % on unseen synthetic data, SVM 95.8 %, an
  MLP 95.6 %. More data helped more than another model, so `train.py` now uses 1,200 per class.
- **Isolation Forest (anomaly)**: trained on **good parts only**, flags anything unusual.
  Matches the real world where faulty examples are rare. Lower AUC than the supervised
  model (0.82 on the full-value-range synth, `vi_ml/eval_synth.py`; it was 0.87 on the old
  one-value synth), but needs no faulty data.
- **PyTorch / deep learning (future only)**: 1D-CNN / Siamese / autoencoder are on the
  roadmap for when there's enough *real* data. Not in the current runtime path.

## Why 14 features instead of 720 raw numbers

- Lower dimensionality → learns well from small data, less overfitting.
- Each feature has physical meaning → the model is explainable, and we inject domain
  knowledge (loop area ↔ reactance, knee ↔ diode, rotation ↔ C vs L).
- Raw 720-point input is reserved for a future CNN.

The 14 features (see `features.py`): the original 12 — `signed_area, abs_area, slope0,
phaseVI, aspect, knee_V, symmetry, rms_radius, n_segments, peakV, peakI, spread_ratio` — and
two soft-fault features added 2026-11-27, still physical: `off_slope` (dI/dV on the blocking
side at low current = junction leakage) and `on_res` (dV/dI past the knee on the conducting
side = series resistance). On the full-value-range synth they lifted Zener-leak
recall from ~10% to ~85% and degraded-LED recall from ~20% to ~96%; `slope0` couldn't see
either because its window around 0 V is dominated by the forward knee.

## Why faults are shape-changing (and drift is excluded)

Detectable-from-shape faults change the loop: open, short, reversed, high ESR (cap),
leakage (cap), high DCR / shorted turns (inductor), degraded/soft diode, Zener junction leakage
(Zener Vz shift was dropped 2026-11-27: with Vz over a range it is value drift, see below).
A small value drift on an otherwise healthy part does **not** change the shape class — from
shape alone it looks like a healthy component of a different value. Catching parametric
drift needs a **reference-comparison** path (compare against the golden signature for that
exact position), which is a roadmap item, not a flaw in the classifier.

## Why type is only meaningful when GOOD

A shorted part looks like "short"; an open part looks like "open" — not like the original
component. So the type classifier (trained on good parts) will output a wrong type for a
faulty part. That's expected. The primary, trustworthy output is the good/faulty verdict.

## Why the tester can answer OUT_OF_RANGE (added 2026-11-27)

After normalisation a linear part's loop depends on |Z|/Rr, and synth only trains |Z|/Rr near
1 (auto-range picks 0.5–2). Far outside that, a good part's loop looks like a fault: a good
10 Ω on Rr 221 Ω is an almost vertical line, like a short; a good 1 MΩ on Rr 101 kΩ is almost
flat, like an open. The model called both FAULTY, which is right for the shapes it was trained
on. So `hardware/autorange.judge` checks the lock-in first: no current → FAULTY (open), |Z|
near 0 → FAULTY (short), |Z|/Rr outside 0.25–4 on a linear part → OUT_OF_RANGE with the value
and the Rr or frequency to try instead; everything else gets the model's verdict. A part with
strong harmonics (diode, LED, Zener) skips the short and range checks and gets the model's
verdict. All 52
scored real captures stay with the model (`tests/test_autorange.py`).

## Why synthetic data

No public dataset of V-I signatures exists, and real faulty parts are hard to collect in
quantity. We generate signatures from circuit equations (Ohm's law for R; phasors for C/L;
Shockley for diodes/LED/Zener), for 6 components × good + faulty, with augmentation (noise,
phase jitter, amplitude variation). This lets us build and test the whole system before the
hardware is ready; the plan is to fine-tune / re-validate on real data later.

Since 2026-11-27 synth draws every value over the whole range (R 100 Ω–300 kΩ, C 1 nF–1000 µF,
L 10 mH–10 H), picks the drive frequency and Rr with the same auto-range rule the board uses,
and adds the Case 1 board's measured imperfections (node noise and offset, ADC crosstalk and
spikes, V/I skew, phase-locked sampling). Real captures so far agree with it: the 52 labelled
ones all come out right, and the real good/faulty boundaries of graded soft faults match
synth's ranges (`docs/CASE1_WIRING.md` ADC step 3).

## Train/serve consistency

The exact same `calibrate` and `features` code path runs during training and during live
inference. If they diverge, the model sees inputs shaped differently from what it learned,
and predictions degrade silently. This is why both `train.py` and `verify.py` call the same
functions — keep it that way.
