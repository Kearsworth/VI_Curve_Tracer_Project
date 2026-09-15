# LITERATURE.md — External check on the model-choice and soft-fault claims

> Written after a literature search (alphaXiv + Firecrawl, run 2026-09-14) triggered by the
> "Selim et al., 2025" citation in `docs/DESIGN.md`. Read this before changing the
> classifier stack (`train.py`) or the evaluation code (`verify.py`), and before assuming
> the RF-vs-SVM/KNN claim is settled.

## 1. Status of the "Selim et al., 2025" citation

`docs/DESIGN.md` §"Why these models" cites "Selim et al., 2025" for the claim that Random
Forest beat SVM/KNN on I-V features. **This could not be verified.** Searches across
arXiv/alphaXiv and Firecrawl's research index + open web (multiple phrasings: "Selim
random forest SVM KNN I-V features", "Selim component health classification", "Selim I-V
curve tracer") returned no matching paper. Either the citation is slightly wrong (wrong
year, misspelled name, or it's a paper not indexed by either search), or it doesn't exist
in the form described.

**Action for whoever wrote it down**: if you have the actual PDF or a DOI, add it here with
the exact reference so it can be checked directly. Until then, treat the claim as
unverified and lean on the studies below instead, which were independently confirmed.

## 2. The closest verified literature: Dieste-Velasco et al.

Two papers solve almost exactly this project's problem — classifying faults in an analog
circuit from a small set of measured features — and are worth citing instead of, or
alongside, the unverified Selim reference.

### 2a. Dieste-Velasco, M.I. (2025). "Soft fault diagnosis in analog electronic circuits
using supervised machine learning." *Integration*, 104, 102482.
https://doi.org/10.1016/j.vlsi.2025.102482

**Pipeline**: Monte Carlo simulation (Cadence OrCAD) of a Sallen-Key band-pass filter,
sweeping each component through its fault range one at a time → 15 classes (14 single soft
faults across 2 capacitors and 5 resistors, ±10–15% deviation, plus nominal) → **6
frequency-domain voltage features** (2 measurement nodes × 3 frequencies: center frequency
and the two ±3 dB points) → 7 classifiers, each Bayesian-hyperparameter-tuned, evaluated
with cross-validation (70/15/15 split for the ANN, 7-fold CV for the rest) → reported via
Accuracy, Precision, Recall, F1, **Matthews Correlation Coefficient (MCC)**, and per-class
TPR/FNR/PPV/FDR from the confusion matrix.

**Results (test data):**

| Classifier | Accuracy | MCC | Note |
|---|---|---|---|
| ANN | 97.92% | 97.76% | best overall |
| SVM | 97.22% | 97.01% | close second |
| KNN | 95.83% | 95.56% | |
| Discriminant Analysis | 95.14% | 94.78% | |
| **Random Forest** | **93.06%** | **92.52%** | train acc. 99.39% → clear overfitting |
| Decision Tree | 88.89% | 88.04% | |
| Naive Bayes | 86.11% | 85.05% | independence assumption hurts it |

Hardest classes: the resistor faults (R4/R5, low and high) — attributed to feature-space
overlap. Capacitor faults and nominal were classified almost perfectly by every model.

### 2b. Dieste-Velasco et al. (2026). "Identification of Simultaneous Soft Faults in Analog
Circuits Using a Hybrid PSO-Machine Learning Approach." *Circuits, Systems, and Signal
Processing* (Springer).

Extends 2a from single faults to **simultaneous** two-component faults (83 combined-fault
classes + nominal, 8,300 samples, same 6-feature extraction). Two hybrid pipelines:

- **RF → PSO**: Random Forest with Bayesian-tuned hyperparameters, then PSO fine-tunes
  `NumLearningCycles`/`MinLeafSize` in a ±10% window (200 particles, 15 iterations).
  Train 98.24% → **test 86.43%**, MCC 86.26% — overfits, same pattern as 2a's plain RF.
- **PSO → ANN → grid search**: PSO picks the hidden-layer size (8–20 neurons), grid search
  refines it ±10%, trained with Scaled Conjugate Gradient. Train 94.26% → **test 93.01%**,
  MCC 92.93% — generalizes much better, and gets 39 of the 83 classes to 100% accuracy vs.
  7 for RF-PSO.

The authors explicitly note "a notable lack of studies addressing... simultaneous soft
faults" — this is a genuinely under-explored angle, relevant if soft-fault work here ever
extends past single-component faults.

## 3. What this means for our decisions

**Model choice (CLAUDE.md §6.4, DESIGN.md "Why these models").** In this independent,
closely-related study, ANN and SVM beat Random Forest on soft-fault classification, and RF
showed a visible train/test overfitting gap (99.39% → 93.06%) that our own docs don't
currently check for. This doesn't mean switch away from RF — explainability via feature
importance and low tuning cost are real, project-relevant advantages Dieste-Velasco's
benchmark doesn't score on — but it does mean:

- The "RF beats SVM/KNN" framing in DESIGN.md should be presented as *our* trade-off
  choice (explainability + low tuning), not as a literature-settled fact — the nearest
  verified comparable study found the opposite ranking.
- Our own RF should be checked for the same overfitting pattern (train vs. test accuracy
  gap), which the current pipeline doesn't report separately.
- Before adding new soft-fault features (ROADMAP Phase C), a cheap first experiment is to
  run ANN and SVM on the *existing* 12 features and compare per-fault recall against RF,
  specifically on the three known-weak soft faults. If the literature's pattern holds here
  too, that's a lower-cost win than engineering new features.

**Evaluation depth.** This project currently reports headline accuracy numbers (97.8%
health, ~100% type, 0.87 anomaly AUC) plus ad-hoc per-fault recall for the known weak
faults. Both Dieste-Velasco papers use confusion-matrix-derived per-class metrics (TPR,
FNR, PPV, FDR) and MCC as standard practice for this exact kind of problem. Adopting the
same reporting (even just MCC + a saved confusion matrix from `verify.py`/`demo.py`) would
put our results in a form directly comparable to the field, and would surface train/test
overfitting the way a single accuracy number doesn't.

**Soft faults and hybrid approaches.** ROADMAP Phase C's "confidence review band" idea is
directly precedented — it's the same instinct behind the two-stage RF→PSO and PSO→ANN
pipelines above, and behind an earlier cited approach (Bilski) that splits easy/hard cases
before classification. This is reassuring: it's a known-good pattern in this literature,
not a novel unproven idea.

**Isolation Forest / anomaly-only path.** No literature was found for one-class anomaly
detection on V-I *signature shape* (time/phase-domain geometry) specifically. What exists
under "anomaly detection + electronics" is almost entirely image-based (SEM/wafer visual
defect detection, IC inspection) or sensor time-series (photovoltaic arrays, industrial
condition monitoring) — a different modality. This isn't a warning sign about the
approach; it means there's no existing baseline to benchmark against, which is worth
stating plainly as a gap in the final report rather than implying it's well-established.

## 4. How our pipeline flow compares (for quick orientation, human or Claude Code)

```
Dieste-Velasco (2a/2b):
  circuit simulation (Monte Carlo, one/two components off-nominal)
      -> 6 frequency-domain voltage features (2 nodes x 3 frequencies)
      -> bake-off across 7 classifiers, each Bayesian/PSO-tuned
      -> confusion matrix + MCC + per-class TPR/FNR/PPV/FDR

This project (CLAUDE.md §3):
  ESP32 DAC/ADC (or loopback) -> raw {v, i, phase, A, Rr}
      -> calibrate.py: 360-point phase-indexed resample + common-factor normalize
      -> features.py: 12 interpretable time/phase-domain geometric features
      -> train.py: RF (health/type) + Isolation Forest (anomaly), model choice fixed up front
      -> verify.py: verdict (good/faulty, type, confidence, anomaly flag)
```

Structural differences worth being deliberate about, not accidental:

- **Feature domain**: their features are frequency-domain (magnitude/phase at fixed
  frequencies); ours are time/phase-domain (shape of the traced loop). Different
  information, not directly substitutable — this is a reason our numbers won't be
  perfectly comparable to theirs even after matching evaluation style.
- **Model selection**: they run a multi-classifier bake-off per problem; we picked RF/IF up
  front based on non-benchmarked reasoning (see §3 above) and haven't run a bake-off on our
  own feature set yet.
- **Evaluation**: they report MCC + confusion-matrix-derived per-class metrics as standard;
  we currently report aggregate accuracy plus informal per-fault recall.

## 5. Suggested follow-ups (tie back to `docs/ROADMAP.md` Phase C)

- Run ANN and SVM against the current RF on the existing 12-feature set, focused on the
  three known-weak soft faults (degraded diode, Zener Vz-shift, leaky cap). Cheap to try,
  directly motivated by §3.
- Add MCC and a saved confusion matrix to `verify.py`/`demo.py`'s evaluation output.
- Track train-vs-test accuracy gap for the RF model to catch the overfitting pattern seen
  in both Dieste-Velasco papers before it shows up as a real-hardware surprise.
- If real citation details for "Selim et al., 2025" turn up later, replace this section's
  caveat with the actual reference and reconcile it against the numbers here.

## 6. References

- Dieste-Velasco, M.I. (2025). Soft fault diagnosis in analog electronic circuits using
  supervised machine learning. *Integration*, 104, 102482.
  https://doi.org/10.1016/j.vlsi.2025.102482
- Dieste-Velasco, M.I. et al. (2026). Identification of Simultaneous Soft Faults in Analog
  Circuits Using a Hybrid PSO-Machine Learning Approach. *Circuits, Systems, and Signal
  Processing* (Springer). https://doi.org/10.1007/s00034-026-03531-4
- "Selim et al., 2025" (cited in `docs/DESIGN.md`) — **unverified**, see §1.

## 7. V-I loop / Lissajous-signature technique vs. similar work

> Run via the `compare-similar-work` skill, 2026-09-15, WebSearch/WebFetch only (no
> Firecrawl/alphaXiv connected this session). Scope: specifically the *time/phase-domain
> V-I loop shape* as the classification input — 360-point phase-indexed resampling +
> common-factor normalization + 12 hand-crafted geometric features (signed_area, abs_area,
> slope0, phaseVI, aspect, knee_V, symmetry, rms_radius, n_segments, peakV, peakI,
> spread_ratio) + RF/Isolation Forest. This is a different angle from §1-3 above, which
> covered the *classifier choice* using Dieste-Velasco's *frequency*-domain features — this
> section checks the loop-shape/feature-engineering choice itself, which that search didn't
> touch.

### Matches / well-supported

- **Geometric features extracted from a Lissajous-style curve, fed to an ML classifier, is
  a validated pattern** — just not yet found validated in this project's exact domain.
  Eddy-current testing (ECT) does this on magnetic-field-response Lissajous figures: a
  feature-extraction method computing 4 geometric parameters (**amplitude, width, angle,
  symmetry**) from the figure, evaluated with ML classifiers via ROC-AUC, MCC, and
  F-Measure (D'Angelo & Laracca, *Fast Eddy Current Testing Defect Classification Using
  Lissajous Figures*, IEEE, and a related 2016 low-definition-Lissajous ECT paper — full
  text of both blocked, see Unverifiable claims below, but the method description is
  consistent across independent IEEE/ScienceDirect/ResearchGate/Semantic Scholar listings).
- **V-I trajectory shape as an identity "signature" is an established idea**, not a novel
  unproven one — it's the core technique behind non-intrusive load monitoring (NILM),
  where V-I trajectory shape identifies which appliance is running from mains
  measurements. Different problem setting (see Genuinely different, below) but the same
  root idea this project is built on.
- Time/phase-domain feature engineering (rather than raw points) for small-data
  classification matches broadly standard practice, consistent with this project's own
  stated rationale in `docs/DESIGN.md`.

### Where the similar work is better

- **Evaluation rigor, again, from a second independent domain.** The ECT Lissajous work
  reports ROC-AUC, MCC, and F-Measure — the same gap already flagged in §3 from
  Dieste-Velasco's frequency-domain work, now corroborated by a completely different
  physical domain using the *same* geometric-Lissajous-feature technique this project
  uses. Two independent literatures agree on richer evaluation than this project's current
  headline-accuracy-plus-informal-recall reporting. This raises the priority of the
  existing ROADMAP Phase C item to add MCC + a saved confusion matrix — it's no longer
  only motivated by one paper.
- **The most directly on-topic paper by title could not be verified.** "Identification of
  Electronic Components based on VI Curves using Machine Learning" (ResearchGate, 2024) is
  the single closest title match to this entire project — same problem (V-I curves →
  ML → component identification) — but WebFetch returned HTTP 403 and no free full-text
  copy was found in this search. Its actual features, classifiers, and accuracy are
  **unknown**, not confirmed-and-agreeing or confirmed-and-disagreeing. This is now a
  second unresolved citation-verification gap for the project (after "Selim et al.," §1) —
  worth actually obtaining full text before citing it either way.

### Where this project's approach is better / more suited to its constraints

- **Automation.** The two closest comparable *open-hardware* projects found — both
  ESP32/microcontroller-based, both driving a DAC sine into a DUT and tracing a V-I curve —
  stop at raw curve capture/display and rely on a **human visually overlaying** a known-good
  curve against a test curve:
  - `rtek1000/Curve-Tracer-ESP32` (GitHub) — ESP32 DAC + 74HC4067 muxing, explicitly
    "Work in progress, just demonstrative, not functional" with no documented
    classification or comparison algorithm at all.
  - A microcontroller-based curve tracer on Hackaday.io — DAC-driven sine, dual op-amp
    V/X and I/Y sensing into an oscilloscope-style XY display, with a "save a curve, then
    compare visually against a new one" feature — explicitly **no algorithmic
    classification or ML across any of its five documented versions**.

  Neither has anything resembling this project's automated 360-point resample →
  12-feature → RF/Isolation-Forest pipeline. In the publicly visible hobbyist
  curve-tracer space, this project's ML automation is a genuine, stated differentiator —
  not an assumption.
- **Feature richness for this specific signal.** The ECT work's 4 generic geometric
  features (amplitude/width/angle/symmetry) wouldn't capture this project's
  electronics-specific cues — e.g. `knee_V` (diode forward-conduction knee) and
  `n_segments` (direction-change count) have no obvious ECT equivalent, because they
  encode physics (a semiconductor junction turning on) that a magnetic-field Lissajous
  figure doesn't have.

### Genuinely different, not better-or-worse

- **NILM's V-I trajectory work** identifies *appliance type* from *mains-level*
  measurements — different signal chain, different noise/loading conditions, generally no
  single controlled clean sine excitation isolated to one DUT the way this project drives
  one component directly. Related root idea, not a directly benchmarkable comparison.
- **ECT's Lissajous figures** come from an induced *magnetic field response*, not an
  electrical V-I loop — the geometric-feature-extraction *technique* transfers as a
  validated pattern, but the specific feature definitions (amplitude/width/angle/symmetry)
  don't map onto this project's electrical quantities directly.

### Unverifiable claims

- "Identification of Electronic Components based on VI Curves using Machine Learning"
  (ResearchGate, 2024) — found by title only; WebFetch blocked (403); no free full text
  located. **Do not cite its methods or numbers as confirmed** until the actual paper is
  obtained.
- D'Angelo & Laracca ECT Lissajous papers (IEEE Xplore / ScienceDirect / ResearchGate) —
  full text blocked on every host tried (403 / image-only PDF). The "4 geometric features
  + ROC-AUC/MCC/F-Measure" description is consistent across multiple independent search
  listings, which gives reasonable confidence in the qualitative method — but no specific
  accuracy numbers were confirmed from primary text, so none are reported here.

### Concrete next steps (cheapest first)

1. Get real access to "Identification of Electronic Components based on VI Curves using
   Machine Learning" (ResearchGate, 2024) — via institutional/library access or ask
   Dr. Wathis — it's the single most directly on-topic paper found and remains unread.
2. When implementing the existing ROADMAP Phase C item (MCC + confusion matrix in
   `verify.py`/`demo.py`), note it's now motivated by *two* independent literatures using
   this same Lissajous/geometric-feature technique, not one.
3. State the automation gap explicitly in any report/thesis writeup: the closest public
   ESP32/microcontroller curve-tracer projects found rely on manual visual curve
   comparison; this project's RF/Isolation-Forest automation is ahead of what's publicly
   documented in that space, not merely different from it.
4. (Exploratory, lower priority) Skim NILM V-I-trajectory literature for additional
   geometric feature ideas beyond the current 12 — a mature field built on the same root
   idea, potentially useful specifically for the soft-fault weak spots already tracked in
   Phase C.
