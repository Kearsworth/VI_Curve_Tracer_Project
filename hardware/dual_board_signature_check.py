"""
dual_board_signature_check.py — capture all three signature_gen shapes on real hardware
and plot the calibrated V-I loop for each, side by side.

Not part of the ML pipeline; a verification tool for the two-board bring-up
(firmware/esp32/dual_board/). This is the actual check firmware/esp32/dual_board/README.md
and the logbook's Next Steps item 1 ask for: does each shape (R/C/D) come back looking like
what it should, once it's gone through the real DAC -> wire -> ADC -> sync -> reader.py ->
calibrate.py chain?

Usage:
    python3 hardware/dual_board_signature_check.py \
        --gen-port /dev/cu.usbserial-0001 --cap-port /dev/cu.usbserial-9
"""
import argparse
import os
import sys
import time

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "vi_ml"))
import calibrate
import features

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import reader

SHAPES = {
    "R": "line (R)",
    "C": "ellipse (C/L)",
    "D": "knee (D)",
}

# signature_capture.ino's placeholders -- the board only prints its '# ... A_nominal_v=...'
# meta line once, right after boot, so a listener that attaches later (as this script does,
# since the board is likely already running from earlier testing) misses it. Passing these
# explicitly is the documented fallback in reader.py's read_capture() docstring.
A_PLACEHOLDER = 1.29
RR_PLACEHOLDER = 1.0


def select_shape(gen_port, shape, settle_s=1.0):
    import serial
    ser = serial.Serial(gen_port, 115200, timeout=1.0)
    time.sleep(settle_s)
    ser.reset_input_buffer()
    ser.write(f"{shape}\n".encode())
    time.sleep(0.3)
    ack = ser.read(200).decode(errors="replace").strip()
    ser.close()
    return ack


def capture_and_calibrate(cap_port, n_cycles):
    raw = reader.read_capture(cap_port, n_cycles=n_cycles, A=A_PLACEHOLDER, Rr=RR_PLACEHOLDER)
    sig = calibrate.calibrate(raw)
    x = features.extract(sig)
    corr = float(np.corrcoef(sig[:, 0], sig[:, 1])[0, 1])
    return sig, x, corr


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--gen-port", required=True, help="signature_gen board's port")
    ap.add_argument("--cap-port", required=True, help="signature_capture board's port")
    ap.add_argument("--shapes", default="R,C,D", help="comma-separated shapes to test")
    ap.add_argument("--cycles", type=int, default=4)
    ap.add_argument("--out", help="also save the figure to this path (e.g. figs/shapes.png)")
    ap.add_argument("--no-show", action="store_true",
                     help="skip the interactive window (e.g. for a headless/automated run)")
    args = ap.parse_args()

    shapes = args.shapes.split(",")
    fig, axes = plt.subplots(1, len(shapes), figsize=(5 * len(shapes), 5))
    if len(shapes) == 1:
        axes = [axes]

    for ax, shape in zip(axes, shapes):
        print(f"--- {shape} ({SHAPES.get(shape, '?')}) ---")
        ack = select_shape(args.gen_port, shape)
        print("  GEN ack:", ack or "(no response)")

        sig, x, corr = capture_and_calibrate(args.cap_port, args.cycles)
        aspect = x[4]
        print(f"  correlation={corr:+.4f}  aspect={aspect:.4f}  slope0={x[2]:+.4f}"
              f"  n_segments={x[8]:.0f}")

        ax.axhline(0, color="0.7", linewidth=0.8)
        ax.axvline(0, color="0.7", linewidth=0.8)
        ax.plot(sig[:, 0], sig[:, 1], linewidth=1.4)
        ax.set_title(f"{shape} = {SHAPES.get(shape, '?')}")
        ax.set_xlabel("V (normalized)")
        ax.set_ylabel("I (normalized)")
        ax.set_aspect("equal", adjustable="box")
        ax.grid(alpha=.3)
        ax.text(0.02, 0.98, f"corr={corr:+.3f}\naspect={aspect:.3f}",
                transform=ax.transAxes, va="top", fontsize=9,
                bbox=dict(boxstyle="round", facecolor="white", alpha=.8))

    fig.suptitle("Two-board bring-up: calibrated V-I signature per shape (real hardware)")
    fig.tight_layout()
    if args.out:
        fig.savefig(args.out, dpi=150)
        print("saved:", args.out)
    if not args.no_show:
        plt.show()


if __name__ == "__main__":
    main()
