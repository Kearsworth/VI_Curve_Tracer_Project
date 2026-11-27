"""
autorange.py — measure a part at the drive frequency and Rr that make its V-I loop readable.

A loop is readable when the part's impedance |Z| is near the sense resistor Rr. One frequency
can't do that for every capacitor (0.1 uF wants 1 kHz with Rr 1k, 1000 uF wants 1 Hz with
220 ohm), so — like a commercial tracer — this picks the condition per part, with the same
rule synth trains on: synth.auto_range over synth.TEST_FREQS_HZ x synth.RR_OPTIONS.

  python3 hardware/autorange.py                  # Rr connected now: tools/board_settings.json
  python3 hardware/autorange.py --rr 1022 --rr-values 217,1022,10000,100000

Needs firmware case1_frontend_mf (selectable frequency). Steps:
  1. reset the board, take one 1 kHz burst with the Rr connected now
  2. lock-in Z at 1 kHz. A nonlinear part (diode/LED/Zener: strong harmonics) stays at 1 kHz
     with Rr 1k, where synth trains semiconductors
  3. a linear part: model Z(f) from that one value (R, or R + C / R + L in series) and pick
     (f, Rr)
  4. if that needs another Rr: asks you to move the Rr selector jumper, then waits for Enter
  5. if it still looks like a short at the smallest Rr: one look at 1 Hz — a big C opens up
     there, a real short doesn't
  6. capture at the chosen condition, run verify, print verdict and value; the capture goes to
     tools/last_capture.txt and the summary to tools/board.log, like the board page
"""
import argparse
import datetime
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "vi_ml"))
import reader  # noqa: E402
import synth   # noqa: E402

TOOLS = os.path.join(ROOT, "tools")
SETTINGS = os.path.join(TOOLS, "board_settings.json")
ZERO = os.path.join(TOOLS, "zero_capture.txt")
LAST = os.path.join(TOOLS, "last_capture.txt")
LOG = os.path.join(TOOLS, "board.log")
DEFAULT_RR_VALUES = (217.0, 1022.0, 10000.0, 100000.0)   # measured / nominal, same order as RR_OPTIONS
NONLINEAR_THD = 0.15        # harmonics / fundamental of the current: diode ~0.5, R/C/L < 0.05
SHORT_RATIO = 0.1           # |Z| / Rr below this at the smallest Rr: short, or a C too big for 1 kHz
HEADER = "index,t_us,phase_rad,adc_v_counts,adc_i_counts"


# ---------------------------------------------------------------- analysis (no hardware)
def lockin_z(raw):
    e = np.exp(-1j * raw["phase"])
    return complex(np.mean(raw["v"] * e) / np.mean(raw["i"] * e))


def current_thd(raw):
    """Harmonic content of the DUT current (2nd..5th over the fundamental), from the
    phase-binned signature, so it works at any samples-per-cycle."""
    import calibrate
    i = calibrate.calibrate(raw)[:, 1]
    h = np.abs(np.fft.rfft(i - i.mean()))
    return float(np.sqrt(np.sum(h[2:6] ** 2)) / (h[1] + 1e-12))


def z_model(z, f):
    """|Z| at any frequency from one measurement z (complex ohms) at f: R if nearly resistive,
    else R + C or R + L in series."""
    w = 2 * np.pi * f
    r, x = z.real, z.imag
    if abs(x) < 0.1 * abs(z):
        return lambda ff: complex(abs(z), 0.0)
    if x < 0:
        c = -1 / (w * x)
        return lambda ff: complex(r, -1 / (2 * np.pi * ff * c))
    l = x / w
    return lambda ff: complex(r, 2 * np.pi * ff * l)


def plan(z, f, nonlinear):
    """(drive Hz, nominal Rr) for a part measured as z at f."""
    if nonlinear:
        return synth.DEFAULT_F, synth.DEFAULT_RR
    return synth.auto_range(z_model(z, f))


def describe(z, f):
    w = 2 * np.pi * f
    if abs(z.imag) < 0.1 * abs(z):
        return f"R = {abs(z):.1f} ohm"
    if z.imag < 0:
        return f"C = {-1 / (w * z.imag) * 1e9:.4g} nF + {z.real:.0f} ohm (series)"
    return f"L = {z.imag / w * 1e3:.4g} mH + {z.real:.0f} ohm (series)"


def cycles_for(hz):
    """Whole cycles per burst: ~3 s of signal, 4..32 cycles."""
    return int(min(32, max(4, round(3 * hz))))


# ---------------------------------------------------------------- board I/O
def read_burst(ser, hz, timeout):
    """Lines of the first whole burst whose meta line says drive_freq_hz ~ hz."""
    buf, lines, active, t_end = b"", [], False, time.monotonic() + timeout
    while time.monotonic() < t_end:
        chunk = ser.read(ser.in_waiting or 1)
        if not chunk:
            continue
        buf += chunk
        *done, buf = buf.split(b"\n")
        for raw in done:
            line = raw.decode("ascii", "replace").rstrip("\r")
            if line.startswith("# error"):
                raise RuntimeError(line)
            if line.startswith("# drive_freq_hz="):
                f = float(line.split()[1].split("=")[1])
                active = abs(f - hz) / hz < 0.02
                lines = [line, HEADER] if active else []
                continue
            if active:
                lines.append(line)
                if line.startswith("# burst="):
                    return lines
    raise TimeoutError(f"no {hz:g} Hz burst within {timeout:.0f} s: is case1_frontend_mf running?")


def capture(ser, hz, log=print):
    m = int(min(1000, max(1, round(1000 / hz))))
    hz = 1000 / m
    n = cycles_for(hz)
    log(f"  capture {hz:.4g} Hz, {n} cycles ...")
    ser.write(f"\nf {hz:.6g}\nn {n}\n".encode())
    return read_burst(ser, hz, timeout=6 + (n + 6) / hz)


def analyse(lines, rr, zero):
    cap = reader.parse_capture(lines)
    kw = dict(cal_a=zero[0], cal_b=zero[1]) if zero else {}
    raw = reader.frontend_to_raw(cap, Rr=rr, **kw)
    return cap, raw, lockin_z(raw), current_thd(raw)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", default="auto")
    ap.add_argument("--rr", type=float, help="Rr connected now, ohm (default: tools/board_settings.json)")
    ap.add_argument("--rr-values", default=",".join(f"{v:g}" for v in DEFAULT_RR_VALUES),
                    help="actual values of the 220/1k/10k/100k positions, ohm")
    ap.add_argument("--no-verify", action="store_true")
    args = ap.parse_args(argv)

    settings = {}
    if os.path.exists(SETTINGS):
        with open(SETTINGS) as fh:
            settings = json.load(fh)
    rr_values = [float(x) for x in args.rr_values.split(",")]
    actual = dict(zip(synth.RR_OPTIONS, rr_values))
    rr_now = args.rr or float(settings.get("rr", 1022.0))
    zero = reader.zero_cal(reader.load_capture(ZERO)) if os.path.exists(ZERO) else None
    port = args.port
    if port == "auto":
        from serial.tools import list_ports
        port = next((p.device for p in list_ports.comports() if p.vid in (0x10C4, 0x1A86, 0x0403, 0x303A)), None)
        if not port:
            sys.exit("board not found on USB")

    import serial
    with serial.Serial(port, reader.BAUD, timeout=0.2) as ser:
        reader.reset_board(ser)
        print(f"[1] 1 kHz with Rr {rr_now:g} ohm")
        lines = capture(ser, 1000.0)
        cap, raw, z, thd = analyse(lines, rr_now, zero)
        nonlinear = thd > NONLINEAR_THD
        print(f"    |Z| {abs(z):.4g} ohm, angle {np.degrees(np.angle(z)):+.1f} deg, harmonics {thd:.2f}"
              f" -> {'nonlinear (diode/LED/Zener)' if nonlinear else describe(z, 1000.0)}")

        def need_rr(nominal):
            nonlocal rr_now
            want = actual[nominal]
            if abs(want - rr_now) / want > 0.05:
                input(f"    >> ย้ายสายเลือก Rr ไปที่ตัว {want:g} ohm แล้วกด Enter (ตอนนี้ {rr_now:g} ohm) ")
                rr_now = want

        f_hz, rr_nom = plan(z, 1000.0, nonlinear)
        print(f"[2] plan: {f_hz:.4g} Hz with Rr {actual[rr_nom]:g} ohm")
        need_rr(rr_nom)
        lines = capture(ser, f_hz)
        cap, raw, z, thd = analyse(lines, rr_now, zero)

        smallest = synth.RR_OPTIONS[0]
        if not nonlinear and rr_nom == smallest and abs(z) / rr_now < SHORT_RATIO and f_hz > synth.TEST_FREQS_HZ[-1]:
            f_low = synth.TEST_FREQS_HZ[-1]
            print(f"[3] looks like a short at {rr_now:g} ohm: checking {f_low:g} Hz for a big capacitor")
            lines_low = capture(ser, f_low)
            cap_l, raw_l, z_l, thd_l = analyse(lines_low, rr_now, zero)
            if abs(z_l) > 5 * abs(z) and z_l.imag < 0:
                f2, rr2 = plan(z_l, f_low, False)
                print(f"    opens up at {f_low:g} Hz ({describe(z_l, f_low)}): plan {f2:.4g} Hz, Rr {actual[rr2]:g}")
                need_rr(rr2)
                f_hz, rr_nom = f2, rr2
                lines = capture(ser, f_hz)
                cap, raw, z, thd = analyse(lines, rr_now, zero)
            else:
                print(f"    still {abs(z_l):.3g} ohm at {f_low:g} Hz: a real short")

    with open(LAST, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    result = f"{f_hz:.4g} Hz, Rr {rr_now:g} ohm: |Z| {abs(z):.4g} ohm, {describe(z, f_hz)}, |Z|/Rr {abs(z) / rr_now:.2f}"
    print(f"[4] {result}")
    verdict = ""
    if not args.no_verify:
        import warnings
        warnings.filterwarnings("ignore", category=UserWarning)
        import verify
        verdict = str(verify.verify(raw))
        print(f"    {verdict}")
    if settings:
        settings["rr"] = rr_now
        with open(SETTINGS, "w") as fh:
            json.dump(settings, fh)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG, "a") as fh:
        fh.write(f"== {stamp}  autorange  {result}\n{verdict}\n\n")
    if abs(rr_now - actual[synth.DEFAULT_RR]) > 1:
        print(f"    (สายเลือก Rr อยู่ที่ {rr_now:g} ohm — ย้ายกลับ 1k ก่อนวัดไดโอด/LED ในช่อง board)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
