# BOM.md — Case 1 analog front end (Dr. Wathis's ±10 V drive stage)

Decided in chat 2026-11-25, **built 2026-11-26/27**. This is the physical build: the advisor's
0–3.3 V → ±10 V drive stage, rebuilt with the parts we actually bought. Lists **only those
parts**; what the build changed is under the table.

> The NE5532 + ±9 V (MT3608 / ICL7660S) design in `docs/STANDALONE_TESTER_PLAN.md` is a
> *different, ±5 V* front end. We are **not** building that one with these parts. Keep that
> file as the alternative; don't mix the two BOMs.

---

## 1. Parts bought

| Part | Qty | Purpose |
|---|---|---|
| **OPA4134PA** (DIP-14, quad FET-input op-amp) | 1 (+1 spare recommended) | drive amp + return-path amp + V_REF buffer, all in one chip. Pinout: TI **OPA4134 datasheet (SBOS058)**, "Pin Configuration". Works on ±15 V. |
| **DD1718PA** dual-output module, **15 V variant** | 1 | USB 5 V (VIN 3.3–13 V) → **+15 V / −15 V** for the op-amp |
| Resistor **10 kΩ**, 1 % metal film | ~6 | input R (×2), V_REF divider (×2), feedback series (×2) |
| Resistor **51 kΩ**, 1 % metal film | 2 | feedback (51 k + 10 k ≈ 61 k per side) |
| Trimmer **100 kΩ**, multi-turn (VR1, VR2) | 2 | fine-tune gain to exactly ±10 V |
| Sense resistors **100 Ω / 1 k / 10 k / 100 kΩ**, 1 % | 1 each | current sense R_r (switchable range) |
| Capacitor **0.1 µF** ceramic | ≥4 | rail decoupling at each op-amp |
| Capacitor **10 µF** electrolytic | ≥4 | rail bulk decoupling — **optional, not on hand (2026-11-25)**: build uses 0.1 µF in the E1–E4 spots; add 10 µF (≥ 25 V rating) only if the step-6 noise check in `docs/CASE1_WIRING.md` fails |
| **1N5819** Schottky diode | 2–3 | reverse-protect the 5 V feed |
| IC socket, DIP-14 | 1–2 | make the OPA4134 swappable (don't solder it directly) |
| Breadboard + jumper wires | — | prototyping |

**As built (2026-11-26/27, every value in `docs/CASE1_WIRING.md`):**
- Rr positions are **220 Ω / 1k / 10k / 100k** (221.4 / 1022 / 10290 / 101300 Ω in circuit).
  100 Ω isn't fitted: a shorted DUT would ask more current than the op-amp gives.
- VR1/VR2 aren't fitted: the amplitude is set in firmware instead. The 10 µF caps aren't fitted
  either: 0.1 µF only, and the step-6 noise check (12.8 counts) came out in the "usable" band,
  below the level where they'd be added.
- Added parts not in the table: the return-path dividers (100 kΩ ×2, 20 kΩ ×4 — 22 kΩ was the
  plan), C5/C6 at the ADC pins (100 pF until the ordered 1 nF arrive), and the offset-reference
  divider on GPIO32 (20 kΩ ×2, 100 kΩ, 0.1 µF).

---

## 2. Gain and resistor values (why these give ±10 V)

- Difference amp around the op-amp: gain = R_f / R_in, with R_in = 10 kΩ.
- R_f = **51 kΩ + 10 kΩ in series ≈ 61 kΩ** → gain ≈ **6.1** → ESP32's ±1.65 V swing × 6.1 ≈ **±10.1 V**.
- Trim **VR (100 kΩ)** down slightly to land exactly on ±10 V.
- *As built:* no trimmer, and the gain measured **5.92** ((49.73k + 9.80k) / 10.05k), so a full
  ±1.65 V swing would give ±9.8 V. The firmware uses 63 DAC counts instead: A ≈ 4.66 V at node A.
- **Both feedback legs must match** (inverting + non-inverting side). Use 1 % metal film; if
  the two sides differ, the 0 V midpoint drifts (common-mode error).
- **V_REF = 1.65 V** from a 10 k / 10 k divider (half of 3.3 V), **buffered by one OPA4134
  channel** so it stays stiff.

---

## 3. Power wiring and cautions

- Feed **5 V** to DD1718PA **VIN** (USB 5 V or the USB boost — VIN must stay ≤ 13 V). Make
  sure the module is the **15 V variant**.
- Outputs: **+15 V / −15 V / GND** to the op-amp rails. The −15 V rail is rated only **120 mA**,
  but the op-amp draws a few mA, so it's fine.
- ⚠ **GND ต่อร่วมกันทั้งหมด** (DD1718PA + op-amp + ESP32) เป็นจุดเดียว ไม่งั้นสัญญาณอ้างอิงเพี้ยน.
- ⚠ โมดูลเป็น boost 400 kHz มี noise → ใส่ **0.1 µF + 10 µF คร่อม +15 V↔GND และ −15 V↔GND
  ติดใกล้ขา op-amp ทุกตัว** (ห้ามลืม — สำคัญต่อความสะอาดของ signature).
- ⚠ **วัด +15 V / −15 V ด้วยมิเตอร์ก่อนต่อ op-amp** (±4 % = 14.4–15.6 V ถือว่าปกติ).
- Put a **1N5819** in series on the 5 V feed to block reverse current.

---

## 4. Drive stage schematic (one OPA4134 channel)

```
                                   +15V ──┬─[0.1µF]─┬─[10µF]── GND
                                          │ (rail decoupling at the chip)
      R_in 10k                            │
ESP32 DAC ──/\/\──●───────────────┐    ┌──┴──┐
 (0–3.3V sine)    │                └────┤ −   │
                  │   R_f = 51k+10k ≈61k │     │
                  └────/\/\──[VR 100k]───┤     ├──●── V_out  (−10V … +10V) ── to DUT ──► R_r ──► GND
                                     ┌───┤ +   │        │                    (sense; measured on return path)
   V_REF 1.65V ──[buffer: 1 OPA4134]─┘   └──┬──┘        │
   (10k/10k divider off 3.3V)               │       V_DUT = V_out across DUT ; I = V(R_r)/R_r
                                   −15V ──┬──┴[0.1µF]─┬─[10µF]── GND
                                          (rail decoupling)
```

> ⚠ **This sketch is simplified and wrong as drawn** (found 2026-11-25): with V_REF wired
> straight to `+`, the output sits at **+1.65 V DC**, not 0 V. Build the full difference amp
> from §2 instead (V_REF → 10 k → `+`, and `+` → 51 k + 10 k → GND), plus a second return-path
> channel. Hole-by-hole wiring: `docs/CASE1_WIRING.md`.

(OPA4134PA is quad: use 1 channel for the drive amp, 1 for the V_REF buffer, and 2 for the
±10 V→0–3.3 V **return path**: unity followers on node A and node B, each into a divider. Pin
numbers are checked against the datasheet in `docs/CASE1_WIRING.md` §0.)

---

## 5. ⚠ Consequences of ±10 V (read before trusting results)

1. **The model is out-of-distribution at ±10 V for diodes/LED/Zener.** `synth.py` trains at
   **A = 4–6 V** (all components, since 2026-11-27). A diode knee sits at ~0.6 V regardless of
   amplitude, so after normalising by A the knee lands at 0.6/5 = 0.12 (training) vs 0.6/10 =
   0.06 (at ±10 V) — a different shape. **R, C, L are unaffected** (they scale with A, so the
   normalised loop is identical). The firmware therefore drives A ≈ 4.66 V, inside the training
   band. → Before raising the amplitude, **add A = 10 to the training set** (`docs/ROADMAP.md`
   Phase B).
2. ⚠ **LED reverse rating (~5 V).** At ±10 V the reverse half-cycle can exceed a typical LED's
   reverse breakdown. Add a series/clamp for LED tests, or test LEDs at a lower amplitude.
3. **Return path: built.** The ±10 V nodes must be scaled to **0–3.3 V** before the ESP32 ADC.
   As built, OPA4134 channels C/D follow node A / node B into 100k/20k/20k dividers: a node at
   ±10 V reads 0.63–2.40 V at the pin, and even a saturated op-amp (±13.5 V) stays inside
   0.32–2.71 V (`docs/CASE1_WIRING.md` §6, 3c).

---

## 6. Not included here (on purpose)

- MCP6002 / NE5532 / MT3608 / ICL7660S — those belong to the ±5 V alternative in
  `STANDALONE_TESTER_PLAN.md`, not this build.
