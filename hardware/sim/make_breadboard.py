"""
make_breadboard.py — Stage 1 breadboard layout for docs/STANDALONE_TESTER_PLAN.md, generated from
one connection list so the drawing and the tables can't disagree.

Run:  python3 hardware/sim/make_breadboard.py  ->  hardware/sim/stage1_breadboard.svg + .json

Board: one 830-point breadboard, rows 1-63, columns a-e / f-j.
  top rails (next to column j):    TR+ = +9 V (MT3608 out)      TR- = GND
  bottom rails (next to column a): BR- = GND                     BR+ = -9 V (ICL7660S out)  <- tape-label it!
Rr is picked with one jumper in Stage 1; relays replace that jumper later.
Values match hardware/sim/stage0_check.py.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

# ------------------------------------------------------------------ parts
ICS = [  # name, first row, label, pin labels 1..8 (pin1 at column e of first row)
    ("U1", 3, "ICL7660S", ["BOOST", "CAP+", "GND", "CAP−", "VOUT", "LV", "OSC", "V+"]),
    ("U2", 14, "NE5532", ["OUT A", "IN− A", "IN+ A", "V−", "IN+ B", "IN− B", "OUT B", "V+"]),
]
# kind: wire | res | cap | ecap (first end = +) | film | dut | jumper
PARTS = [
    # --- power: ICL7660S makes -9 V from +9 V
    ("W1", "wire", ("j", 3), ("TR+", 3), "U1 pin 8 (V+) → +9 V", "red"),
    ("W2", "wire", ("a", 5), ("BR-", 5), "U1 pin 3 → GND", "black"),
    ("C1", "ecap", ("b", 4), ("b", 6), "10 µF pump cap (+ ขา row 4 = pin 2)", None),
    ("W3", "wire", ("i", 6), ("BR+", 6), "U1 pin 5 (VOUT) → −9 V rail", "purple"),
    ("C2", "ecap", ("TR-", 7), ("g", 6), "10 µF output cap: + ที่ GND, − ที่ pin 5", None),
    ("W4", "wire", ("TR-", 1), ("BR-", 1), "GND บน ↔ GND ล่าง", "black"),
    ("C3", "ecap", ("TR+", 10), ("TR-", 10), "10 µF bulk +9 V", None),
    ("C4", "ecap", ("BR-", 10), ("BR+", 10), "10 µF bulk −9 V (+ ที่ GND)", None),
    # --- drive amplifier: gain 1 + 27k/10k = 3.7
    ("W5", "wire", ("j", 14), ("TR+", 14), "U2 pin 8 (V+) → +9 V", "red"),
    ("C5", "cap", ("h", 14), ("TR-", 13), "100 nF decoupling V+", None),
    ("W6", "wire", ("a", 17), ("BR+", 17), "U2 pin 4 (V−) → −9 V", "purple"),
    ("C6", "cap", ("b", 17), ("BR-", 18), "100 nF decoupling V−", None),
    ("W7", "wire", ("j", 17), ("TR-", 17), "U2 pin 5 → GND (ครึ่ง B ไม่ใช้)", "black"),
    ("W8", "wire", ("h", 16), ("h", 15), "U2 pin 6 ↔ pin 7 (ครึ่ง B เป็น follower)", "gray"),
    ("C7", "film", ("c", 11), ("c", 16), "1 µF film (ไม่มีขั้ว) DAC → IN+", None),
    ("R1", "res", ("b", 16), ("BR-", 16), "100 kΩ IN+ → GND", None),
    ("R2", "res", ("b", 15), ("BR-", 15), "Rg 10 kΩ IN− → GND", None),
    ("R3", "res", ("d", 15), ("d", 14), "Rf 27 kΩ OUT → IN−", None),
    ("W9", "wire", ("a", 14), ("a", 22), "U2 OUT → node A (row 22)", "orange"),
    # --- DUT between node A (row 22) and node B (row 28)
    ("DUT", "dut", ("d", 22), ("d", 28), "DUT: ขาบวก/anode ที่ row 22", None),
    # --- return path ch1 (node A -> GPIO34), node P1 = row 30
    ("R4", "res", ("b", 22), ("b", 30), "100 kΩ node A → P1", None),
    ("R5", "res", ("c", 30), ("c", 32), "56 kΩ P1 → 3.3 V", None),
    ("R6", "res", ("d", 30), ("BR-", 31), "56 kΩ P1 → GND", None),
    ("C8", "cap", ("a", 30), ("BR-", 30), "1 nF P1 → GND", None),
    # --- return path ch2 (node B -> GPIO35), node P2 = row 34; 3.3 V bus = row 32
    ("R7", "res", ("b", 28), ("b", 34), "100 kΩ node B → P2", None),
    ("R8", "res", ("c", 34), ("d", 32), "56 kΩ P2 → 3.3 V", None),
    ("R9", "res", ("d", 34), ("BR-", 35), "56 kΩ P2 → GND", None),
    ("C9", "cap", ("a", 34), ("BR-", 34), "1 nF P2 → GND", None),
    # --- Rr bank: node B -> bus row 40 -> one jumper -> chosen Rr -> GND
    ("W10", "wire", ("a", 28), ("f", 40), "node B → Rr bus (row 40)", "orange"),
    ("Rr1", "res", ("j", 44), ("TR-", 44), "Rr 220 Ω", None),
    ("Rr2", "res", ("j", 46), ("TR-", 46), "Rr 1 kΩ", None),
    ("Rr3", "res", ("j", 48), ("TR-", 48), "Rr 10 kΩ", None),
    ("Rr4", "res", ("j", 50), ("TR-", 50), "Rr 100 kΩ", None),
    ("JS", "jumper", ("g", 40), ("f", 46), "สายเลือก Rr (ตอนนี้ = 1 kΩ) ย้ายไป row 44/46/48/50", "green"),
]
OFFBOARD = [  # (hole, text) — wires to the ESP32 / MT3608 that leave the board
    (("TR+", 2), "MT3608 VOUT+ (ตั้ง 9.0 V ก่อน!)"),
    (("TR-", 3), "MT3608 VOUT−"),
    (("BR-", 3), "ESP32 GND"),
    (("a", 11), "ESP32 GPIO25 (DAC)"),
    (("a", 32), "ESP32 3V3"),
    (("e", 30), "ESP32 GPIO34 — ต่อเป็นอย่างสุดท้าย"),
    (("e", 34), "ESP32 GPIO35 — ต่อเป็นอย่างสุดท้าย"),
]

# ------------------------------------------------------------------ geometry
STEP = 16
X0 = 56
Y = {"TR+": 40, "TR-": 56, "j": 92, "i": 108, "h": 124, "g": 140, "f": 156,
     "e": 188, "d": 204, "c": 220, "b": 236, "a": 252, "BR-": 288, "BR+": 304}
W, H = X0 + 62 * STEP + 56, 340
COL = {"red": "#D62828", "black": "#222", "purple": "#7B2CBF", "gray": "#888", "orange": "#E07A00", "green": "#2B9348"}


def xy(h):
    col, row = h
    return X0 + (row - 1) * STEP, Y[col]


def svg():
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="IBM Plex Mono, monospace" font-size="9">']
    o.append(f'<rect x="8" y="8" width="{W-16}" height="{H-16}" rx="10" fill="#F4F1EA" stroke="#CFC8BC"/>')
    for name, y, c in [("+9V", Y["TR+"], "#D62828"), ("GND", Y["TR-"], "#2F5DA8"), ("GND", Y["BR-"], "#2F5DA8"), ("−9V", Y["BR+"], "#7B2CBF")]:
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
        for col in list("jihgfedcba") + ["TR+", "TR-", "BR-", "BR+"]:
            o.append(f'<rect x="{x-2.5}" y="{Y[col]-2.5}" width="5" height="5" rx="1" fill="#B9B1A3"/>')
    for name, r0, label, pins in ICS:
        x1, x2 = X0 + (r0 - 1) * STEP - 7, X0 + (r0 + 2) * STEP + 7
        o.append(f'<rect x="{x1}" y="{Y["f"]-4}" width="{x2-x1}" height="{Y["e"]-Y["f"]+8}" rx="3" fill="#2B2B2B"/>')
        o.append(f'<circle cx="{x1+5}" cy="{Y["e"]-2}" r="2.2" fill="#777"/>')
        o.append(f'<text x="{(x1+x2)/2}" y="{(Y["e"]+Y["f"])/2+3}" fill="#fff" text-anchor="middle" font-size="8.5">{label}</text>')
        for k in range(4):
            x = X0 + (r0 - 1 + k) * STEP
            o.append(f'<text x="{x}" y="{Y["e"]+0.5}" fill="#FFD166" text-anchor="middle" font-size="7">{k+1}</text>')
            o.append(f'<text x="{x}" y="{Y["f"]+5.5}" fill="#FFD166" text-anchor="middle" font-size="7">{8-k}</text>')
    for pid, kind, a, b, label, color in PARTS:
        (x1, y1), (x2, y2) = xy(a), xy(b)
        if kind in ("wire", "jumper"):
            mx, my = (x1 + x2) / 2 + (10 if x1 == x2 else 0), (y1 + y2) / 2 - (0 if x1 == x2 else 14)
            dash = ' stroke-dasharray="4 3"' if kind == "jumper" else ""
            o.append(f'<path d="M{x1} {y1} Q{mx} {my} {x2} {y2}" fill="none" stroke="{COL[color]}" stroke-width="2.4" stroke-linecap="round"{dash}/>')
        else:
            stroke = {"res": "#8B5E34", "cap": "#C77D00", "ecap": "#1D4E89", "film": "#B5179E", "dut": "#D62828"}[kind]
            o.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#9A9A9A" stroke-width="1.4"/>')
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            vert = abs(y2 - y1) > abs(x2 - x1)
            bw, bh = (8, 14) if vert else (16, 8)
            o.append(f'<rect x="{cx-bw/2}" y="{cy-bh/2}" width="{bw}" height="{bh}" rx="2" fill="{stroke}"/>')
            if kind == "ecap":
                o.append(f'<text x="{x1+4}" y="{y1+(9 if y2>y1 else -3)}" fill="#1D4E89" font-weight="700">+</text>')
        for h in (a, b):
            hx, hy = xy(h)
            o.append(f'<circle cx="{hx}" cy="{hy}" r="2.6" fill="#111"/>')
        tx, ty = xy(a)
        o.append(f'<text x="{(tx + xy(b)[0]) / 2 + 6}" y="{(ty + xy(b)[1]) / 2 - 6}" fill="#111" font-weight="700" font-size="8">{pid}</text>')
    for h, text in OFFBOARD:
        x, y = xy(h)
        o.append(f'<circle cx="{x}" cy="{y}" r="4" fill="none" stroke="#D62828" stroke-width="1.6"/>')
        o.append(f'<text x="{x+6}" y="{y+(14 if h[0] in ("a","b","BR-","BR+") else -7)}" fill="#D62828" font-size="8">★{text.split(" ")[0]} {text.split(" ")[1] if len(text.split(" "))>1 else ""}</text>')
    o.append("</svg>")
    return "\n".join(o)


def main():
    with open(os.path.join(HERE, "stage1_breadboard.svg"), "w") as f:
        f.write(svg())
    data = dict(ics=ICS, parts=PARTS, offboard=OFFBOARD)
    with open(os.path.join(HERE, "stage1_breadboard.json"), "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    # sanity: no hole used twice except rails
    used = {}
    for pid, kind, a, b, *_ in PARTS:
        for h in (a, b):
            if h[0] in ("TR+", "TR-", "BR-", "BR+"):
                continue
            used.setdefault(h, []).append(pid)
    for _, r0, _, _ in ICS:
        for k in range(4):
            used.setdefault(("e", r0 + k), []).append("IC")
            used.setdefault(("f", r0 + k), []).append("IC")
    for h, _ in OFFBOARD:
        if h[0] not in ("TR+", "TR-", "BR-", "BR+"):
            used.setdefault(h, []).append("offboard")
    clash = {h: v for h, v in used.items() if len(v) > 1}
    print("hole clashes:", clash or "none")
    # sanity: 5 holes per half-row
    rows = {}
    for (c, r), v in used.items():
        rows.setdefault((r, c in "abcde"), 0)
        rows[(r, c in "abcde")] += 1
    print("fullest half-row:", max(rows.values()), "holes (max 5)")


if __name__ == "__main__":
    main()
