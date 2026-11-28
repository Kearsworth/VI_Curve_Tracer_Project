# ROADMAP.md — Next steps (concrete tasks)

Ordered roughly by priority. Check items off as they land.

## Phase A — Hardware/software integration (mostly done: the Case 1 board works end to end)
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
      ±10V→0–3.3V return-path gain (still unconfirmed). *Done for Case 1 (2026-11-26/27):*
      `FrontEnd.case1` (each divider's measured gain), zero-cal, and the GPIO32 drift reference.
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
- [x] **Dual-core single-board bring-up (updated 2026-10-04, supersedes the external-generator
      sync plan; done in its Case 1 form 2026-11-26/27):** per Dr. Wathis, the drive goes back to the ESP32's own DAC
      (through the confirmed ±10V drive stage), not an external source — so the two-board setup
      and its sync-pulse problem are retired. New plan: one ESP32, two FreeRTOS tasks pinned
      one per core (`xTaskCreatePinnedToCore`) — Core A drives the DAC sine from a LUT (reusing
      `loopback/sine_capture.ino`'s approach), Core B reads both ADC channels and streams CSV,
      same frame format as today (zero `hardware/reader.py` changes). No sync wire needed: both
      cores share one hardware clock, so phase comes from elapsed time since one shared `t0us`,
      exactly like the single-board loopback already does — just parallelized so blocking
      `analogRead()`/`Serial` on the capture side can't jitter the drive timing. See
      `firmware/esp32/README.md` "Dual-core single-board plan" for the full design.
      Step 1 (dual-core loopback, `firmware/esp32/dual_core/dual_core_loopback/`) written and
      **verified on hardware 2026-10-09** (core split works, ~65 samples/cycle, V/I corr
      0.9993 on two real pins — numbers in `firmware/esp32/README.md`). Logic analyzer then found
      UART saturation causing ~1.6 ms sample holes; fixed the same day (bounded line length +
      fixed 333 µs sample grid → 0 dropped samples). Steps 2–4 were done by the Case 1 build
      (next items): the drive stage, the return path (OPA4134 followers + dividers) and real DUTs.
      Every Case 1 sketch keeps this core split (core 0 drive, core 1 ADC). `live_pipeline_demo.py`
      was not ported to Case 1.
      ~~Old plan, retired 2026-10-04: external voltage source/function generator driving the
      DUT directly with a sync pulse into GPIO27 (two options worked out, comparator-IC
      fallback if chatter) — see `dual_board/README.md` Next steps item 3 for the superseded
      detail, kept for the record.~~

- [ ] **Standalone tester plan (drafted 2026-10-10; Stage 0 simulation passed same day, not built yet):** our own
      USB-powered front end — ±5 V drive (MT3608 + ICL7660S rails, NE5532), ESP32-selected Rr
      bank (220 Ω / 1 kΩ / 10 kΩ / 100 kΩ via relays), 50/200/1000 Hz, DMA capture, then ML
      retrained for selectable settings + auto-range. Stages 0–5 and BOM in
      `docs/STANDALONE_TESTER_PLAN.md`. Needs Dr. Wathis's OK since it runs alongside his ±10 V stage.
      **2026-11-25: not being built** — the physical build is Case 1 (his ±10 V stage with
      OPA4134PA + DD1718PA ±15 V, `docs/BOM.md`); this stays as the ±5 V alternative.

- [x] **Case 1 breadboard build** — built and brought up 2026-11-26/27 (`docs/CASE1_WIRING.md`,
      wired by node names, not the generated hole layout). Firmware: `case1_frontend` (50 Hz,
      fallback), `case1_frontend_1k` (1 kHz DMA), `case1_frontend_mf` (1 kHz … 1 Hz by serial
      command, 2026-11-27). Rr 220 Ω / 1k / 10k / 100k by jumper. Still to do: swap C5/C6 to 1 nF
      when it arrives, redo zero-cal, re-measure noise.
- [ ] **Auto-range on the real board** — `hardware/autorange.py` (also `auto` in the board page)
      measures at 1 kHz, picks frequency + Rr with `synth.auto_range` (the rule synth trains
      with), asks for the Rr jumper move, checks 1 Hz before calling something a short.
      Planning is unit-tested. On hardware: a nonlinear DUT read the same |Z| at all 7
      frequencies, and a 0.1 µF ceramic (2026-11-27) was planned at 1 kHz + Rr 1k by itself →
      100.6 nF, C / GOOD (sweep at Rr 1k: 97–106 nF from 1 kHz to 10 Hz; 3 Hz and 1 Hz unreadable
      at Rr 1k, as expected — `docs/CASE1_WIRING.md` ADC step 3). A 988 Ω resistor: auto → 1 kHz
      + Rr 1k, 995 Ω, R / GOOD; across frequencies it reads within ~0.2 % at ≤ 30 Hz but has a
      repeatable ~1 % / up to 1.1° error at 91–333 Hz (+0.7 % at 1 kHz, where the old 1 kHz
      firmware read +0.08 %) — cause not found yet. A short-circuit sweep shows the channels
      match when they see the same signal (gain −0.13…−0.25 %, timing < 1 µs), so the error only
      appears when the two channels see different voltages; parked — re-check the R sweep after
      the C5/C6 swap.
      Then 1 nF (Rr 100k, needs a jumper move) and a big electrolytic (needs low amplitude —
      not supported yet).
- [x] **Offset drift → automatic zero (found and built 2026-11-27):** node offsets moved by up to
      ~0.25 V within minutes, the same way on both channels (likely the ESP32 3V3 feeding the
      dividers; the ADC isn't ratiometric). A third divider with its input at GND now sits on
      GPIO32; `case1_frontend_mf` reads it after every burst (`ref_counts=` on the `# burst=`
      line) and `reader.py` subtracts its move since the zero capture from both channels. Over a
      2-minute check the corrected baseline stayed within ~25 mV where the uncorrected one moved
      26–62 mV. Still to see: a long run (tens of minutes, a power cycle). The zero must be taken
      with this firmware (`docs/CASE1_WIRING.md` ADC step 3).
- [ ] **ADC decision experiment:** flash `firmware/esp32/loopback/adc_step`, run
      `python3 hardware/adc_check.py --port <port>` with a multimeter on GPIO34. Budget ≈ 2
      counts (10 mV at the ±10 V return-path scale). PASS → internal ADC; BORDERLINE → also
      order the external ADC; FAIL → external ADC (AD7606-class: simultaneous, ±10 V input).
      Write ADR-0001 once chosen. Budget ceiling was $30 (external module may need ~$40);
      2–3 weeks lead time.
      *Status 2026-11-28:* this step test and ADR-0001 were never done. Case 1 runs on the
      internal ADC (DMA, the eFuse calibration table, zero-cal, GPIO32 offset reference) and reads
      24 kit resistors within ±1.5 % of a multimeter, so nothing has needed the external ADC yet.
- [x] Drive at ~1 kHz for real C/L captures (synthetic data was tuned to 1 kHz then: 100 nF and
      100 mH look open/short at 50 Hz). Done with DMA on the internal ADC: `case1_frontend_1k`
      (2026-11-27), then `case1_frontend_mf` (1 kHz … 1 Hz). Real C captured; no real L yet
      (Phase B).
- [x] Measured `A`: `reader.frontend_to_raw` takes A from node A itself (half its 1st–99th
      percentile span). Amplitude leveling wasn't built: it is only needed if A leaves synth's
      4–6 V band, and the board sits at ≈ 4.66 V.
- [x] Current from two matched channels, in the Case 1 form: the DUT sits between node A and
      node B with Rr from node B to GND, so V_DUT = V_A − V_B and I = V_B / Rr
      (`reader.FrontEnd.dut`), each channel with its own measured divider gain
      (`FrontEnd.case1`). A short-circuit sweep shows the two channels agree within 0.25 % and
      1 µs (`docs/CASE1_WIRING.md` ADC step 3).

## Phase B — Real data & validation (current focus)
- [ ] **Retrain `synth.py` at A = 10 V — only if the drive is raised to ±10 V** (added
      2026-11-25). `calibrate.py` divides V by A, so a ~0.6 V diode knee lands at 0.6/5 = 0.12
      in training but 0.6/10 = 0.06 at ±10 V: a different normalised shape, i.e.
      out-of-distribution. R, C, L scale with A and are unaffected. Since 2026-11-27 `synth.py`
      draws A from 4–6 V for every component (Zener included), and the Case 1 firmware drives
      A ≈ 4.66 V, so D/LED verdicts today are in distribution. If the amplitude goes up, add
      A = 10 to the training set, then rerun `pytest` (the accuracy-floor test retrains the
      models). Reasoning: `docs/BOM.md` §5.
- [ ] Capture real signatures for R/C/L/D/LED/Z on the Case 1 board, good and (deliberately
      created) faulty. *Started 2026-11-27:* `hardware/captures/`
      (labels.csv) has R, C, diode, LED good; open, short, reversed diode, reversed LED; and soft
      faults built from good parts (leaky C, high-ESR C, degraded diode). Since 2026-11-27 also
      24 good resistors 100 Ω – 300 kΩ from a 1 % kit (`hardware/collect.py r`): all GOOD, values
      within ±1.5 % of a multimeter. Graded soft faults from kit resistors (`esr`, `leak`,
      `degraded`, `led`, 16 parts): every scored one right, and the model's real-data boundaries
      match synth's ranges (`docs/CASE1_WIRING.md` ADC step 3). Outside the trained range
      (`r_oor`: 10 Ω, 47 Ω, 470k, 1M) the values are still right but the model calls the
      extremes FAULTY (short-/open-like shapes). Done: `autorange.judge` answers OUT_OF_RANGE with the
      value when |Z|/Rr is outside 0.25–4, open/short from the current and |Z|, and the model's
      verdict everywhere else (all 52 scored captures stay with the model). Still missing L,
      Zener and an electrolytic C.
- [ ] Re-run evaluation on real held-out data; compare to the synthetic numbers.
      *First pass 2026-11-27:* `python3 hardware/eval_real.py` → 52/52 verdicts correct (still
      too few to compare with the ~98 % synthetic number; soft faults are strong versions only).
- [ ] Fine-tune / retrain on a mix of synthetic + real; keep the synthetic pipeline as
      a bootstrap.

## Phase C — Model quality (soft faults)
- [x] Quick experiment first: benchmark ANN and SVM against the current RF on the
      *existing* 14 features, focused on the weakest soft faults. Motivated by
      docs/LITERATURE.md §3 — a closely related published study found ANN/SVM beating RF
      specifically on soft faults. **Done 2026-11-28** (`python3 vi_ml/compare_models.py`: each
      model tuned by 5-fold CV on train.py's split with its former 300 samples per class, scored
      on 7,200 unseen synthetic samples and the real captures):

      | model | unseen acc | good → GOOD | Zener leak | shorted turns | high-ESR C | leaky C | real |
      |---|---|---|---|---|---|---|---|
      | RF (train.py; CV picks the same settings) | 97.3 % | 98.7 % | 81 % | 83 % | 84 % | 87 % | 52/52 |
      | gradient boosting | 97.3 % | 97.9 % | 83 % | 86 % | 86 % | 88 % | 52/52 |
      | SVM (RBF) | 95.8 % | 98.1 % | 68 % | 76 % | 81 % | 81 % | 51/52 |
      | MLP (128, 64) | 95.6 % | 98.0 % | 44 % | 80 % | 82 % | 84 % | 51/52 |

      The published ranking doesn't carry over to these features, so RF stays. Gradient boosting
      ties overall but calls more good parts FAULTY and gives near-0/1 probabilities on the real
      boundary parts. More data helps more than another model: RF trained on 14,400 samples →
      97.9 %, Zener leak 89 %, leaky C 93 %, good parts and real captures unchanged; shorted turns
      (~83 %) and high-ESR C (~87 %) don't move, so they need features (below).
- [x] Train on more synthetic data. **Done 2026-11-28:** `train.py` 300 → 1,200 samples per
      component and health (14,400 in all). `vi_ml/eval_synth.py`: health 97.3 → 97.8 %, MCC
      0.941 → 0.951, good parts GOOD 98.7 → 98.8 %, Zener leak 81 → 86 %, shorted turns 83 → 87 %,
      high-ESR C 84 → 85 %, leaky C 87 → 90 %; real captures still 52/52; `train.py`'s own test
      split 97.4 → 98.4 %. Costs: `train.py` ~40 s, `eval_synth.py` ~1 min, `pytest` ~1.5 min
      (was ~25 s; `tests/test_pipeline.py` retrains twice).
- [x] Report MCC, a confusion matrix and the RF's train-vs-test gap, as the soft-fault
      literature does (docs/LITERATURE.md §3, §7). *Done 2026-11-28:* `vi_ml/eval_synth.py`
      prints MCC (0.95), the health confusion matrix and recall per fault on 7,200 unseen
      synthetic samples; `vi_ml/compare_models.py` prints train / CV / unseen accuracy (RF at
      300 per class: 99.5 / 97.3 / 97.3 %, a 2-point train gap as the literature warns, but no
      loss on unseen data).
- [ ] Add features targeting soft faults: reverse-leakage slope, ESR tilt / loss tangent,
      diode knee sharpness. *Partly done 2026-11-27:* `off_slope` (reverse leakage) and
      `on_res` (forward series R) in `features.py`; ESR tilt and knee sharpness still open.
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
- [ ] (Later, owner's idea 2026-11-27) Rr chosen without a hand-moved jumper: relays, or a
      potentiometer whose actual value an ESP32 pin senses.
- [ ] (Later) A wider range: Rr 1 MΩ for the high side; a low amplitude or a current limit for
      the low side (an Rr below 220 Ω at ±4.66 V asks more current than the op-amp gives).
      Today parts outside |Z|/Rr 0.25–4 get OUT_OF_RANGE.

## Phase E — Optional / research
- [ ] 1D-CNN or Siamese network on the raw 360-point signature (this is where PyTorch
      finally enters). Compare against the Random Forest baseline.
