"""
reader.py — turn the ESP32's serial stream into the pipeline's raw dict.

    serial lines  ->  parse_capture  ->  capture_to_raw  ->  {v, i, phase, A, Rr}
                                                              -> calibrate.calibrate(...)

Frame format: docs/DATA_CONTRACT.md section 7 (firmware/esp32/loopback/sine_capture):

    # key=value key=value ...          <- capture settings, once at boot
    index,t_us,phase_rad,adc_v_counts,adc_i_counts

Nothing here touches the ML code: the dict returned matches DATA_CONTRACT.md section 1, and
the phase comes straight from the firmware's `phase_rad` column (drive phase, not geometry).

Usage (from repo root):
    python3 hardware/reader.py --port /dev/cu.usbserial-XXXX --loopback --verify
    python3 hardware/reader.py --file capture.csv --loopback
"""
import argparse
import os
import sys
import time
from dataclasses import dataclass, field

import numpy as np

BAUD = 921600
ADC_MAX = 4095            # 12-bit
ADC_VREF_DEFAULT = 3.3


# ----------------------------------------------------------------------------------------
# counts -> volts
# ----------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ChannelCal:
    """Per-channel linear correction: volts = (counts - offset_counts) * volts_per_count."""
    offset_counts: float
    volts_per_count: float

    def to_volts(self, counts):
        return (np.asarray(counts, float) - self.offset_counts) * self.volts_per_count

    @classmethod
    def ideal(cls, vref=ADC_VREF_DEFAULT):
        """Textbook ADC, signal biased at mid-rail. Known to be WRONG on this ESP32
        (Stage 2 measured adc ~ 16*dac - 231, i.e. a real offset) — fine as a fallback."""
        return cls(ADC_MAX / 2, vref / ADC_MAX)

    @classmethod
    def centered_on(cls, counts, vref=ADC_VREF_DEFAULT):
        """LOOPBACK ONLY: assume a symmetric sine and put zero volts at its centre.
        Uses the midpoint of the 2nd/98th percentiles (unbiased for a sine, robust to
        spikes). Wrong for a real DUT — a diode's V/I is not symmetric about the bias."""
        lo, hi = np.percentile(np.asarray(counts, float), [2, 98])
        return cls((lo + hi) / 2, vref / ADC_MAX)


# ----------------------------------------------------------------------------------------
# parsing
# ----------------------------------------------------------------------------------------
@dataclass
class Capture:
    meta: dict = field(default_factory=dict)      # numeric `# key=value` settings
    index: np.ndarray = None
    t_us: np.ndarray = None
    phase: np.ndarray = None
    adc_v: np.ndarray = None
    adc_i: np.ndarray = None
    n_bad_lines: int = 0                          # malformed data lines that were skipped


def _parse_meta(line, meta):
    for tok in line.lstrip("#").split():
        key, sep, val = tok.partition("=")
        if sep:
            try:
                meta[key] = float(val)
            except ValueError:
                pass


def _parse_row(line):
    """Return (index, t_us, phase, v, i) or None if the line isn't a valid data row."""
    parts = line.split(",")
    if len(parts) != 5:
        return None
    try:
        idx, t_us, phase, v, i = int(parts[0]), int(parts[1]), float(parts[2]), int(parts[3]), int(parts[4])
    except ValueError:
        return None
    if not (0 <= v <= ADC_MAX and 0 <= i <= ADC_MAX and 0.0 <= phase <= 2 * np.pi + 1e-3):
        return None
    return idx, t_us, phase, v, i


def parse_capture(lines, max_cycles=None):
    """
    Parse serial lines into a Capture. Comment lines (#) feed `meta`; the CSV header and any
    malformed line (e.g. a half-received first line after opening the port) are skipped and
    counted in `n_bad_lines`. If `max_cycles` is set, stop reading as soon as that many
    FULL drive cycles have been seen (a cycle = one wrap of phase_rad back to ~0).
    """
    cap = Capture()
    rows, wraps, last_phase = [], 0, None
    for line in lines:
        if isinstance(line, bytes):
            line = line.decode("ascii", errors="replace")
        line = line.strip()
        if not line or line.startswith("index"):
            continue
        if line.startswith("#"):
            _parse_meta(line, cap.meta)
            continue
        row = _parse_row(line)
        if row is None:
            cap.n_bad_lines += 1
            continue
        rows.append(row)
        if last_phase is not None and last_phase - row[2] > np.pi:
            wraps += 1
            if max_cycles is not None and wraps > max_cycles:   # first wrap only *starts* cycle 1
                break
        last_phase = row[2]
    if rows:
        a = np.array(rows, float)
        cap.index, cap.t_us, cap.phase = a[:, 0], a[:, 1], a[:, 2]
        cap.adc_v, cap.adc_i = a[:, 3], a[:, 4]
    else:
        cap.index = cap.t_us = cap.phase = cap.adc_v = cap.adc_i = np.empty(0)
    return cap


def _whole_cycle_slice(phase):
    """Slice covering only complete drive cycles: from the first wrap to the last wrap."""
    wraps = np.where(np.diff(phase) < -np.pi)[0] + 1      # index of first sample after each wrap
    if len(wraps) < 2:
        raise ValueError(
            f"need at least one full drive cycle (two phase wraps), saw {len(wraps)} wrap(s) "
            f"in {len(phase)} samples"
        )
    return slice(wraps[0], wraps[-1])


# ----------------------------------------------------------------------------------------
# Capture -> raw dict
# ----------------------------------------------------------------------------------------
def capture_to_raw(cap, A=None, Rr=None, cal_v=None, cal_i=None, loopback=False):
    """
    Build the DATA_CONTRACT.md section 1 raw dict from a parsed Capture.

    A, Rr     : capture settings; default to the firmware's `A_nominal_v` /
                `Rr_ohm_placeholder` from the meta line. Both are placeholders until the
                real circuit exists (see firmware/esp32/README.md) — pass real values then.
    cal_v/cal_i: ChannelCal per channel; default is `ChannelCal.ideal`.
    loopback  : centre each channel on its own sine midpoint (DAC->ADC loopback only).

    I = V_sense / Rr, so with the loopback's shared pin (no real sense R) i == v / Rr.
    """
    A = cap.meta.get("A_nominal_v") if A is None else A
    Rr = cap.meta.get("Rr_ohm_placeholder") if Rr is None else Rr
    if A is None or Rr is None:
        raise ValueError("A and Rr are unknown: no '# ... A_nominal_v=... Rr_ohm_placeholder=...' "
                         "meta line was seen (board wasn't reset?). Pass A= and Rr= explicitly.")

    sl = _whole_cycle_slice(cap.phase)
    counts_v, counts_i, phase = cap.adc_v[sl], cap.adc_i[sl], cap.phase[sl]

    vref = cap.meta.get("vref", ADC_VREF_DEFAULT)
    if loopback:
        cal_v = cal_v or ChannelCal.centered_on(counts_v, vref)
        cal_i = cal_i or ChannelCal.centered_on(counts_i, vref)
    else:
        cal_v = cal_v or ChannelCal.ideal(vref)
        cal_i = cal_i or ChannelCal.ideal(vref)

    return {
        "v": cal_v.to_volts(counts_v),
        "i": cal_i.to_volts(counts_i) / Rr,
        "phase": phase,
        "A": float(A),
        "Rr": float(Rr),
    }


# ----------------------------------------------------------------------------------------
# sources: file and serial
# ----------------------------------------------------------------------------------------
def load_capture(path, max_cycles=None):
    """Parse a saved capture (the same text the board prints) — for replay without hardware."""
    with open(path, "r", errors="replace") as fh:
        return parse_capture(fh, max_cycles=max_cycles)


def _serial_lines(ser, deadline):
    while time.monotonic() < deadline:
        line = ser.readline()          # returns b"" on the port's read timeout
        if line:
            yield line


def read_capture(port, baud=BAUD, n_cycles=4, timeout_s=15.0, **raw_kwargs):
    """
    Open `port`, read `n_cycles` full drive cycles, return the raw dict.
    Opening the port normally resets an ESP32 devkit, so the `# ...` settings line arrives
    fresh; if your adapter doesn't reset it, pass A= and Rr= (via raw_kwargs) explicitly.
    """
    try:
        import serial              # pyserial; imported lazily so the ML side never needs it
    except ImportError as e:
        raise ImportError("pyserial is required for live capture: pip install pyserial") from e

    with serial.Serial(port, baud, timeout=1.0) as ser:
        cap = parse_capture(_serial_lines(ser, time.monotonic() + timeout_s), max_cycles=n_cycles)
    return capture_to_raw(cap, **raw_kwargs)


# ----------------------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--port", help="serial port, e.g. /dev/cu.usbserial-0001")
    src.add_argument("--file", help="saved capture text file")
    ap.add_argument("--cycles", type=int, default=4, help="full drive cycles to read (default 4)")
    ap.add_argument("--loopback", action="store_true", help="centre channels on their sine midpoint")
    ap.add_argument("--verify", action="store_true", help="run calibrate->features->verify on the capture")
    args = ap.parse_args(argv)

    if args.port:
        raw = read_capture(args.port, n_cycles=args.cycles, loopback=args.loopback)
    else:
        cap = load_capture(args.file, max_cycles=args.cycles)
        if cap.n_bad_lines:
            print(f"skipped {cap.n_bad_lines} malformed line(s)")
        raw = capture_to_raw(cap, loopback=args.loopback)

    print(f"samples: {len(raw['v'])}   A={raw['A']:.4f} V   Rr={raw['Rr']:g} ohm")
    print(f"v range: {raw['v'].min():+.3f} .. {raw['v'].max():+.3f} V   "
          f"phase: {raw['phase'].min():.3f} .. {raw['phase'].max():.3f} rad")

    if args.verify:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "vi_ml"))
        import verify
        print(verify.verify(raw))


if __name__ == "__main__":
    main()
