"""
eval_real.py — run the trained model on the labelled real captures in hardware/captures/.

  python3 hardware/eval_real.py               # table + summary; exit code 1 if a verdict is wrong
  python3 hardware/eval_real.py --cycles 32

Each row of hardware/captures/labels.csv names a capture (the text the board prints, e.g. a copy
of tools/last_capture.txt), the settings it was taken with (Rr, front end, zero-cal file) and
what the part really is. Rows with health = zero are zero-cal captures: used, not scored.
tests/test_real_captures.py runs the same rows, so a synth/feature change that breaks a real
verdict fails pytest.
"""
import argparse
import csv
import os
import sys
import warnings

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CAPTURES = os.path.join(HERE, "captures")
LABELS = os.path.join(CAPTURES, "labels.csv")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "vi_ml"))
import reader  # noqa: E402


def load_labels(path=LABELS):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def raw_for(row, cycles=16):
    """Raw dict for one labels.csv row, exactly as the board page / reader.py would build it."""
    fe = reader.FrontEnd.case1() if row["frontend"] == "case1" else reader.FrontEnd()
    cap = reader.load_capture(os.path.join(CAPTURES, row["file"]), max_cycles=cycles)
    kw = {}
    if row["zero_cal"]:
        zcap = reader.load_capture(os.path.join(CAPTURES, row["zero_cal"]))
        kw["cal_a"], kw["cal_b"] = reader.zero_cal(zcap, fe=fe)
    return reader.frontend_to_raw(cap, Rr=float(row["rr_ohm"]), fe=fe, **kw)


def lockin_z(raw):
    """DUT impedance at the drive frequency (complex ohms), from the V and I fundamentals."""
    e = np.exp(-1j * raw["phase"])
    return complex(np.mean(raw["v"] * e) / np.mean(raw["i"] * e))


def value_text(row, raw):
    z = lockin_z(raw)
    if row["component"] == "R":
        return f"{abs(z):.1f} ohm"
    if row["component"] == "C" and z.imag < 0:
        return f"{-1 / (2 * np.pi * float(row['drive_hz']) * z.imag) * 1e9:.1f} nF"
    return ""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cycles", type=int, default=16, help="drive cycles per capture (default 16)")
    args = ap.parse_args(argv)
    warnings.filterwarnings("ignore", category=UserWarning)
    import verify

    rows = [r for r in load_labels() if r["health"] in ("good", "faulty")]
    wrong = 0
    print(f"{'capture':34s} {'truth':16s} {'verdict':7s} {'p_faulty':>8s} {'type':5s} {'value':>11s}")
    for r in rows:
        raw = raw_for(r, args.cycles)
        out = verify.verify(raw)
        expect = "GOOD" if r["health"] == "good" else "FAULTY"
        p_faulty = out["confidence"] if out["verdict"] == "FAULTY" else 1 - out["confidence"]
        ok = out["verdict"] == expect
        wrong += not ok
        truth = f"{r['component']} {r['health']}" + (f" ({r['fault']})" if r["fault"] else "")
        print(f"{r['file']:34s} {truth:16s} {out['verdict']:7s} {p_faulty:8.2f} {out['type']:5s} "
              f"{value_text(r, raw):>11s}  {'ok' if ok else 'WRONG'}")
    print(f"\n{len(rows) - wrong}/{len(rows)} verdicts correct")
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())
