"""
demo_r.py — Case 1 front end as a resistance meter, for a live demo.

Each capture: read node A/B through the Case 1 front end, fit V_DUT = R·I + c by least
squares, and show R next to the V-I loop (a resistor is a straight line through the origin;
its slope is R). Optionally also runs the ML verdict (--verify).

  live:      python3 hardware/demo_r.py --port /dev/cu.usbserial-0001 --rr 1022
  rehearse:  python3 hardware/demo_r.py --file tools/last_capture.txt --rr 1022

Live mode: press Enter in the terminal for a new capture, q + Enter to quit.
Release the serial port first (Ctrl+C in the serial pane).
Zero-cal: tools/zero_capture.txt is used automatically if it exists (--zero to override).
"""
import argparse
import os
import sys
import warnings

import numpy as np
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import reader  # noqa: E402

DEFAULT_ZERO = os.path.join(ROOT, "tools", "zero_capture.txt")
MIN_SNR = 8               # current's 50 Hz component must stand this far above the noise


def _fundamental(x, phase):
    """Complex amplitude of x at the drive frequency (lock-in over the whole cycles)."""
    return 2 * np.mean(x * np.exp(-1j * phase))


def fit_r(raw):
    """
    (R ohm, offset V, r2, i_peak A). R = |V1|/|I1| from the drive-frequency (50 Hz) component
    of V_DUT and I — a lock-in: ADC noise averages out over every sample, and an empty socket
    shows up as a current no bigger than the noise (-> R = inf) instead of a random slope.
    r2 is the straight-line fit's linearity, for display only.
    """
    v, i, ph = raw["v"], raw["i"], raw["phase"]
    V1, I1 = _fundamental(v, ph), _fundamental(i, ph)
    i_noise = np.std(i - np.real(I1 * np.exp(1j * ph)) - i.mean()) * np.sqrt(2 / len(i))
    c = float(np.mean(v))
    if abs(I1) < MIN_SNR * i_noise:
        return np.inf, c, 0.0, float(abs(I1))
    R = abs(V1) / abs(I1)
    r2 = float(np.corrcoef(v, i)[0, 1] ** 2)
    return float(R), c, r2, float(abs(I1))


def fmt_ohm(R):
    if not np.isfinite(R):
        return "OPEN (∞)"
    if R < 20:
        return f"SHORT (~{R:.0f} Ω)"
    if abs(R) >= 1e3:
        return f"{R/1e3:.3f} kΩ"
    return f"{R:.1f} Ω"


def show(ax, raw, R, c, r2, n, verdict=None):
    ax.clear()
    i_ma = raw["i"] * 1e3
    ax.plot(raw["v"], i_ma, ".", ms=3, color="#1f77b4", label="measured")
    if np.isfinite(R) and R != 0:
        vv = np.linspace(np.percentile(raw["v"], 1), np.percentile(raw["v"], 99), 2)
        ax.plot(vv, (vv - c) / R * 1e3, "-", color="#d62728", lw=1.5, label="I = V / R  (50 Hz lock-in)")
    ax.axhline(0, color="0.7", lw=0.8)
    ax.axvline(0, color="0.7", lw=0.8)
    ax.set_xlabel("V_DUT (V)")
    ax.set_ylabel("I (mA)")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left")
    title = f"R = {fmt_ohm(R)}"
    sub = f"capture #{n}   Rr = {raw['Rr']:g} Ω   A = {raw['A']:.2f} V   linearity r² = {r2:.4f}"
    if verdict:
        sub += f"\nML: {verdict['type']} / {verdict['verdict']} (conf {verdict['confidence']:.2f})"
    ax.figure.suptitle(title, fontsize=28, fontweight="bold", y=0.99)
    ax.set_title(sub, fontsize=10)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--port", help="serial port, e.g. /dev/cu.usbserial-0001")
    src.add_argument("--file", help="saved capture (rehearsal, no board needed)")
    ap.add_argument("--rr", type=float, required=True, help="sense resistor actually connected, ohms")
    ap.add_argument("--cycles", type=int, default=10, help="drive cycles per capture (default 10)")
    ap.add_argument("--zero", default=DEFAULT_ZERO, help="no-DUT zero capture ('' to skip)")
    ap.add_argument("--verify", action="store_true", help="also print the ML verdict")
    ap.add_argument("--no-plot", action="store_true", help="terminal output only")
    ap.add_argument("--live", action="store_true",
                    help="keep the port open and update R continuously (close the window to stop)")
    args = ap.parse_args(argv)

    fe = reader.FrontEnd.case1()
    kw = dict(Rr=args.rr, fe=fe)
    if args.zero and os.path.exists(args.zero):
        kw["cal_a"], kw["cal_b"] = reader.zero_cal(reader.load_capture(args.zero), fe=fe)
        print(f"zero-cal: {os.path.relpath(args.zero, ROOT)}")
    else:
        print("zero-cal: none (ADC reads ~0.17 V low; current will be off)")

    verify = None
    if args.verify:
        sys.path.insert(0, os.path.join(ROOT, "vi_ml"))
        warnings.filterwarnings("ignore", category=UserWarning, module="sklearn")
        warnings.filterwarnings("ignore", message=".*InconsistentVersion.*")
        import verify  # noqa: F811

    fig = None
    if not args.no_plot:
        plt.ion()
        fig, ax = plt.subplots(figsize=(8, 6.5))
        fig.subplots_adjust(top=0.80)

    def report(raw, n):
        R, c, r2, i_pk = fit_r(raw)
        v_verdict = verify.verify(raw) if verify else None
        line = f"#{n}  R = {fmt_ohm(R):>14}   I_pk = {i_pk*1e3:.3f} mA   r² = {r2:.4f}"
        if v_verdict:
            line += f"   ML: {v_verdict['type']}/{v_verdict['verdict']} ({v_verdict['confidence']:.2f})"
        print(line, flush=True)
        if fig:
            show(ax, raw, R, c, r2, n, v_verdict)
            fig.canvas.draw_idle()
            plt.pause(0.05)

    if args.live:
        if not args.port:
            ap.error("--live needs --port")
        import termios
        import time
        import serial
        meta, n = {}, 0

        def alive():
            return fig is None or plt.fignum_exists(fig.number)

        while alive():
            try:
                ser = serial.Serial(args.port, reader.BAUD, timeout=1.0)
            except (serial.SerialException, OSError):
                print(f"waiting for {args.port} (USB unplugged?) ...", flush=True)
                if fig:
                    ax.set_title("USB disconnected: waiting for the board ...", color="#d62728")
                    plt.pause(1.0)
                else:
                    time.sleep(1.0)
                continue
            try:
                with ser:
                    first = True
                    while alive():
                        if not first:
                            ser.reset_input_buffer()    # drop the backlog: show what's plugged in NOW
                        first = False
                        lines = reader._serial_lines(ser, time.monotonic() + 5.0)
                        cap = reader.parse_capture(lines, max_cycles=args.cycles)
                        meta.update(cap.meta)
                        cap.meta = dict(meta)
                        try:
                            raw = reader.frontend_to_raw(cap, **kw)
                        except Exception as e:      # a garbled capture mid-swap: skip it
                            print(f"skip: {e}", flush=True)
                            continue
                        n += 1
                        report(raw, n)
            except (serial.SerialException, OSError, termios.error) as e:
                print(f"USB lost ({e}); reconnecting ...", flush=True)
        return

    n = 0
    while True:
        if args.port:
            raw = reader.read_capture(args.port, n_cycles=args.cycles, frontend=True, **kw)
        else:
            raw = reader.frontend_to_raw(reader.load_capture(args.file, max_cycles=args.cycles), **kw)
        n += 1
        report(raw, n)
        if not args.port:
            if fig:
                plt.ioff()
                plt.show()
            return
        if input("Enter = capture ใหม่, q = ออก > ").strip().lower() == "q":
            return


if __name__ == "__main__":
    main()
