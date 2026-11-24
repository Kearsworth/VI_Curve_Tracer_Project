# BOM.md — Case 1 analog front end (Dr. Wathis's ±10 V drive stage)

Decided in chat 2026-11-25. This is the **physical build we are doing**: the advisor's
0–3.3 V → ±10 V drive stage, rebuilt with the parts we actually bought. Lists **only those
parts**.

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
| Capacitor **10 µF** electrolytic | ≥4 | rail bulk decoupling |
| **1N5819** Schottky diode | 2–3 | reverse-protect the 5 V feed |
| IC socket, DIP-14 | 1–2 | make the OPA4134 swappable (don't solder it directly) |
| Breadboard + jumper wires | — | prototyping |

---

## 2. Gain and resistor values (why these give ±10 V)

- Difference amp around the op-amp: gain = R_f / R_in, with R_in = 10 kΩ.
- R_f = **51 kΩ + 10 kΩ in series ≈ 61 kΩ** → gain ≈ **6.1** → ESP32's ±1.65 V swing × 6.1 ≈ **±10.1 V**.
- Trim **VR (100 kΩ)** down slightly to land exactly on ±10 V.
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

(OPA4134PA is quad: use 1 channel for the drive amp, 1 for the V_REF buffer, and 1 for the
±10 V→0–3.3 V **return path** amp in section 5. Confirm channel pin numbers in the OPA4134
datasheet before wiring.)

---

## 5. ⚠ Consequences of ±10 V (read before trusting results)

1. **The model is out-of-distribution at ±10 V for diodes/LED/Zener.** `synth.py` trains at
   **A = 5 V** (R/C/L/D/LED; Zener uses A = 6 V). A diode knee sits at ~0.6 V regardless of amplitude, so after normalising by A
   the knee lands at 0.6/5 = 0.12 (training) vs 0.6/10 = 0.06 (at ±10 V) — a different shape.
   **R, C, L are unaffected** (they scale with A, so the normalised loop is identical).
   → Before trusting diode/LED/Zener verdicts, **retrain `synth.py` with A = 10** (or add
   A = 10 to the training set). This belongs in `docs/ROADMAP.md` Phase B.
2. ⚠ **LED reverse rating (~5 V).** At ±10 V the reverse half-cycle can exceed a typical LED's
   reverse breakdown. Add a series/clamp for LED tests, or test LEDs at a lower amplitude.
3. **Return path still required.** The ±10 V DUT response must be scaled to **0–3.3 V** before
   the ESP32 ADC (one OPA4134 channel + resistor divider, or a divider + 3.3 V Zener clamp).
   This is the project's existing open item — see `firmware/esp32/README.md` and
   `docs/ROADMAP.md` Phase A (return-path gain still unconfirmed).

---

## 6. Not included here (on purpose)

- MCP6002 / NE5532 / MT3608 / ICL7660S — those belong to the ±5 V alternative in
  `STANDALONE_TESTER_PLAN.md`, not this build.
