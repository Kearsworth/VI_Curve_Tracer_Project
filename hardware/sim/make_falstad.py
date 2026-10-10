"""
make_falstad.py — write the standalone front end (docs/STANDALONE_TESTER_PLAN.md) as a Falstad
CircuitJS file plus a share link, with the same values that pass stage0_check.py.

Run:  python3 hardware/sim/make_falstad.py      (pip install lzstring for the link)
Out:  hardware/sim/standalone_frontend.falstad.txt  (File > Import From Text in CircuitJS)

Not modeled: the MT3608 / ICL7660S rails — the op-amp is clamped at +-7.5 V, the swing an
NE5532 gets on +-9 V. Switches pick the DUT and the Rr; click a switch to flip it.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "standalone_frontend.falstad.txt")

DAC_AMP = round(104 * 3.3 / 255, 4)      # 1.3459 V: DAC 128 +- 104 counts, levelled to A = 5.0 V
L = ["$ 1 0.000005 10.391409633455755 50 5 50 5e-11"]
add = L.append

def label(x, y, text, size=12):
    add(f"x {x} {y} {x + 8 * len(text)} {y + 3} 4 {size} {text}")

# --- ESP32 DAC (sine around 1.65 V) -> AC coupling -> non-inverting amp, gain 1 + 27k/10k = 3.7
add(f"R 48 240 0 240 0 1 50 {DAC_AMP} 1.65 0 0.5")      # AC rail: 50 Hz, amp, bias
label(0, 208, "ESP32_DAC_GPIO25")
add("w 48 240 96 240 0")
add("c 96 240 160 240 0 0.000001 1.65")                # 1 uF, starts charged to the 1.65 V bias
add("r 160 240 160 320 0 100000")
add("g 160 320 160 352 0")
add("w 160 240 224 240 0")
add("a 224 224 320 224 8 7.5 -7.5 1000000 0 0 100000")  # in- (224,208), in+ (224,240), out (320,224)
add("w 224 208 224 160 0")
add("r 224 160 320 160 0 27000")                       # Rf
add("w 320 160 320 224 0")
add("r 224 160 224 96 0 10000")                        # Rg
add("g 224 96 224 64 0")
label(240, 272, "NE5532_on_9V_rails")
add("w 320 224 400 224 0")                             # node A
label(336, 208, "A")

# --- DUT bank between bus A (x=400) and bus B (x=560); switch 0 = closed, 1 = open
duts = [  # y, closed?, element line between (448,y) and (528,y), label
    (224, 0, "r 448 224 528 224 0 1000", "R_1k"),
    (288, 1, "d 448 288 528 288 2 default", "diode"),
    (352, 1, "162 448 352 528 352 2 default-led 1 0 0 0.01", "LED"),
    (416, 1, "w 448 416 528 416 0", "short"),
    (480, 1, "c 448 480 528 480 0 1e-7 0", "C_100n_(use_1kHz)"),
    (544, 1, "l 448 544 528 544 0 0.1 0", "L_100m_(use_1kHz)"),
]
for i, (y, pos, elm, name) in enumerate(duts):
    if i:
        add(f"w 400 {y - 64} 400 {y} 0")
        add(f"w 560 {y - 64} 560 {y} 0")
    add(f"s 400 {y} 448 {y} 0 {pos} false")
    add(elm)
    add(f"w 528 {y} 560 {y} 0")
    label(456, y - 24, name, 10)
label(568, 236, "B")

# --- Rr bank from bus B to ground, one switch each (1k closed by default)
add("w 560 480 624 480 0")
for i, (x, rr, pos) in enumerate([(624, 220, 1), (688, 1000, 0), (752, 10000, 1), (816, 100000, 1)]):
    if i:
        add(f"w {x - 64} 480 {x} 480 0")
    add(f"s {x} 480 {x} 528 0 {pos} false")
    add(f"r {x} 528 {x} 592 0 {rr}")
    add(f"g {x} 592 {x} 624 0")
    label(x + 6, 640, f"Rr_{rr}", 10)

# --- return path: Vin -100k- node -56k- 3.3V, node -56k- GND, 1 nF at the ADC pin
def return_path(x0, y, src_wire, pin_name):
    for w in src_wire:
        add(w)
    add(f"r {x0} {y} {x0 + 96} {y} 0 100000")
    n = x0 + 96
    add(f"r {n} {y} {n} {y - 64} 0 56000")
    add(f"R {n} {y - 64} {n} {y - 96} 0 0 40 3.3 0 0 0.5")
    add(f"r {n} {y} {n} {y + 64} 0 56000")
    add(f"g {n} {y + 64} {n} {y + 96} 0")
    add(f"w {n} {y} {n + 80} {y} 0")
    add(f"c {n + 80} {y} {n + 80} {y + 64} 0 1e-9 0")
    add(f"g {n + 80} {y + 64} {n + 80} {y + 96} 0")
    label(n + 88, y - 8, pin_name)

return_path(576, 112, ["w 400 224 400 112 0", "w 400 112 576 112 0"], "ADC_GPIO34_(node_A)")
return_path(880, 480, ["w 816 480 880 480 0"], "ADC_GPIO35_(node_B)")

text = "\n".join(L) + "\n"
with open(OUT, "w") as f:
    f.write(text)
print("wrote", OUT)
try:
    import lzstring
    link = "https://www.falstad.com/circuit/circuitjs.html?ctz=" + \
        lzstring.LZString().compressToEncodedURIComponent(text)
    with open(OUT.replace(".txt", ".url"), "w") as f:
        f.write(link + "\n")
    print("link written to", OUT.replace(".txt", ".url"), f"({len(link)} chars)")
except ImportError:
    print("pip install lzstring to also write a share link")
