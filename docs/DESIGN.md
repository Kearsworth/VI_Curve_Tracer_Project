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

## Why 360 points, indexed by DRIVE PHASE

- **Fixed length**: raw captures vary in length (~1600 points, and not identical each time).
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
- **Coverage**: we capture ≥1 full drive cycle (the code uses ~4), so all 0–360° are
  swept; calibration folds the cycles together, bins per degree, averages, and interpolates
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
  See `docs/LITERATURE.md` §3 before treating RF's superiority as proven.
- **Isolation Forest (anomaly)**: trained on **good parts only**, flags anything unusual.
  Matches the real world where faulty examples are rare. Lower AUC (0.87) than the
  supervised model, but needs no faulty data.
- **PyTorch / deep learning (future only)**: 1D-CNN / Siamese / autoencoder are on the
  roadmap for when there's enough *real* data. Not in the current runtime path.

## Why 12 features instead of 720 raw numbers

- Lower dimensionality → learns well from small data, less overfitting.
- Each feature has physical meaning → the model is explainable, and we inject domain
  knowledge (loop area ↔ reactance, knee ↔ diode, rotation ↔ C vs L).
- Raw 720-point input is reserved for a future CNN.

The 12 features (see `features.py`): `signed_area, abs_area, slope0, phaseVI, aspect,
knee_V, symmetry, rms_radius, n_segments, peakV, peakI, spread_ratio`.

## Why faults are shape-changing (and drift is excluded)

Detectable-from-shape faults change the loop: open, short, reversed, high ESR (cap),
leakage (cap), high DCR / shorted turns (inductor), degraded/soft diode, Zener Vz shift.
A small value drift on an otherwise healthy part does **not** change the shape class — from
shape alone it looks like a healthy component of a different value. Catching parametric
drift needs a **reference-comparison** path (compare against the golden signature for that
exact position), which is a roadmap item, not a flaw in the classifier.

## Why type is only meaningful when GOOD

A shorted part looks like "short"; an open part looks like "open" — not like the original
component. So the type classifier (trained on good parts) will output a wrong type for a
faulty part. That's expected. The primary, trustworthy output is the good/faulty verdict.

## Why synthetic data

No public dataset of V-I signatures exists, and real faulty parts are hard to collect in
quantity. We generate signatures from circuit equations (Ohm's law for R; phasors for C/L;
Shockley for diodes/LED/Zener), for 6 components × good + faulty, with augmentation (noise,
phase jitter, amplitude variation). This lets us build and test the whole system before the
hardware is ready; the plan is to fine-tune / re-validate on real data later.

## Train/serve consistency

The exact same `calibrate` and `features` code path runs during training and during live
inference. If they diverge, the model sees inputs shaped differently from what it learned,
and predictions degrade silently. This is why both `train.py` and `verify.py` call the same
functions — keep it that way.
