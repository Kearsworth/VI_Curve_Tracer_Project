# Standalone tester plan (drafted 2026-10-10)

> **Status update 2026-11-25: alternative, not being built.** This is the ±5 V front end
> (NE5532 + MT3608/ICL7660S ±9 V rails). The physical build went the **Case 1** way instead:
> Dr. Wathis's ±10 V drive stage with an OPA4134PA on DD1718PA ±15 V rails — see
> `docs/BOM.md`. Keep this file as the ±5 V option; don't mix its BOM with Case 1's.
> Two of its software stages were done for Case 1 instead (2026-11-27): Stage 2's burst DMA
> capture with a frequency command (`case1_frontend_1k`, `case1_frontend_mf`), and Stage 3's
> training over selectable Rr and frequency with auto-range (`synth.py`, `hardware/autorange.py`).

Goal: a **real-use, standalone** V-I tester. One USB 5 V cable powers everything, the
ESP32 drives the DUT itself, and the test settings (sense resistor Rr, drive frequency,
amplitude) are selectable by the ESP32 — the same idea as commercial analog signature
analyzers, sized for a student budget.

Status: **Stage 0 (simulation) done 2026-10-10 — nothing built or measured on hardware yet.**
Values below are the ones that passed `hardware/sim/stage0_check.py` (ngspice); several changed
from the first paper design, see "Stage 0 result". This is our own front end; it runs alongside
Dr. Wathis's confirmed ±10 V drive stage, not as a silent replacement — tell him before
committing to it.

## Why these targets

| Setting | Commercial reference | Our target | Reason |
|---|---|---|---|
| Drive amplitude | Huntron Tracker 2800: 200 mV–20 V (5 V is one preset); EyePoint u2x: 1.2/3.3/5/12 V | **±5 V peak** | `synth.py` trains at A = 5 V; safe for LED reverse rating (~5 V); covers R, C, L, D, LED, 3.3 V Zener |
| Source/sense resistance | Huntron: 10 Ω–100 kΩ, 9 steps | **4 steps: 220 Ω, 1 kΩ, 10 kΩ, 100 kΩ** | Signature shape depends on Rr/|Z_DUT|; 220 Ω floor keeps peak current ≤ ~23 mA (op-amp limit) |
| Frequency | Huntron: 20 Hz–2 kHz, 6 steps | **50, 200, 1000 Hz** (firmware only) | C/L need ~1 kHz (100 nF ≈ 1.6 kΩ at 1 kHz; ≈ 32 kΩ "open" at 50 Hz) |

Sources: Huntron Tracker 2800 datasheet, EyePoint u21/u22 brochures (see chat log 2026-10-10).

Out of scope for v1: Zener > ~4.5 V, electrolytic capacitors (AC reverse-biases them),
in-circuit testing (needs the low 200 mV range so semiconductors stay off).

## Architecture (v1)

```
USB 5V ─► MT3608 boost ─► +9V ─► ICL7660S ─► −9V      (all from the one USB cable)
                          │                    │
ESP32 DAC1 ─► NE5532 (×3.7, ±9V) ─► node A ─► DUT ─► node B ─► [Rr bank: 220/1k/10k/100k] ─► GND
                                    │                 │          selected by ESP32 via relays
                                    ▼                 ▼
                           return path ch1     return path ch2   (3-resistor divider + 1 nF, ±5V → ~0.20–2.38 V)
                                    │                 │
                                 GPIO34            GPIO35   (ADC1, DMA continuous mode)
V_DUT = V_A − V_B,  I = V_B / Rr
```

Design notes:
- DUT stays ground-referenced (same topology as the advisor's stage), so the existing
  2-channel frame, `reader.py` and the ML pipeline carry over.
- **Rr switching: one 5 V reed relay per resistor, each driven by an NPN transistor from an
  ESP32 GPIO** (decided 2026-10-10). Why not the alternatives:
  - CD4066 on ±9 V rails needs a logic-high ~3.6 V above ground (70 % of the 18 V span from
    VSS), which a 3.3 V GPIO can't reach without level shifting, and adds ~100 Ω on-resistance.
  - Common 5 V relay *modules* are usually active-LOW with the opto LED pulled to 5 V: a 3.3 V
    GPIO "high" leaves ~1.7 V across the LED, so the relay may not release. Only usable if the
    module explicitly supports 3.3 V / high-level trigger.
  - Reed relay (e.g. SIP-1A05): ~10 mA coil, contacts ~0.1 Ω, sealed — suited to small signals;
    GPIO → 1 kΩ → NPN base, coil to 5 V, 1N4148 flyback diode across each coil.
  - GPIOs: **16, 17, 18, 19** (output-capable, not strapping pins, not ADC1/DAC pins).
  - Firmware rule: break-before-make — all relays off, wait ~5 ms, then the new one on; never
    two at once. With none on, node B just floats to the return-path bias (harmless).
  - Stage 1 can start with a jumper wire in place of the relays; the relays only make it
    software-selectable.
- **Auto-range rule (Stage 3, recorded now):** capture at 1 kΩ, estimate |Z| = V_DUT,pk / I_pk,
  pick the bank value nearest |Z| on a log scale, never with Rr/|Z| > 20 (Stage 0 showed those
  signatures degenerate). Diode/LED-like signatures (low `symmetry`) stay at 1 kΩ. Every
  capture records the Rr actually used (`raw['Rr']`), measured with a multimeter once, not the
  nominal value.
- Drive: DAC sine 128 ± 104 counts (levelled so A = 5.0 V), 1 µF AC coupling + 100 kΩ to GND
  (τ = 0.1 s, settles ~0.5 s after power-up), non-inverting gain 1 + 27k/10k = 3.7.
- Return path per channel: Vin–100 kΩ–node, node–56 kΩ–3.3 V, node–56 kΩ–GND, 1 nF at the
  pin. Gain ≈ 0.219, 0 V → ≈ 1.29 V, so ±5 V lands in **0.20–2.38 V** — inside the ESP32 ADC's
  accurate window (~150–2450 mV at 11/12 dB attenuation, per Espressif), not just 0–3.3 V.
  The 100 kΩ limits fault current into the pin to µA. `reader.py` needs `ChannelCal` from
  measured gain/offset.
- **Current needs a loading correction:** the return path draws a little current from node B
  (Thevenin 1.65 V behind 128 kΩ), so I = V_B/Rr alone is off by up to ~100 % at Rr = 100 kΩ.
  Software must use `I = V_B/Rr + (V_B − 1.65)/128k` (values from measurement, since 5 %
  resistors are used); in simulation this brings the error to ≤ 0.3 % of 5 V/Rr.

## Stages

### Stage 0 — Simulate before buying — DONE 2026-10-10 (simulation only)
- Falstad / LTspice model of: boost + charge pump rails, drive amp, Rr bank, both return paths.
- Check: ±5 V at node A with headroom on ±9 V rails, return-path outputs stay in 0–3.3 V for
  every Rr including DUT open/short, op-amp current at Rr = 220 Ω with DUT shorted.
- **Done when:** every node is inside its limit in every Rr × {open, short, R, D, LED} case.
- **Result:** `python3 hardware/sim/stage0_check.py` → all 28 cases (7 DUTs × 4 Rr) pass:
  node A = 4.98 V peak, both ADC pins within 0.20–2.38 V, peak op-amp current 22.7 mA (DUT
  shorted at Rr = 220 Ω, under the ~30 mA limit), corrected current error ≤ 0.3 %. Two
  impedance-mismatched settings (C 100 nF and L 100 mH at Rr = 100 kΩ, Rr/|Z| = 63 and 159)
  give a degenerate signature and are excluded — auto-range must never select Rr/|Z| > 20.
  Interactive model: `hardware/sim/standalone_frontend.falstad.txt` (regenerate with
  `make_falstad.py`; share link in the `.url` file).
- **Cross-checked in Falstad** (`hardware/sim/falstad_measure.js`, headless Chrome driving
  CircuitJS): R 1k, diode, LED at Rr 1 kΩ, short at 220 Ω, R 1k at 100 kΩ, C 100 nF at 1 kHz —
  ADC pins 0.18–2.36 V, currents within 0.1 mA of ngspice (e.g. short/220 Ω: 23.0 vs 22.7 mA).
  Falstad shows a ~0.09 V offset at node A because it only ran ~2 cycles of the 0.1 s
  coupling time constant; ngspice was settled for 0.5 s.
- Changes vs. the first paper design, all found here: gain 4.0 → 3.7 with DAC levelling
  (4.0 overshot to ~5.27 V); return path re-centred from 0–3.3 V to the ADC's accurate
  150–2450 mV window (62k/150k → 56k/56k); coupling cap 10 µF → 1 µF (settle 5 s → 0.5 s);
  added the return-path loading correction.
- Not modeled: the MT3608/ICL7660S rails (ideal ±9 V, op-amp clamp ±7.5 V), op-amp output
  impedance, ADC sampling-cap kickback. Breadboard measurements in Stage 1 are the real check.

### Stage 1 — Analog front end on breadboard (≈ 1–2 weeks after parts arrive)
Ready before parts arrive (2026-10-11, not yet run on hardware): hole-by-hole layout
`hardware/sim/stage1_breadboard.svg` (generated by `make_breadboard.py`, no hole clashes),
firmware `firmware/esp32/standalone/stage1_frontend/` (compiles; DAC 104 counts → A ≈ 5.0 V),
and `hardware/reader.py --frontend --rr <ohm>` (pin → node conversion, V_DUT = V_A − V_B,
loading-corrected current, measured A; covered by `tests/test_reader.py`).
1. Rails alone: measure +9 V / −9 V under load.
2. Drive amp: ±5 V sine at node A (multimeter AC ≈ 3.5 V RMS), no DUT.
3. Return paths **disconnected from the ESP32**: measure 0–3.3 V range with DUT open and shorted.
4. Connect to GPIO34/35; first DUT = 1 kΩ at Rr = 1 kΩ, 50 Hz (expect a 45° line).
5. Fold in the pending **ADC decision experiment** (`loopback/adc_step` + `hardware/adc_check.py`):
   if the internal ADC misses the ≈ 2-count budget, decide internal-with-calibration vs.
   external ADC before Stage 2.
- **Done when:** R, D, LED signatures at 50 Hz look right through `reader.py → verify`.

### Stage 2 — Firmware v2: settings + fast capture
- Drive: DAC from a hardware path (`dac_continuous` DMA or `dac_cosine`, both in the
  installed core 3.3.2 / IDF 5.5) so 1 kHz is clean without the busy loop.
- Capture: `analogContinuous()` (ADC1 DMA, both channels) instead of blocking `analogRead()`.
  Target ≥ 30 samples/cycle at 1 kHz → ≥ 30 kS/s per channel.
- **Burst capture, not streaming:** at 1 kHz even a 4-byte binary sample (2 ch × 2 B) needs
  ~120 kB/s, above 921600 baud's ~92 kB/s. Capture N cycles into RAM, then send. Needs a new
  versioned frame (keep the CSV path for 50 Hz) — `reader.py` gains a parser for it.
- Serial command protocol: `SET RR <ohm>`, `SET F <hz>`, `SET AMP <counts>`, `CAPTURE <cycles>`;
  every capture's meta line carries the actual Rr, f and DAC amplitude.
- Measured A: from channel A's amplitude, and an amplitude-leveling loop to hit A = 5.0 V ±1–2 %
  (already a ROADMAP item).
- **Done when:** 1 kHz captures of 100 nF film cap and 100 mH inductor show the correct
  ellipse direction (C clockwise, L counter-clockwise).

### Stage 3 — ML for selectable settings
- Today's model is trained on one fixed (Rr, f) per component; a signature at any other
  setting is out of distribution. *(True on 2026-10-10; done for Case 1 on 2026-11-27, see the
  status note at the top.)* Extend `synth.py` to sample Rr ∈ {220, 1k, 10k, 100k} and
  f ∈ {50, 200, 1000} and a range of component values; pass Rr and f into the features
  (or train per-setting models). Keep the golden rule: one `calibrate`/`features` path for
  training and inference.
- **Auto-range:** ESP32/PC tries settings and keeps the one where the signature is most
  informative (line near 45°, ellipse aspect near 1) — the procedure commercial users do by hand.
- Also on this stage: the RF vs SVM/ANN benchmark on soft faults (ROADMAP Phase C).
- **Done when:** synthetic accuracy is re-reported per setting, and auto-range picks the
  expected setting for each test part.

### Stage 4 — Real data and validation (= ROADMAP Phase B)
- Capture good and deliberately faulty R, C, L, D, LED at the auto-ranged settings; record
  each part's true value (multimeter / LCR) and fault.
- Evaluate the synthetic-trained model on real data first, then retrain on synthetic + real.

### Stage 5 — Usable product
- Probe / DUT socket, enclosure, PC UI (live signature + verdict + chosen settings), reuse
  `verify.verify(raw)` as the backend.

## Bill of materials (v1, paper estimate)

| Part | Qty | Purpose |
|---|---|---|
| MT3608 boost module | 1 | 5 V → +9 V |
| ICL7660**S** (DIP-8) | 1 | +9 V → −9 V (the S version accepts up to 12 V in) |
| NE5532P | 1–2 | Drive amplifier, ±5 V out (TL072 is weaker at 20+ mA loads) |
| 5 V reed relay (SIP-1A05 or similar) + NPN (2N2222A/BC547) + 1 kΩ base resistor + 1N4148 flyback, per Rr | 4 sets | ESP32-selected Rr (GPIO 16–19) |
| Resistors (5 % is fine — calibrated in software): 220 Ω, 1 kΩ, 10 kΩ, 100 kΩ (Rr bank); 10 k + 27 k (gain); 100 k ×3 (input bias + return paths), 56 k ×4 (return paths) | — | Gain, Rr, return path |
| Capacitors: 10 µF ×3 (charge pump + rail bulk), 1 µF film/ceramic ×1 (coupling), 100 nF ×6, 1 nF ×2 | — | Charge pump, coupling, decoupling, ADC pin |
| Test DUTs: 1 k / 10 k resistors, 1N4148, red LED, 100 nF film cap, 100 mH inductor | — | Validation |

## Open questions
- Does the advisor want this front end, or should Stage 1 wait for the return path of his
  ±10 V stage? (Either way Stages 2–3 are needed.)
- Exact relay module: confirm its input works from a 3.3 V GPIO before buying.
- 1 kHz DMA ADC sample rate and noise on the classic ESP32 — measure in Stage 2.
