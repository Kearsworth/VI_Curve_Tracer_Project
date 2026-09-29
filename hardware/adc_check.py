"""
adc_check.py — is the ESP32's internal ADC accurate enough, or do we need an external one?

Runs firmware/esp32/loopback/adc_step: for a list of DAC codes it collects ADC counts, and you
type in the TRUE voltage from a multimeter at GPIO34. From that we report:
  - noise      : std of the counts at each step (the ADC's own jitter)
  - linearity  : residual of counts vs multimeter volts after a straight-line fit
                 (the ADC's own nonlinearity — the DAC's is irrelevant, the multimeter is the truth)

Error budget (docs: Q3 = 10 mV at the +-10 V return-path full scale): a 0-3.3 V pin mapped to
20 V spans 6.06x, and one count is 3.3/4095 V, so 10 mV of drive-side error is ~2 counts.

Usage:
    python3 hardware/adc_check.py --port /dev/cu.usbserial-XXXX
"""
import argparse
import csv
import sys
import time

import numpy as np

BAUD = 921600
VREF = 3.3
ADC_MAX = 4095
FULL_SCALE_V = 20.0                        # +-10 V return path
COUNTS_PER_10MV = 0.010 / FULL_SCALE_V * ADC_MAX      # ~2.05 counts
PASS_COUNTS = COUNTS_PER_10MV
BORDERLINE_COUNTS = 2 * COUNTS_PER_10MV
DEFAULT_CODES = list(range(28, 229, 20))   # the DAC range sine_capture uses (28..228)


def parse_step_lines(lines):
    """Lines from adc_step -> {dac_code: np.array(counts)}. Skips comments, header, junk."""
    steps = {}
    for line in lines:
        if isinstance(line, bytes):
            line = line.decode("ascii", errors="replace")
        parts = line.strip().split(",")
        if len(parts) != 3:
            continue
        try:
            code, _, counts = int(parts[0]), int(parts[1]), int(parts[2])
        except ValueError:
            continue
        if 0 <= counts <= ADC_MAX:
            steps.setdefault(code, []).append(counts)
    return {k: np.array(v, float) for k, v in steps.items()}


def counts_to_drive_mv(counts):
    """Counts -> millivolts at the +-10 V drive side (i.e. as if scaled to FULL_SCALE_V)."""
    return counts * FULL_SCALE_V / ADC_MAX * 1000.0


def linearity(volts, mean_counts):
    """Fit counts = gain*volts + offset; return (gain, offset, residuals in counts)."""
    volts, mean_counts = np.asarray(volts, float), np.asarray(mean_counts, float)
    gain, offset = np.polyfit(volts, mean_counts, 1)
    return gain, offset, mean_counts - (gain * volts + offset)


def verdict(worst_counts):
    if worst_counts <= PASS_COUNTS:
        return "PASS (internal ADC fits the budget)"
    if worst_counts <= BORDERLINE_COUNTS:
        return "BORDERLINE (order the external ADC in parallel)"
    return "FAIL (use an external ADC)"


def _collect_step(ser, code):
    ser.reset_input_buffer()
    ser.write(f"d {code}\n".encode())
    lines, deadline = [], time.monotonic() + 30
    while time.monotonic() < deadline:
        line = ser.readline()
        if line.startswith(b"# done"):
            break
        lines.append(line)
    return parse_step_lines(lines).get(code, np.empty(0))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", required=True)
    ap.add_argument("--codes", default=",".join(map(str, DEFAULT_CODES)),
                    help="comma-separated DAC codes to step through")
    ap.add_argument("--out", help="write per-step results to this CSV")
    args = ap.parse_args(argv)

    try:
        import serial
    except ImportError:
        sys.exit("pyserial is required: pip install pyserial")

    rows = []
    with serial.Serial(args.port, BAUD, timeout=1.0) as ser:
        time.sleep(2.0)                                   # ESP32 resets when the port opens
        for code in [int(c) for c in args.codes.split(",")]:
            counts = _collect_step(ser, code)
            if len(counts) < 100:
                print(f"code {code}: only {len(counts)} samples, skipped")
                continue
            ans = input(f"code {code:3d}: mean {counts.mean():7.1f}  std {counts.std():.2f} counts. "
                        f"Multimeter volts at GPIO34 (blank to skip): ").strip()
            rows.append((code, float(ans) if ans else None, counts.mean(), counts.std()))

    if not rows:
        sys.exit("no data collected")
    worst_noise = max(r[3] for r in rows)
    print(f"\nnoise: worst std {worst_noise:.2f} counts = {counts_to_drive_mv(worst_noise):.1f} mV "
          f"at +-10 V scale (budget ~{PASS_COUNTS:.1f} counts = 10 mV)")

    measured = [r for r in rows if r[1] is not None]
    worst_lin = 0.0
    if len(measured) >= 4:
        gain, offset, res = linearity([r[1] for r in measured], [r[2] for r in measured])
        worst_lin = float(np.abs(res).max())
        print(f"linearity: counts = {gain:.1f} * V + {offset:.1f}   (ideal gain {ADC_MAX / VREF:.1f})")
        print(f"           worst residual {worst_lin:.2f} counts = {counts_to_drive_mv(worst_lin):.1f} mV "
              f"at +-10 V scale")
    else:
        print("linearity: need >= 4 multimeter readings to fit; skipped")

    print("verdict:", verdict(max(worst_noise, worst_lin)))

    if args.out:
        with open(args.out, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["dac_code", "multimeter_v", "mean_counts", "std_counts"])
            w.writerows(rows)


if __name__ == "__main__":
    main()
