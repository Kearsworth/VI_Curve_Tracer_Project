"""
make_case1_breadboard.py — Case 1 breadboard layout (docs/BOM.md, docs/CASE1_WIRING.md):
Dr. Wathis's ±10 V drive stage on one OPA4134PA, ±15 V from a DD1718PA module.

Generated from one parts list, then CHECKED against the intended netlist (union-find over
breadboard strips, rails and wires): every IC pin and every part lead must land on the net
the schematic says, and no two different nets may touch. Same drawing style as
make_breadboard.py (Stage 1, ±5 V alternative).

Run:  python3 hardware/sim/make_case1_breadboard.py
      -> hardware/sim/case1_breadboard.svg + .json, prints the check result

Board: one 830-point breadboard, rows 1-63, columns a-e / f-j.
  top rails (next to j):    TRn = −15 V  <- tape-label it!     TRg = GND
  bottom rails (next to a): BRg = GND                          BRp = +15 V
OPA4134PA (DIP-14) at rows 20-26, notch toward row 19: pins 1-7 in column e (rows 20-26),
pins 14-8 in column f (rows 20-26). So V+ (pin 4) = e23 next to the +15 rail and
V− (pin 11) = f23 next to the −15 rail.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
RAILS = ("TRn", "TRg", "BRg", "BRp")

# ------------------------------------------------------------------ parts
IC_ROW0 = 20
IC = ("U1", IC_ROW0, "OPA4134PA",
      ["OUT A", "−IN A", "+IN A", "V+", "+IN B", "−IN B", "OUT B",
       "OUT C", "−IN C", "+IN C", "V−", "+IN D", "−IN D", "OUT D"])


def pin_hole(p):
    """Hole of OPA4134 pin p (1..14)."""
    return ("e", IC_ROW0 + p - 1) if p <= 7 else ("f", IC_ROW0 + 14 - p)


# kind: wire | jumper | res | cap | ecap (first end = +) | diode (first end = anode) | dut
# (id, kind, end1, end2, label, colour-or-value, expected net at end1, expected net at end2)
PARTS = [
    # --- power entry: 5 V from ESP32 VIN -> 1N5819 -> DD1718PA VIN (module itself is off-board)
    ("D1", "diode", ("b", 3), ("b", 7), "1N5819: แถบ (cathode) ไปทาง row 7", "1N5819", "5V_IN", "5V_MOD"),
    ("W1", "wire", ("TRg", 2), ("BRg", 2), "GND บน ↔ GND ล่าง", "black", "GND", "GND"),
    ("W2", "wire", ("TRg", 60), ("BRg", 60), "GND บน ↔ GND ล่าง (ปลายขวา)", "black", "GND", "GND"),
    ("E1", "ecap", ("BRp", 9), ("BRg", 9), "10 µF ที่ทางเข้า +15 V: ขา + ที่ +15", "10µF", "+15", "GND"),
    ("E2", "ecap", ("TRg", 9), ("TRn", 9), "10 µF ที่ทางเข้า −15 V: ขา + ที่ GND!", "10µF", "GND", "-15"),
    ("C1", "cap", ("BRp", 11), ("BRg", 11), "100 nF ที่ทางเข้า +15 V", "100nF", "+15", "GND"),
    ("C2", "cap", ("TRg", 11), ("TRn", 11), "100 nF ที่ทางเข้า −15 V", "100nF", "GND", "-15"),
    # --- OPA4134 supply pins + decoupling right at the chip
    ("W3", "wire", ("d", 23), ("BRp", 23), "pin 4 (V+) → +15 V", "red", "+15", "+15"),
    ("C3", "cap", ("c", 23), ("c", 27), "100 nF pin 4 → GND strip row 27 (ชิดขา)", "100nF", "+15", "GND"),
    ("W13", "wire", ("d", 27), ("BRg", 27), "row 27 ล่าง → GND (จุด GND ของ C3)", "black", "GND", "GND"),
    ("E3", "ecap", ("BRp", 25), ("BRg", 25), "10 µF ใกล้ชิป +15 V", "10µF", "+15", "GND"),
    ("W4", "wire", ("j", 23), ("TRn", 23), "pin 11 (V−) → −15 V", "purple", "-15", "-15"),
    ("C4", "cap", ("i", 23), ("TRg", 22), "100 nF pin 11 → GND (ชิดขา)", "100nF", "-15", "GND"),
    ("E4", "ecap", ("TRg", 25), ("TRn", 25), "10 µF ใกล้ชิป −15 V: ขา + ที่ GND!", "10µF", "GND", "-15"),
    # --- channel B: V_REF = 1.65 V (10k/10k off ESP32 3V3), buffered
    ("R7", "res", ("f", 33), ("f", 37), "10 kΩ 3V3 → VREF_DIV (row 37 บน)", "10k", "3V3", "VREF_DIV"),
    ("R8", "res", ("j", 37), ("TRg", 37), "10 kΩ VREF_DIV → GND", "10k", "VREF_DIV", "GND"),
    ("W5", "wire", ("g", 37), ("d", 24), "VREF_DIV → pin 5 (+IN B)", "orange", "VREF_DIV", "VREF_DIV"),
    ("W6", "wire", ("d", 25), ("d", 26), "pin 6 ↔ pin 7 (follower)", "gray", "VREF", "VREF"),
    # --- channel A: difference amp, Vout = 6.1 × (V_REF − V_DAC)
    ("R1", "res", ("a", 15), ("a", 21), "Rin1 10 kΩ DAC → pin 2 (−IN A)", "10k", "DAC", "INV_A"),
    ("R3", "res", ("b", 21), ("b", 17), "Rf1a 51 kΩ pin 2 → M1", "51k", "INV_A", "M1"),
    ("R4", "res", ("c", 17), ("c", 20), "Rf1b 10 kΩ M1 → pin 1 (OUT A)", "10k", "M1", "NODE_A"),
    ("R2", "res", ("b", 26), ("b", 22), "Rin2 10 kΩ V_REF (pin 7) → pin 3 (+IN A)", "10k", "VREF", "NINV_A"),
    ("R5", "res", ("a", 22), ("a", 28), "Rf2a 51 kΩ pin 3 → M2 (row 28)", "51k", "NINV_A", "M2"),
    ("R6", "res", ("c", 28), ("BRg", 28), "Rf2b 10 kΩ M2 → GND", "10k", "M2", "GND"),
    # --- node A / DUT / node B / Rr
    ("W7", "wire", ("d", 20), ("f", 40), "OUT A (pin 1) → node A (row 40 บน)", "orange", "NODE_A", "NODE_A"),
    ("W8", "wire", ("g", 40), ("h", 24), "node A → pin 10 (+IN C)", "orange", "NODE_A", "NODE_A"),
    ("DUT", "dut", ("i", 40), ("i", 44), "DUT: ขาบวก/anode ที่ row 40", "DUT", "NODE_A", "NODE_B"),
    ("W9", "wire", ("g", 44), ("g", 22), "node B → pin 12 (+IN D)", "green", "NODE_B", "NODE_B"),
    ("JS", "jumper", ("h", 44), ("f", 50), "สายเลือก Rr (ตอนนี้ 1 kΩ) ย้ายไป f52 / f54", "green", "NODE_B", "NODE_B"),
    ("Rr1", "res", ("j", 50), ("TRg", 50), "Rr 1 kΩ (เลือกอยู่: ต่อกับ node B ผ่าน JS)", "1k", "NODE_B", "GND"),
    ("Rr2", "res", ("j", 52), ("TRg", 52), "Rr 10 kΩ", "10k", "RR_10K", "GND"),
    ("Rr3", "res", ("j", 54), ("TRg", 54), "Rr 100 kΩ", "100k", "RR_100K", "GND"),
    # --- channels C/D: unity followers (FET input: no load on node A/B)
    ("W10", "wire", ("g", 25), ("g", 26), "pin 9 ↔ pin 8 (follower C)", "gray", "BUF_A", "BUF_A"),
    ("W11", "wire", ("g", 21), ("g", 20), "pin 13 ↔ pin 14 (follower D)", "gray", "BUF_B", "BUF_B"),
    # --- return path A: BUF_A -> 100k -> P1, P1 -22k- 3V3, P1 -22k- GND, 1 nF; P1 -> GPIO34
    ("R9", "res", ("h", 26), ("h", 30), "100 kΩ OUT C (pin 8) → P1", "100k", "BUF_A", "P1"),
    ("R10", "res", ("g", 33), ("g", 30), "22 kΩ 3V3 → P1", "22k", "3V3", "P1"),
    ("R11", "res", ("i", 30), ("TRg", 30), "22 kΩ P1 → GND", "22k", "P1", "GND"),
    ("C5", "cap", ("j", 30), ("TRg", 31), "1 nF P1 → GND", "1nF", "P1", "GND"),
    # --- return path B: BUF_B -> 100k -> P2, same divider; P2 -> GPIO35
    ("W12", "wire", ("i", 33), ("j", 13), "3V3 → row 13 บน", "orange", "3V3", "3V3"),
    ("R12", "res", ("h", 20), ("h", 16), "100 kΩ OUT D (pin 14) → P2", "100k", "BUF_B", "P2"),
    ("R13", "res", ("g", 13), ("g", 16), "22 kΩ 3V3 → P2", "22k", "3V3", "P2"),
    ("R14", "res", ("i", 16), ("TRg", 16), "22 kΩ P2 → GND", "22k", "P2", "GND"),
    ("C6", "cap", ("j", 16), ("TRg", 17), "1 nF P2 → GND", "1nF", "P2", "GND"),
]

# Wires that leave the board: (hole, text, net). GPIO34/35 go in LAST (docs/CASE1_WIRING.md step 6).
OFFBOARD = [
    (("a", 3), "ESP32 VIN (5V จาก USB)", "5V_IN"),
    (("a", 7), "DD1718PA VIN", "5V_MOD"),
    (("BRg", 4), "DD1718PA GND", "GND"),
    (("BRp", 5), "DD1718PA +Vo (+15V)", "+15"),
    (("TRn", 5), "DD1718PA −Vo (−15V)", "-15"),
    (("BRg", 13), "ESP32 GND", "GND"),
    (("e", 15), "ESP32 GPIO25 (DAC)", "DAC"),
    (("j", 33), "ESP32 3V3", "3V3"),
    (("f", 30), "ESP32 GPIO34 — ต่อเป็นอย่างสุดท้าย", "P1"),
    (("f", 16), "ESP32 GPIO35 — ต่อเป็นอย่างสุดท้าย", "P2"),
]

PIN_NETS = {1: "NODE_A", 2: "INV_A", 3: "NINV_A", 4: "+15", 5: "VREF_DIV", 6: "VREF", 7: "VREF",
            8: "BUF_A", 9: "BUF_A", 10: "NODE_A", 11: "-15", 12: "NODE_B", 13: "BUF_B", 14: "BUF_B"}
RAIL_NETS = {"TRn": "-15", "TRg": "GND", "BRg": "GND", "BRp": "+15"}
# nets that exist only when the Rr jumper picks them
OPTIONAL = {"RR_10K", "RR_100K"}

# ------------------------------------------------------------------ checks


def node(h):
    """Electrical node of a hole before wires: a rail, or one 5-hole strip."""
    col, row = h
    if col in RAILS:
        return col
    return (row, "top" if col in "fghij" else "bottom")


def check():
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    for pid, kind, a, b, *_ in PARTS:
        if kind in ("wire", "jumper"):
            union(node(a), node(b))

    # every hole's expected net, from the parts list, IC pins, offboard and rails
    claims = {}
    for pid, kind, a, b, _, _, na, nb in PARTS:
        claims.setdefault(find(node(a)), set()).add(na)
        claims.setdefault(find(node(b)), set()).add(nb)
    for p, net in PIN_NETS.items():
        claims.setdefault(find(node(pin_hole(p))), set()).add(net)
    for h, _, net in OFFBOARD:
        claims.setdefault(find(node(h)), set()).add(net)
    for r, net in RAIL_NETS.items():
        claims.setdefault(find(r), set()).add(net)

    errors = []
    for grp, nets in claims.items():
        if len(nets) > 1:
            errors.append(f"short: nets {sorted(nets)} are connected together")
    owners = {}
    for grp, nets in claims.items():
        for n in nets:
            owners.setdefault(n, set()).add(grp)
    for n, grps in owners.items():
        if len(grps) > 1:
            errors.append(f"open: net {n} is split into {len(grps)} unconnected pieces")

    # every connected component needs at least 2 element terminals (else a lead goes nowhere)
    terms = {}
    for pid, kind, a, b, *_ in PARTS:
        if kind not in ("wire", "jumper"):
            terms.setdefault(find(node(a)), []).append(pid)
            terms.setdefault(find(node(b)), []).append(pid)
    for p in PIN_NETS:
        terms.setdefault(find(node(pin_hole(p))), []).append(f"U1.{p}")
    for h, text, _ in OFFBOARD:
        terms.setdefault(find(node(h)), []).append("off")
    for grp, t in terms.items():
        nets = claims.get(grp, {"?"})
        if len(t) < 2 and not (nets & OPTIONAL) and not isinstance(grp, str):
            errors.append(f"dangling: {t} alone on net {sorted(nets)}")

    # no hole used twice (rails excepted); at most 5 holes per strip
    used = {}
    for pid, kind, a, b, *_ in PARTS:
        for h in (a, b):
            if h[0] not in RAILS:
                used.setdefault(h, []).append(pid)
    for p in range(1, 15):
        used.setdefault(pin_hole(p), []).append(f"U1.{p}")
    for h, *_ in OFFBOARD:
        if h[0] not in RAILS:
            used.setdefault(h, []).append("off")
    for h, v in used.items():
        if len(v) > 1:
            errors.append(f"hole {h[0]}{h[1]} used by {v}")
    flat = [(pid, a[0], min(a[1], b[1]), max(a[1], b[1])) for pid, kind, a, b, *_ in PARTS
            if kind not in ("wire", "jumper") and a[0] == b[0] and a[0] not in RAILS]
    for i, (p1, line1, lo1, hi1) in enumerate(flat):
        for p2, line2, lo2, hi2 in flat[i + 1:]:
            if line1 == line2 and lo1 < hi2 and lo2 < hi1:
                errors.append(f"{p1} and {p2} lie on top of each other along line {line1}")
        for (col, row), who in used.items():
            if col == line1 and lo1 < row < hi1:
                errors.append(f"hole {col}{row} ({who}) is under the body of {p1}")
    rail_used = {}
    for pid, kind, a, b, *_ in PARTS:
        for h in (a, b):
            if h[0] in RAILS:
                rail_used.setdefault(h, []).append(pid)
    for h, *_ in OFFBOARD:
        if h[0] in RAILS:
            rail_used.setdefault(h, []).append("off")
    for h, v in rail_used.items():
        if len(v) > 1:
            errors.append(f"rail hole {h[0]} {h[1]} used by {v}")
    return errors


# ------------------------------------------------------------------ drawing
STEP = 16
X0 = 56
Y = {"TRn": 40, "TRg": 56, "j": 92, "i": 108, "h": 124, "g": 140, "f": 156,
     "e": 188, "d": 204, "c": 220, "b": 236, "a": 252, "BRg": 288, "BRp": 304}
W, H = X0 + 62 * STEP + 56, 340
COL = {"red": "#D62828", "black": "#222", "purple": "#7B2CBF", "gray": "#888",
       "orange": "#E07A00", "green": "#2B9348"}
FILL = {"res": "#8B5E34", "cap": "#C77D00", "ecap": "#1D4E89", "diode": "#444", "dut": "#D62828"}


def xy(h):
    col, row = h
    return X0 + (row - 1) * STEP, Y[col]


def svg():
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
         f'font-family="IBM Plex Mono, monospace" font-size="9">']
    o.append(f'<rect x="8" y="8" width="{W-16}" height="{H-16}" rx="10" fill="#F4F1EA" stroke="#CFC8BC"/>')
    for name, key, c in [("−15V", "TRn", "#7B2CBF"), ("GND", "TRg", "#2F5DA8"),
                         ("GND", "BRg", "#2F5DA8"), ("+15V", "BRp", "#D62828")]:
        y = Y[key]
        o.append(f'<line x1="{X0-8}" y1="{y}" x2="{X0+62*STEP+8}" y2="{y}" stroke="{c}" stroke-width="1.2" opacity=".55"/>')
        o.append(f'<text x="14" y="{y+3}" fill="{c}" font-weight="600">{name}</text>')
    o.append(f'<rect x="{X0-10}" y="{Y["f"]+10}" width="{62*STEP+20}" height="{Y["e"]-Y["f"]-20}" fill="#E7E1D6"/>')
    for col in "jihgfedcba":
        o.append(f'<text x="{X0-26}" y="{Y[col]+3}" fill="#8A8173">{col}</text>')
    for r in range(1, 64):
        x = X0 + (r - 1) * STEP
        if r == 1 or r % 5 == 0:
            o.append(f'<text x="{x}" y="{Y["j"]-12}" text-anchor="middle" fill="#8A8173">{r}</text>')
            o.append(f'<text x="{x}" y="{Y["a"]+20}" text-anchor="middle" fill="#8A8173">{r}</text>')
        for col in list("jihgfedcba") + list(RAILS):
            o.append(f'<rect x="{x-2.5}" y="{Y[col]-2.5}" width="5" height="5" rx="1" fill="#B9B1A3"/>')
    name, r0, label, pins = IC
    x1, x2 = X0 + (r0 - 1) * STEP - 7, X0 + (r0 + 5) * STEP + 7
    o.append(f'<rect x="{x1}" y="{Y["f"]-4}" width="{x2-x1}" height="{Y["e"]-Y["f"]+8}" rx="3" fill="#2B2B2B"/>')
    o.append(f'<circle cx="{x1+5}" cy="{Y["e"]-2}" r="2.2" fill="#777"/>')
    o.append(f'<text x="{(x1+x2)/2}" y="{(Y["e"]+Y["f"])/2+3}" fill="#fff" text-anchor="middle" font-size="8.5">{label}</text>')
    for p in range(1, 15):
        hx, hy = xy(pin_hole(p))
        ty = hy + 0.5 if p <= 7 else hy + 5.5
        o.append(f'<text x="{hx}" y="{ty}" fill="#FFD166" text-anchor="middle" font-size="7">{p}</text>')
    for pid, kind, a, b, label, colour, *_ in PARTS:
        (x1, y1), (x2, y2) = xy(a), xy(b)
        if kind in ("wire", "jumper"):
            mx, my = (x1 + x2) / 2 + (10 if x1 == x2 else 0), (y1 + y2) / 2 - (0 if x1 == x2 else 14)
            dash = ' stroke-dasharray="4 3"' if kind == "jumper" else ""
            o.append(f'<path d="M{x1} {y1} Q{mx} {my} {x2} {y2}" fill="none" stroke="{COL[colour]}" '
                     f'stroke-width="2.4" stroke-linecap="round"{dash}/>')
        else:
            o.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#9A9A9A" stroke-width="1.4"/>')
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            vert = abs(y2 - y1) > abs(x2 - x1)
            bw, bh = (8, 14) if vert else (16, 8)
            o.append(f'<rect x="{cx-bw/2}" y="{cy-bh/2}" width="{bw}" height="{bh}" rx="2" fill="{FILL[kind]}"/>')
            if kind == "ecap":
                o.append(f'<text x="{x1+4}" y="{y1+(9 if y2>y1 else -3)}" fill="#1D4E89" font-weight="700">+</text>')
            if kind == "diode":   # cathode band at end 2
                bx = cx + (bw / 2 - 3 if not vert else 0)
                o.append(f'<rect x="{bx-1.5}" y="{cy-bh/2}" width="3" height="{bh}" fill="#ddd"/>')
        for h in (a, b):
            hx, hy = xy(h)
            o.append(f'<circle cx="{hx}" cy="{hy}" r="2.6" fill="#111"/>')
        o.append(f'<text x="{(x1 + x2) / 2 + 6}" y="{(y1 + y2) / 2 - 6}" fill="#111" font-weight="700" font-size="8">{pid}</text>')
    for h, text, _ in OFFBOARD:
        x, y = xy(h)
        o.append(f'<circle cx="{x}" cy="{y}" r="4" fill="none" stroke="#D62828" stroke-width="1.6"/>')
        words = text.split(" ")
        below = h[0] in ("a", "b", "BRg", "BRp")
        o.append(f'<text x="{x+6}" y="{y+(14 if below else -7)}" fill="#D62828" font-size="8">★{" ".join(words[:2])}</text>')
    o.append("</svg>")
    return "\n".join(o)


def main():
    errors = check()
    with open(os.path.join(HERE, "case1_breadboard.svg"), "w") as f:
        f.write(svg())
    data = dict(ic=IC, pin_nets=PIN_NETS, parts=PARTS, offboard=OFFBOARD)
    with open(os.path.join(HERE, "case1_breadboard.json"), "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("netlist check:", "OK (every lead on its intended net, no shorts, no clashes)" if not errors else "")
    for e in errors:
        print("  ERROR", e)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
