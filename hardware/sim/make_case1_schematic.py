#!/usr/bin/env python3
"""
make_case1_schematic.py — full Case 1 front-end schematic (OPA4134PA + DD1718PA), for review.

Renders hardware/sim/case1_schematic.svg and .png. Values are the ones actually on the board
(measured 2026-11-26, docs/CASE1_WIRING.md); nominal value first, measured in brackets.
Needs schemdraw (pip install schemdraw) — kept out of requirements.txt on purpose: this is a
documentation script, not part of the pipeline.

    python3 hardware/sim/make_case1_schematic.py
"""
from pathlib import Path

import schemdraw
import schemdraw.elements as elm

OUT = Path(__file__).resolve().parent / "case1_schematic"

GND = dict(lead=False)
BLUE, RED, GREEN, GRAY = "#1f4e9c", "#b3261e", "#1e7a34", "#555555"


def frame(d, x0, y0, x1, y1, title):
    d.add(elm.Line().at((x0, y0)).to((x1, y0)).color(GRAY).linestyle(":"))
    d.add(elm.Line().at((x1, y0)).to((x1, y1)).color(GRAY).linestyle(":"))
    d.add(elm.Line().at((x1, y1)).to((x0, y1)).color(GRAY).linestyle(":"))
    d.add(elm.Line().at((x0, y1)).to((x0, y0)).color(GRAY).linestyle(":"))
    d.add(elm.Label().at((x0 + 0.3, y0 - 0.45)).label(title, halign="left", fontsize=13, color=BLUE))


def text(d, xy, s, size=10, color="black", halign="left"):
    d.add(elm.Label().at(xy).label(s, halign=halign, valign="top", fontsize=size, color=color))


with schemdraw.Drawing(show=False) as d:
    d.config(fontsize=10, unit=2.2, lw=1.1)

    # ------------------------------------------------------------------ title
    text(d, (0, 4.2), "AI Electronic Components Tester (COE2026-15) — Case 1 analog front end", 18)
    text(d, (0, 3.2), "ESP32 DAC sine → ±10 V drive (U1A) → DUT → Rr → GND ;  node A / node B read by unity "
                      "followers (U1C/U1D) → dividers → ESP32 ADC (GPIO34/35).   "
                      "U1 = OPA4134PA (quad FET-input), rails ±15 V from DD1718PA.", 10.5, GRAY)
    text(d, (0, 2.5), "Component labels: nominal value (measured value on the built board, 2026-11-26).   "
                      "All GND symbols are one common node.", 10.5, GRAY)

    # ================================================================== 1. POWER
    frame(d, 0, 1.6, 21, -9.2, "1  Power: USB 5 V → ±15 V")
    d.add(elm.Label().at((0.6, -1.5)).label("ESP32 VIN\n(USB 5 V)", halign="left", fontsize=9))
    d.add(elm.Dot(open=True).at((2.4, -1.5)))
    d.add(elm.Line().at((2.4, -1.5)).right(1.0))
    d1 = d.add(elm.Diode().right().label("D1 1N5819\n(Schottky)", fontsize=9)
               .label("4.82 V", loc="bottom", ofst=(-1.6, -0.05), fontsize=8, color=GREEN))
    d.add(elm.Line().right(1.0).label("5V_D = 4.28 V", fontsize=8, color=GREEN))
    dd = d.add(elm.Ic(pins=[elm.IcPin(name="GND", side="left", slot="1/2", anchorname="GNDIN"),
                            elm.IcPin(name="VIN", side="left", slot="2/2", anchorname="VIN"),
                            elm.IcPin(name="−Vo", side="right", slot="1/3", anchorname="NVO"),
                            elm.IcPin(name="GND", side="right", slot="2/3", anchorname="GNDOUT"),
                            elm.IcPin(name="+Vo", side="right", slot="3/3", anchorname="PVO")],
                       size=(3.4, 4.0), anchor="VIN", lblsize=9)
               .label("DD1718PA (±15 V setting)\n400 kHz boost module", loc="bottom", fontsize=9))
    d.add(elm.Line().at(dd.GNDIN).left(0.8))
    d.add(elm.Ground(**GND))
    # +15 rail
    d.add(elm.Line().at(dd.PVO).right(2.5).color(RED))
    p15 = d.here
    d.add(elm.Line().right(5.8).color(RED))
    d.add(elm.Label().label("+15 V\n(+15.37 V)", halign="left", fontsize=10, color=RED))
    # mid GND
    d.add(elm.Line().at(dd.GNDOUT).right(1.2))
    d.add(elm.Ground(**GND))
    # -15 rail
    d.add(elm.Line().at(dd.NVO).right(2.5).color(BLUE))
    m15 = d.here
    d.add(elm.Line().right(5.8).color(BLUE))
    d.add(elm.Label().label("−15 V\n(−15.48 V)", halign="left", fontsize=10, color=BLUE))
    # bulk/HF caps at module output
    for k, (name, x) in enumerate((("C1", 0.6), ("E1", 2.0))):
        d.add(elm.Dot().at((p15[0] + x, p15[1])))
        d.add(elm.Capacitor().at((p15[0] + x, p15[1])).down(1.4)
              .label(f"{name}\n0.1µF", loc="bottom", fontsize=8))
        d.add(elm.Ground(**GND))
    for name, x in (("C2", 3.6), ("E2", 5.0)):
        d.add(elm.Dot().at((m15[0] + x, m15[1])))
        d.add(elm.Capacitor().at((m15[0] + x, m15[1])).up(1.0)
              .label(f"{name}\n0.1µF", loc="top", fontsize=8))
        d.add(elm.Ground(**GND).flip())
    # U1 supply pins
    d.add(elm.Label().at((0.6, -6.0)).label("U1 supply (decoupling at the pins):", halign="left", fontsize=9))
    d.add(elm.Label().at((0.6, -6.9)).label("+15 V", halign="left", fontsize=9, color=RED))
    d.add(elm.Line().at((2.0, -6.9)).right(2.0).color(RED))
    d.add(elm.Dot())
    d.add(elm.Line().right(1.4).color(RED).label("U1 pin 4 (V+)", loc="right", fontsize=9))
    d.add(elm.Capacitor().at((4.0, -6.9)).down(1.2).label("C3 0.1µF", loc="bottom", fontsize=8))
    d.add(elm.Ground(**GND))
    d.add(elm.Label().at((10.0, -6.9)).label("−15 V", halign="left", fontsize=9, color=BLUE))
    d.add(elm.Line().at((11.4, -6.9)).right(2.0).color(BLUE))
    d.add(elm.Dot())
    d.add(elm.Line().right(1.4).color(BLUE).label("U1 pin 11 (V−)", loc="right", fontsize=9))
    d.add(elm.Capacitor().at((13.4, -6.9)).down(1.2).label("C4 0.1µF", loc="bottom", fontsize=8))
    d.add(elm.Ground(**GND))
    text(d, (0.6, -8.3), "ESP32 GND → common GND.   E1–E4: 10 µF electrolytic in BOM, not on hand → 0.1 µF "
                         "(or omitted); E3/E4 sit beside C3/C4.", 8.5, GRAY)

    # ================================================================== 2. V_REF (U1B)
    frame(d, 22, 1.6, 40, -9.2, "2  V_REF 1.65 V buffer (U1B, pins 5/6/7)")
    d.add(elm.Label().at((23.0, -0.6)).label("ESP32 3V3 (3.321 V)", halign="left", fontsize=9, color=RED))
    d.add(elm.Line().at((25.0, -1.2)).down(0.4))
    d.add(elm.Resistor().down().label("R7 10k", loc="bottom", fontsize=9))
    vdiv = d.add(elm.Dot().label("VDIV 1.676 V", loc="left", fontsize=8, color=GREEN))
    d.add(elm.Resistor().down().label("R8 10k (10.08k)", loc="bottom", fontsize=9))
    d.add(elm.Ground(**GND))
    d.add(elm.Line().at((25.0, -0.95)).to((25.0, -1.2)))
    ub = d.add(elm.Opamp(leads=True).right().at((30.0, vdiv.center[1])).anchor("in2")
               .label("U1B", loc="center", fontsize=9))
    d.add(elm.Line().at(vdiv.center).to(ub.in2))
    d.add(elm.Label().at(ub.in2).label("5", ofst=(0.25, -0.25), fontsize=8))
    d.add(elm.Label().at(ub.in1).label("6", ofst=(0.25, 0.25), fontsize=8))
    d.add(elm.Label().at(ub.out).label("7", ofst=(-0.25, 0.25), fontsize=8))
    d.add(elm.Line().at(ub.out).right(1.0))
    vref = d.add(elm.Dot())
    d.add(elm.Line().right(2.2).label("V_REF\n1.676 V", loc="right", fontsize=9, color=GREEN))
    d.add(elm.Line().at(ub.in1).up(1.4))
    d.add(elm.Line().tox(vref.center))
    d.add(elm.Line().toy(vref.center))
    text(d, (23.0, -7.4), "Unity follower: pin 6 tied to pin 7.  V_REF → R2 (block 3).", 8.5, GRAY)

    # ================================================================== 3. DRIVE AMP (U1A)
    frame(d, 0, -10.2, 21, -24.0, "3  Drive amplifier (U1A, pins 1/2/3): difference amp, gain 5.92, inverting")
    d.add(elm.Label().at((0.6, -14.6)).label("ESP32\nGPIO25 (DAC)\n0–3.3 V sine", halign="left", fontsize=9))
    d.add(elm.Dot(open=True).at((3.6, -14.6)))
    d.add(elm.Resistor().right().label("R1 10k (10.05k)", fontsize=9))
    n2 = d.add(elm.Dot().label("N2", loc="bottom", fontsize=8))
    ua = d.add(elm.Opamp(leads=True).at((10.5, -14.6)).anchor("in1").label("U1A", loc="center", fontsize=9))
    d.add(elm.Line().at(n2.center).to(ua.in1))
    d.add(elm.Label().at(ua.in1).label("2", ofst=(0.25, 0.25), fontsize=8))
    d.add(elm.Label().at(ua.in2).label("3", ofst=(0.25, -0.2), fontsize=8))
    d.add(elm.Label().at(ua.out).label("1", ofst=(-0.25, 0.25), fontsize=8))
    # feedback R3 + R4 over the top
    d.add(elm.Line().at(n2.center).up(2.2))
    d.add(elm.Resistor().right(3.4).label("R3 51k (49.73k)", fontsize=9))
    d.add(elm.Dot().label("M1", loc="top", fontsize=8))
    d.add(elm.Resistor().right(3.4).label("R4 10k (9.80k)", fontsize=9))
    fb_end = d.here
    d.add(elm.Line().right(ua.out[0] + 1.0 - fb_end[0]))
    d.add(elm.Line().toy(ua.out))
    d.add(elm.Line().at(ua.out).right(1.0))
    nodeA = d.add(elm.Dot())
    d.add(elm.Line().right(2.0).label("node A\n±4.5 V now\n(±10 V max)", loc="right", fontsize=9, color=RED))
    # + input: R2 from V_REF, R5+R6 to GND
    d.add(elm.Label().at((0.6, -18.2)).label("V_REF (U1B pin 7)", halign="left", fontsize=9, color=GREEN))
    d.add(elm.Dot(open=True).at((3.6, -18.2)))
    d.add(elm.Resistor().right().label("R2 10k (10.21k)", fontsize=9))
    n3 = d.add(elm.Dot().label("N3", loc="left", ofst=(0, -0.3), fontsize=8))
    d.add(elm.Line().at(n3.center).toy(ua.in2))
    d.add(elm.Line().to(ua.in2))
    d.add(elm.Resistor().at(n3.center).down().label("R5 51k (50.28k)", loc="bottom", fontsize=9))
    d.add(elm.Dot().label("M2", loc="left", fontsize=8))
    d.add(elm.Resistor().down().label("R6 10k (10.20k)", loc="bottom", fontsize=9))
    d.add(elm.Ground(**GND))
    text(d, (11.0, -18.6), "V_A = (Rf/Rin)·(V_REF − V_DAC)\n"
                           "Rf1/R1 = 59.53k/10.05k = 5.923\n"
                           "Rf2/R2 = 60.48k/10.21k = 5.924  (matched)\n"
                           "DC, DAC = 128: pin 2 = 1.431 V, pin 3 = 1.430 V,\n"
                           "  node A = +0.27 V → firmware DAC_CENTER = 132\n"
                           "  (node A = +0.009 V)", 8.5, GRAY)

    # ================================================================== 4. DUT + Rr
    frame(d, 22, -10.2, 40, -24.0, "4  DUT and sense resistor Rr (jumper-selected)")
    d.add(elm.Label().at((23.0, -13.2)).label("node A\n(U1A pin 1)", halign="left", fontsize=9, color=RED))
    d.add(elm.Dot().at((26.0, -13.2)))
    d.add(elm.Line().right(1.0))
    d.add(elm.Dot(open=True).label("DUT +\n(anode)", loc="top", fontsize=8))
    d.add(elm.RBox().right(3.0).label("DUT", fontsize=10).color(RED))
    d.add(elm.Dot(open=True).label("DUT −", loc="top", fontsize=8))
    d.add(elm.Line().right(1.2))
    nb = d.add(elm.Dot().label("node B", loc="top", fontsize=9, color=BLUE))
    d.add(elm.Line().right(2.0).label("→ U1D pin 12", loc="right", fontsize=8))
    d.add(elm.Line().at(nb.center).down(1.6).label("JS", loc="left", fontsize=9))
    js = d.here
    xs = (js[0] - 3.0, js[0], js[0] + 3.0)
    for k, (x, name, val) in enumerate(zip(xs, ("Rr1", "Rr2", "Rr3"), ("1k (1.025k)", "10k (10.29k)", "100k (101.3k)"))):
        d.add(elm.Dot(open=True).at((x, js[1] - 0.9)).label(f"S{k + 1}", loc="right", fontsize=8))
        d.add(elm.Resistor().down(2.4).label(f"{name}\n{val}", loc="bottom", fontsize=8))
        d.add(elm.Ground(**GND))
    d.add(elm.Line().at(js).to((xs[0], js[1] - 0.9)).linestyle("--"))
    text(d, (23.0, -20.0), "JS = one jumper wire from node B to S1/S2/S3 (shown: Rr1).\n"
                           "V_DUT = V_A − V_B ,   I = V_B / Rr.   Rr = 100 Ω not fitted (DUT short at ±10 V\n"
                           "would draw 100 mA > OPA4134 ~35 mA limit).", 8.5, GRAY)

    # ================================================================== 5. RETURN PATH (U1C, U1D)
    frame(d, 0, -25.0, 40, -38.6, "5  Return path: unity followers + dividers → ESP32 ADC (U1C pins 8/9/10, U1D pins 12/13/14)")

    def channel(x0, y0, uname, pins, node, rin, rup, rdn, cap, pname, gpio, pval):
        d.add(elm.Label().at((x0, y0)).label(node, halign="left", fontsize=9,
                                             color=RED if "A" in node else BLUE))
        d.add(elm.Dot(open=True).at((x0 + 2.6, y0)))
        u = d.add(elm.Opamp(leads=True).right().at((x0 + 5.0, y0)).anchor("in2")
                  .label(uname, loc="center", fontsize=9))
        d.add(elm.Line().at((x0 + 2.6, y0)).to(u.in2))
        d.add(elm.Label().at(u.in2).label(pins[0], ofst=(0.25, -0.25), fontsize=8))
        d.add(elm.Label().at(u.in1).label(pins[1], ofst=(0.25, 0.25), fontsize=8))
        d.add(elm.Label().at(u.out).label(pins[2], ofst=(-0.25, 0.25), fontsize=8))
        d.add(elm.Line().at(u.out).right(0.8))
        o = d.add(elm.Dot())
        d.add(elm.Line().at(u.in1).up(1.2))
        d.add(elm.Line().tox(o.center))
        d.add(elm.Line().toy(o.center))
        d.add(elm.Resistor().at(o.center).right(3.2).label(rin, fontsize=9))
        p = d.add(elm.Dot().label(pname, loc="top", ofst=(0.5, 0), fontsize=9, color=GREEN))
        d.add(elm.Line().right(2.6))
        d.add(elm.Dot())
        d.add(elm.Line().right(2.0))
        d.add(elm.Dot(open=True).label(f"ESP32 {gpio}\n(ADC1)", loc="right", fontsize=9))
        d.add(elm.Resistor().at(p.center).up(2.2).label(rup, loc="bottom", fontsize=8))
        d.add(elm.Label().label("3V3", loc="top", fontsize=8, color=RED))
        d.add(elm.Resistor().at(p.center).down(2.2).label(rdn, loc="bottom", fontsize=8))
        d.add(elm.Ground(**GND))
        d.add(elm.Capacitor().at((p.center[0] + 2.6, p.center[1])).down(2.2)
              .label(cap, loc="bottom", fontsize=8))
        d.add(elm.Ground(**GND))
        text(d, (p.center[0] - 1.0, p.center[1] - 3.3), pval, 8, GREEN)

    channel(0.6, -30.6, "U1C", ("10", "9", "8"), "node A", "R9 100k", "R10 20k (19.38k)",
            "R11 20k (19.43k)", "C5 100pF\n(→1nF)", "P1", "GPIO34", "P1 = 1.508 V @ node A 0 V")
    channel(20.6, -30.6, "U1D", ("12", "13", "14"), "node B", "R12 100k (101k)", "R13 20k (19.48k)",
            "R14 20k (19.51k)", "C6 100pF\n(→1nF)", "P2", "GPIO35", "P2 = 1.509 V @ node B 0 V")
    text(d, (0.6, -36.6), "P = 1.515 V + 0.0882·V_node  (node ±10 V → 0.63–2.40 V; op-amp saturation ±13.5 V → "
                          "0.32–2.71 V, always inside the ADC's 0–3.3 V).   Followers: dividers don't load node B, "
                          "so I = V_B/Rr exactly.\n"
                          "22k in the original plan → 20k fitted (not on hand).   C5 = C6 always (equal V/I delay).   "
                          "ESP32 ADC reads ~0.17 V low → software zero-cal from a no-DUT capture (reader.py --zero).",
         8.5, GRAY)

    # ================================================================== notes
    text(d, (0, -39.3),
         "Pinout (TI SBOS058): 1 OUT A · 2 −IN A · 3 +IN A · 4 V+ · 5 +IN B · 6 −IN B · 7 OUT B · 8 OUT C · 9 −IN C · "
         "10 +IN C · 11 V− · 12 +IN D · 13 −IN D · 14 OUT D.     Firmware: case1_frontend (dual-core: core 0 DAC "
         "sine 50 Hz, core 1 ADC), DAC_CENTER 132, 63 counts → A ≈ 4.5 V.\n"
         "Bring-up 2026-11-26: every block passed its DC/AC check (docs/CASE1_WIRING.md).  First DUTs at Rr1: "
         "2k → fit 1978 Ω (verdict FAULTY: outside the 1k±20% training range);  2k‖2k → fit 996 Ω, verdict GOOD "
         "(type R, conf 0.58).  Open items: ≈2° V–I sampling skew, ADC noise (std 12.8 counts with 100 pF).",
         9, GRAY)

    d.save(str(OUT.with_suffix(".svg")), transparent=False)
    d.save(str(OUT.with_suffix(".png")), dpi=170, transparent=False)
print("wrote", OUT.with_suffix(".svg"), "and .png")
