"""
collect.py — guided capture of a batch of labelled parts into hardware/captures/.

It tells you which part to plug in, waits for Enter, takes one 1 kHz burst with the Rr the
plan asks for, prints the value and the model's verdict, saves the capture and appends its
row to labels.csv. Items are ordered by Rr, so the Rr selector jumper moves as few times as
possible. Run it in a terminal (it reads the keyboard), with nothing else holding the port.

    python3 hardware/collect.py r          # good resistors across the 1 % kit (100 ohm .. 300 kohm)
    python3 hardware/collect.py r_oor      # good resistors OUTSIDE the trained range (not scored)
    python3 hardware/collect.py esr        # 0.1 uF + series R   (high-ESR capacitor)
    python3 hardware/collect.py leak       # 0.1 uF || R         (leaky capacitor)
    python3 hardware/collect.py degraded   # 1N4148 + series R   (degraded diode)
    python3 hardware/collect.py led        # LED + series R      (degraded LED)
    python3 hardware/collect.py --list     # show the plans

Labels follow synth.py's definitions: a fault inside synth's range is `faulty`; a severity
between synth's good and faulty ranges, or a part outside the trained value range, is
`boundary` (kept, not scored by eval_real / the tests). Base ESR of the 0.1 uF ceramic
(~80 ohm at 1 kHz, measured 2026-11-27) is counted in the ESR plan.

Needs case1_frontend_mf on the board and a zero-cal taken with it (tools/zero_capture.txt;
its copy in hardware/captures is --zero-label).
"""
import argparse
import csv
import datetime
import filecmp
import io
import os
import sys
import time
import warnings

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "vi_ml"))
import autorange  # noqa: E402
import eval_real  # noqa: E402
import reader  # noqa: E402
import synth  # noqa: E402

CAPTURES = os.path.join(ROOT, "hardware", "captures")
ZERO = os.path.join(ROOT, "tools", "zero_capture.txt")
FIRMWARE = "case1_frontend_mf (+ GPIO32 reference)"
# Rr positions: nominal -> value measured on the board (schematic / CASE1_WIRING)
RR_ACTUAL = {220.0: 221.4, 1000.0: 1022.0, 10000.0: 10290.0, 100000.0: 101300.0}
KIT = [10, 22, 47, 100, 150, 200, 220, 270, 330, 470, 510, 680, 1e3, 2e3, 2.2e3, 3.3e3, 4.7e3, 5.1e3,
       6.8e3, 10e3, 20e3, 47e3, 51e3, 68e3, 100e3, 220e3, 300e3, 470e3, 680e3, 1e6]   # 1 % kit, 30 values
XC_100N_1K = 1 / (2 * np.pi * 1000 * 100e-9)     # 1592 ohm
C_BASE_ESR = 80.0                                  # the ceramic's own loss at 1 kHz (DF ~5 %)


def ohm(r):
    return f"{r / 1e6:g}M" if r >= 1e6 else f"{r / 1e3:g}k" if r >= 1e3 else f"{r:g}"


def _rr_for_r(r):
    return synth.auto_range(lambda f: complex(r, 0.0))[1]


def plans():
    lo, hi = synth.VALUE_RANGE["R"]
    p = {}
    p["r"] = [dict(slug=f"R{ohm(r)}", what=f"ตัวต้านทาน {ohm(r)} Ω", component="R", health="good", fault="",
                   reference=f"{ohm(r)} ohm 1 % (kit)", rr=_rr_for_r(r)) for r in KIT if lo <= r <= hi]
    p["r_oor"] = [dict(slug=f"R{ohm(r)}", what=f"ตัวต้านทาน {ohm(r)} Ω (นอกช่วงที่เทรน)", component="R",
                       health="boundary", fault="", reference=f"{ohm(r)} ohm 1 % (kit), outside synth's "
                       f"{lo:g}-{hi:g} ohm", rr=_rr_for_r(r)) for r in (10, 47, 470e3, 1e6)]
    p["esr"] = []
    for r in (47, 100, 150, 220, 470):
        ratio = (C_BASE_ESR + r) / XC_100N_1K
        health, fault = ("faulty", "esr") if ratio >= 0.12 else ("boundary", "esr")
        p["esr"].append(dict(slug=f"C100n_ser_{ohm(r)}", what=f"C 0.1 µF อนุกรม R {ohm(r)} Ω", component="C",
                             health=health, fault=fault, rr=1000.0,
                             reference=f"0.1 uF ceramic + {ohm(r)} ohm in series (ESR/X_C ~{ratio:.2f}; synth good "
                                       f"<= 0.06, faulty 0.12-0.75)"))
    p["leak"] = []
    own = XC_100N_1K / C_BASE_ESR                 # the ceramic's own loss as a parallel R, in X_C (~20)
    for r in (4.7e3, 10e3, 20e3, 47e3):
        ratio = 1 / (XC_100N_1K / r + 1 / own)      # added R in parallel with the C's own loss
        health = "faulty" if ratio < 11.25 else "boundary"      # synth leak 1.25-12.5, 10 % margin at the edge
        p["leak"].append(dict(slug=f"C100n_par_{ohm(r)}", what=f"C 0.1 µF ขนาน R {ohm(r)} Ω", component="C",
                              health=health, fault="leak", rr=1000.0,
                              reference=f"0.1 uF ceramic || {ohm(r)} ohm (Rleak/X_C {r / XC_100N_1K:.1f}, "
                                        f"{ratio:.1f} with the C's own loss; synth leak 1.25-12.5)"))
    p["degraded"] = []
    for r in (100, 470, 680, 2.2e3):
        health = "faulty" if 200 <= r <= 800 else "boundary"
        p["degraded"].append(dict(slug=f"D1N4148_ser_{ohm(r)}", what=f"ไดโอด 1N4148 อนุกรม R {ohm(r)} Ω "
                                  "(แถบไปทาง node B)", component="D", health=health, fault="degraded", rr=1000.0,
                                  reference=f"1N4148 + {ohm(r)} ohm in series (synth degraded Rs 200-800 ohm)"))
    p["led"] = []
    for r in (100, 220, 470):
        health = "faulty" if 200 <= r <= 800 else "boundary"
        p["led"].append(dict(slug=f"LED_ser_{ohm(r)}", what=f"LED อนุกรม R {ohm(r)} Ω (ขายาวไปทาง node A)",
                             component="LED", health=health, fault="degraded", rr=1000.0,
                             reference=f"LED + {ohm(r)} ohm in series (synth degraded Rs 200-800 ohm)"))
    # next board session (docs/NEXT_BOARD_SESSION.md): parts not tried yet, only values that range at 1 kHz
    p["zener"] = [dict(slug=f"Z{v}V", what=f"ซีเนอร์ {v} V (แถบไปทาง node B)", component="Z", health="good",
                       fault="", rr=1000.0, reference=f"Zener {v} V (marking); at A ~4.66 V the reverse knee "
                       "shows only below ~3.6 V") for v in ("2.7", "3.0", "3.3")]
    p["l"] = []
    for L in (22e-3, 47e-3, 100e-3, 220e-3, 1.0):
        f, rr = synth.auto_range(lambda ff, L=L: complex(0.0, 2 * np.pi * ff * L))
        if f != 1000.0:
            continue
        x = 2 * np.pi * 1000.0 * L
        p["l"].append(dict(slug=f"L{L * 1e3:g}mH", what=f"ตัวเหนี่ยวนำ {L * 1e3:g} mH (วัด DCR ด้วยมิเตอร์ก่อน)",
                           component="L", health="boundary", fault="", rr=rr,
                           reference=f"{L * 1e3:g} mH choke (marking); X_L {x:.0f} ohm at 1 kHz; good in synth needs "
                                     f"Q >= 8, i.e. DCR <= {x / 8:.0f} ohm: measure DCR, then relabel good if it fits"))
    p["c"] = []
    for C in (1e-9, 10e-9, 1e-6):
        f, rr = synth.auto_range(lambda ff, C=C: complex(0.0, -1 / (2 * np.pi * ff * C)))
        if f != 1000.0:
            continue
        name = f"{C * 1e9:g}n" if C < 1e-6 else f"{C * 1e6:g}u"
        p["c"].append(dict(slug=f"C{name}", what=f"ตัวเก็บประจุไม่มีขั้ว {name}F (ฟิล์มหรือเซรามิก)", component="C",
                           health="good", fault="", rr=rr, reference=f"{name}F film/ceramic (marking)"))
    for items in p.values():
        items.sort(key=lambda it: it["rr"])
    return p


def capture_one(ser, timeout=12):
    """One fresh 1 kHz burst taken after Enter: flush what queued while waiting, drop the
    burst in progress, keep the next whole one."""
    ser.reset_input_buffer()
    ser.write(b"\nf 1000\nn 32\n")
    autorange.read_burst(ser, 1000.0, timeout=timeout)
    return autorange.read_burst(ser, 1000.0, timeout=timeout)


def analyse(lines, item, rr, zero):
    cap = reader.parse_capture(lines)
    info = {}
    raw = reader.frontend_to_raw(cap, Rr=rr, cal_a=zero[0], cal_b=zero[1], info=info)
    import verify
    out = verify.verify(raw)
    row = dict(component=item["component"], fault=item["fault"], drive_hz="1000")
    return raw, out, eval_real.value_text(row, raw), info.get("ref_drift_counts")


def save(lines, slug, date, out_dir):
    name = f"{date}_mf1k_{slug}.txt"
    k = 2
    while os.path.exists(os.path.join(out_dir, name)):
        name = f"{date}_mf1k_{slug}_{k}.txt"
        k += 1
    with open(os.path.join(out_dir, name), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return name


def append_label(labels, name, item, rr, zero_label, note):
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerow(
        [name, "1000", FIRMWARE, "case1", f"{rr:g}", zero_label, item["component"], item["health"],
         item["fault"], item["reference"], note])
    with open(labels, "a", newline="") as fh:
        fh.write(buf.getvalue())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("plan", nargs="?", help="r | r_oor | esr | leak | degraded | led | zener | l | c")
    ap.add_argument("--list", action="store_true", help="show the plans and exit")
    ap.add_argument("--port", default="auto")
    ap.add_argument("--rr-now", type=float, default=1000.0, help="nominal Rr the jumper is on now (default 1000)")
    ap.add_argument("--zero", default=ZERO, metavar="FILE",
                    help="zero-cal capture taken with no DUT (default: tools/zero_capture.txt)")
    ap.add_argument("--zero-label", default="2026-11-27_mf1k_zero_ref_noDUT.txt",
                    help="hardware/captures copy of tools/zero_capture.txt, for labels.csv")
    ap.add_argument("--out", default=CAPTURES, help="where captures go (default hardware/captures)")
    ap.add_argument("--labels", default=None, help="labels.csv to append to (default <out>/labels.csv)")
    ap.add_argument("--start", type=int, default=1, help="resume the plan at part N (1-based)")
    ap.add_argument("--only", help="comma-separated slugs to (re)measure, e.g. R10k")
    ap.add_argument("--yes", action="store_true", help="don't wait for Enter (testing)")
    args = ap.parse_args(argv)
    all_plans = plans()
    if args.list or not args.plan:
        for name, items in all_plans.items():
            print(f"{name}: " + ", ".join(f"{it['slug']}[{it['health']}, Rr {ohm(it['rr'])}]" for it in items))
        return 0
    items = all_plans[args.plan]
    if args.only:
        want = set(args.only.split(","))
        items = [it for it in items if it["slug"] in want]
        if not items:
            sys.exit(f"no part named {args.only} in plan {args.plan}")
    labels = args.labels or os.path.join(args.out, "labels.csv")
    warnings.filterwarnings("ignore", category=UserWarning)

    if not os.path.exists(args.zero):
        sys.exit(f"zero-cal file not found: {args.zero} (take one with no DUT, or pass --zero FILE)")
    zero = reader.zero_cal(reader.load_capture(args.zero))
    if zero[0].ref_counts is None:
        sys.exit(f"{args.zero} has no reference reading: take a new zero-cal with case1_frontend_mf")
    zl = os.path.join(CAPTURES, args.zero_label)
    if not (os.path.exists(zl) and filecmp.cmp(zl, args.zero, shallow=False)):
        print(f"WARNING: {args.zero_label} is not the same file as {args.zero} — fix --zero-label")
    port = args.port
    if port == "auto":
        from serial.tools import list_ports
        port = next((p.device for p in list_ports.comports() if p.vid in (0x10C4, 0x1A86, 0x0403, 0x303A)), None)
        if not port:
            sys.exit("board not found on USB")
    date = datetime.date.today().isoformat()
    ask = (lambda msg: "") if args.yes else input
    rr_now, done = args.rr_now, []

    import serial
    with serial.Serial(port, reader.BAUD, timeout=0.2) as ser:
        reader.reset_board(ser)
        print(f"plan '{args.plan}': {len(items)} parts. Enter = วัด, s = ข้าม, q = จบ\n")
        for n, item in enumerate(items, 1):
            if n < args.start:
                continue
            if item["rr"] != rr_now:
                ask(f">> ย้ายสายเลือก Rr ไปที่ {ohm(item['rr'])} ({ohm(RR_ACTUAL[item['rr']])} Ω จริง) แล้วกด Enter ")
                rr_now = item["rr"]
            key = ask(f"[{n}/{len(items)}] เสียบ {item['what']} แล้วกด Enter ").strip().lower()
            if key == "q":
                break
            if key == "s":
                continue
            rr = RR_ACTUAL[rr_now]
            try:
                try:
                    lines = capture_one(ser)
                except TimeoutError:
                    # 2026-11-27: the port went silent mid-batch (USB re-enumerated / board hung);
                    # reopen it, reset the board and try once more
                    print("    .. no burst: reopening the port and resetting the board")
                    ser.close()
                    time.sleep(1.0)
                    ser.open()
                    reader.reset_board(ser)
                    lines = capture_one(ser)
                raw, out, value, drift = analyse(lines, item, rr, zero)
            except Exception as e:                      # keep the batch going; the part can be redone
                print(f"    !! {e}  (redo it later with --only {item['slug']})")
                continue
            name = save(lines, item["slug"], date, args.out)
            note = f"collect.py, Rr {rr:g} ohm" + (f"; reads {value.strip()}" if value.strip() else "")
            append_label(labels, name, item, rr, args.zero_label, note)
            expect = {"good": "GOOD", "faulty": "FAULTY"}.get(item["health"], "?")
            mark = "" if expect == "?" else (" ✓" if out["verdict"] == expect else " ✗ (expected " + expect + ")")
            p_faulty = out["confidence"] if out["verdict"] == "FAULTY" else 1 - out["confidence"]
            print(f"    {value.strip() or 'nonlinear':>24s}  →  {out['type']} / {out['verdict']}{mark}  "
                  f"(p_faulty {p_faulty:.2f}, A {raw['A']:.2f} V, drift {drift if drift is None else f'{drift:+.1f}'})"
                  f"  -> {name}")
            final = autorange.judge(raw, out)
            if final["verdict"] != out["verdict"] or final["range"] not in ("ok", "nonlinear"):
                print(f"    => tester answer: {final['verdict']} ({final['range']}): {final['reason']}")
            done.append((item, out["verdict"], expect))
    scored = [d for d in done if d[2] != "?"]
    right = sum(v == e for _, v, e in scored)
    print(f"\n{len(done)} captured, {right}/{len(scored)} scored verdicts right. "
          "Check them all: python3 hardware/eval_real.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
