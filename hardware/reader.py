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
    python3 hardware/reader.py --port /dev/cu.usbserial-XXXX --frontend --rr 1000 --verify
        (standalone front end, docs/STANDALONE_TESTER_PLAN.md: adc_v = node A, adc_i = node B)
        The front-end constants are picked from the meta line: `frontend_case=1` (Case 1 board,
        docs/CASE1_WIRING.md) -> FrontEnd.case1(); no key -> FrontEnd() (Stage 1, +-5 V).
        Override with --fe stage1|case1.
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

    @classmethod
    def zeroed(cls, counts, pin_volts, vref=ADC_VREF_DEFAULT):
        """Offset-only fit: the mean of `counts` reads as `pin_volts` (ideal slope kept).
        Built by `zero_cal` from a no-DUT capture, where both nodes are known to sit at 0 V."""
        vpc = vref / ADC_MAX
        return cls(float(np.mean(counts)) - pin_volts / vpc, vpc)


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
    n_dup_lines: int = 0                          # repeated/stale rows dropped (see parse_capture)


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

    Rows whose index is not ahead of the previous row's are dropped (`n_dup_lines`): when the
    PC reads too slowly the CP2102's buffer overflows and old 64-byte USB packets come through
    again (seen 2026-11-27). Lost rows (index jumps forward) are kept. A meta or header line,
    or 50 "stale" rows in a row, starts a new stream (the board was reset).
    """
    cap = Capture()
    rows, wraps, last_phase = [], 0, None
    last_idx, stale_run = None, 0
    for line in lines:
        if isinstance(line, bytes):
            line = line.decode("ascii", errors="replace")
        line = line.strip()
        if not line or line.startswith("index"):
            last_idx = None
            continue
        if line.startswith("#"):
            _parse_meta(line, cap.meta)
            if "drive_freq_hz=" in line:
                last_idx = None
            continue
        row = _parse_row(line)
        if row is None:
            cap.n_bad_lines += 1
            continue
        if last_idx is not None:
            wrap = int(cap.meta.get("index_wrap", 10000))
            step = (row[0] - last_idx) % wrap
            if (step == 0 or step > wrap // 2) and stale_run < 50:
                stale_run += 1
                cap.n_dup_lines += 1
                continue
        stale_run = 0
        last_idx = row[0]
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


@dataclass(frozen=True)
class FrontEnd:
    """
    Standalone front end (docs/STANDALONE_TESTER_PLAN.md, Stage 0-verified values). Each ADC
    pin sees its node through  node -r_in- pin,  pin -r_up- v_supply,  pin -r_dn- GND,  so
        pin = gain * node + offset.
    The same network loads node B: a Thevenin source v_th behind r_th, which adds a current
    that must be subtracted from V_B/Rr (up to ~100 % error at Rr = 100 kOhm otherwise).
    Replace the nominal resistor values with measured ones once the board exists.

    buffered=True: a unity follower sits between each node and its divider (Case 1, ch C/D of
    the OPA4134), so the divider does not load node B and I = V_B / Rr exactly.
    """
    r_in: float = 100e3          # node-A divider (and node B's too, unless `b` is given)
    r_up: float = 56e3
    r_dn: float = 56e3
    v_supply: float = 3.3
    buffered: bool = False
    b: tuple = None              # node-B divider (r_in, r_up, r_dn) when it differs from node A's

    @classmethod
    def case1(cls):
        """Case 1 board (docs/CASE1_WIRING.md): followers + 100k/20k/20k dividers, per channel.

        Measured 2026-11-26: ch C (node A) 100k/19.38k/19.43k, ch D (node B) 101k/19.48k/19.51k.
        The two gains differ 0.48 %; using their average read a 988 ohm resistor (meter) as
        998.6 ohm (+1.1 %) on 2026-11-27, so each channel now uses its own. 22k wasn't on hand.
        """
        return cls(r_in=100e3, r_up=19.38e3, r_dn=19.43e3, v_supply=3.32, buffered=True,
                   b=(101e3, 19.48e3, 19.51e3))

    @classmethod
    def from_meta(cls, meta):
        """Pick the front end the firmware declared (`# ... frontend_case=1 ...`)."""
        return cls.case1() if meta.get("frontend_case") == 1 else cls()

    def _res(self, channel):
        return self.b if (channel == "b" and self.b) else (self.r_in, self.r_up, self.r_dn)

    def gain_of(self, channel="a"):
        r_in, r_up, r_dn = self._res(channel)
        return (1 / r_in) / (1 / r_in + 1 / r_up + 1 / r_dn)

    def offset_of(self, channel="a"):
        r_in, r_up, r_dn = self._res(channel)
        return self.v_supply * (1 / r_up) / (1 / r_in + 1 / r_up + 1 / r_dn)

    @property
    def gain(self):
        return self.gain_of("a")

    @property
    def offset(self):
        return self.offset_of("a")

    @property
    def v_th(self):                      # node B's divider as seen from node B (loading term)
        _, r_up, r_dn = self._res("b")
        return self.v_supply * r_dn / (r_up + r_dn)

    @property
    def r_th(self):
        r_in, r_up, r_dn = self._res("b")
        return r_in + r_up * r_dn / (r_up + r_dn)

    def node_from_pin(self, v_pin, channel="a"):
        return (np.asarray(v_pin, float) - self.offset_of(channel)) / self.gain_of(channel)

    def dut(self, v_pin_a, v_pin_b, rr):
        """Pin voltages at node A / node B -> (V across DUT, current through DUT)."""
        va, vb = self.node_from_pin(v_pin_a, "a"), self.node_from_pin(v_pin_b, "b")
        if self.buffered:
            return va - vb, vb / rr
        return va - vb, vb / rr + (vb - self.v_th) / self.r_th


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


def drive_phase_shift(node_a, phase):
    """Angle d (rad) with node_a ~ A*sin(phase + d), from the drive-frequency component over
    whole cycles. Node A IS the drive, so phase + d is the true drive phase."""
    z = np.mean((node_a - np.mean(node_a)) * np.exp(-1j * phase))
    return float(np.angle(2j * z))


def frontend_to_raw(cap, Rr=None, A=None, cal_a=None, cal_b=None, fe=None, align_phase=True, info=None):
    """
    Raw dict for the standalone front end: adc_v = node A pin, adc_i = node B pin.
    Rr defaults to the meta line's `Rr_ohm_placeholder` (Stage 1 picks Rr with a jumper, so
    pass the value actually plugged in). A defaults to the MEASURED drive amplitude — half
    the 1st-99th percentile span of node A — which is what calibrate() should normalise by.
    fe defaults to the front end the meta line declares (FrontEnd.from_meta).

    align_phase: shift the firmware's clock-based phase labels so node A reads +A*sin(phase).
    The labels carry a constant timing offset (2026-11-27: ~14 deg at 1 kHz from the DMA
    interrupt latency, ~2.6 deg at 50 Hz); node A is the drive itself, so its measured phase
    is the drive phase (CLAUDE.md design decision #2) — not the DUT loop's geometry. V/I are
    untouched. Pass a dict as `info` to get the applied shift back (`phase_shift_deg`).
    """
    fe = FrontEnd.from_meta(cap.meta) if fe is None else fe
    Rr = cap.meta.get("Rr_ohm_placeholder") if Rr is None else Rr
    if Rr is None:
        raise ValueError("Rr is unknown: pass Rr= (the sense resistor actually connected).")
    sl = _whole_cycle_slice(cap.phase)
    vref = cap.meta.get("vref", ADC_VREF_DEFAULT)
    absolute = ChannelCal(0.0, vref / ADC_MAX)          # pin volts, not centred
    pin_a = (cal_a or absolute).to_volts(cap.adc_v[sl])
    pin_b = (cal_b or absolute).to_volts(cap.adc_i[sl])
    v, i = fe.dut(pin_a, pin_b, Rr)
    node_a = fe.node_from_pin(pin_a, "a")
    if A is None:
        lo, hi = np.percentile(node_a, [1, 99])
        A = (hi - lo) / 2
    phase = cap.phase[sl]
    shift = drive_phase_shift(node_a, phase) if align_phase else 0.0
    if info is not None:
        info["phase_shift_deg"] = float(np.degrees(shift))
    if shift:
        phase = np.mod(phase + shift, 2 * np.pi)
    return {"v": v, "i": i, "phase": phase, "A": float(A), "Rr": float(Rr)}


def zero_cal(cap, fe=None, max_b_ratio=0.02):
    """
    (cal_a, cal_b) from a capture taken with NO DUT plugged in (Rr still to GND).
    The ESP32 ADC reads ~0.17 V low on this board (2026-11-26: P1/P2 1.508 V on a meter,
    1654/1658 counts ~ 1.33 V ideal) — that shifts node B by ~-2 V and wrecks I = V_B/Rr.
    With no DUT, node B is exactly 0 V and node A is a sine centred on ~0 V (DAC_CENTER is
    trimmed), so each channel's whole-cycle mean is where node = 0 V, i.e. pin = fe.offset.
    Only the offset is fitted; the slope stays ideal (V/I ratios don't depend on it).
    Refuses a capture whose node B follows the drive (a DUT was plugged in).
    """
    fe = FrontEnd.from_meta(cap.meta) if fe is None else fe
    sl = _whole_cycle_slice(cap.phase)
    a, b, ph = (np.asarray(x[sl], float) for x in (cap.adc_v, cap.adc_i, cap.phase))
    basis = np.c_[np.sin(ph), np.cos(ph), np.ones_like(ph)]
    amp = [np.hypot(*np.linalg.lstsq(basis, x, rcond=None)[0][:2]) for x in (a, b)]
    if amp[1] > max_b_ratio * amp[0]:
        raise ValueError(f"zero capture: node B follows the drive ({amp[1]:.0f} vs {amp[0]:.0f} counts) "
                         "— take it with no DUT plugged in")
    vref = cap.meta.get("vref", ADC_VREF_DEFAULT)
    return ChannelCal.zeroed(a, fe.offset_of("a"), vref), ChannelCal.zeroed(b, fe.offset_of("b"), vref)


# ----------------------------------------------------------------------------------------
# sources: file and serial
# ----------------------------------------------------------------------------------------
def load_capture(path, max_cycles=None):
    """Parse a saved capture (the same text the board prints) — for replay without hardware."""
    with open(path, "r", errors="replace") as fh:
        return parse_capture(fh, max_cycles=max_cycles)


def _serial_lines(ser, deadline):
    """Lines from an open port until `deadline`. Bulk reads, not readline(): byte-by-byte reads
    can't keep up with a 921600 stream, and the CP2102's buffer then overflows (garbled rows)."""
    buf = b""
    while time.monotonic() < deadline:
        chunk = ser.read(ser.in_waiting or 1)      # b"" on the port's read timeout
        if not chunk:
            continue
        buf += chunk
        *complete, buf = buf.split(b"\n")
        for line in complete:
            yield line


def reset_board(ser):
    """Reset an ESP32 DevKit through its auto-reset circuit (EN low while RTS is asserted and DTR
    isn't), then drop whatever was buffered. Opening the port alone doesn't reset it on macOS."""
    ser.dtr = False
    ser.rts = True
    time.sleep(0.1)
    ser.rts = False
    time.sleep(0.05)
    ser.reset_input_buffer()


def read_capture(port, baud=BAUD, n_cycles=4, timeout_s=15.0, frontend=False, **raw_kwargs):
    """
    Open `port`, reset the board (so the `# ...` settings line arrives fresh), read `n_cycles`
    full drive cycles, return the raw dict. If your adapter can't reset the board, pass A= and
    Rr= (via raw_kwargs) explicitly.
    """
    try:
        import serial              # pyserial; imported lazily so the ML side never needs it
    except ImportError as e:
        raise ImportError("pyserial is required for live capture: pip install pyserial") from e

    with serial.Serial(port, baud, timeout=1.0) as ser:
        reset_board(ser)
        cap = parse_capture(_serial_lines(ser, time.monotonic() + timeout_s), max_cycles=n_cycles)
    return frontend_to_raw(cap, **raw_kwargs) if frontend else capture_to_raw(cap, **raw_kwargs)


# ----------------------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--port", help="serial port, e.g. /dev/cu.usbserial-0001")
    src.add_argument("--file", help="saved capture text file")
    ap.add_argument("--cycles", type=int, default=4, help="full drive cycles to read (default 4)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--loopback", action="store_true", help="centre channels on their sine midpoint")
    mode.add_argument("--frontend", action="store_true", help="standalone front end: adc_v = node A, adc_i = node B")
    ap.add_argument("--rr", type=float, help="sense resistor actually connected, ohms (--frontend)")
    ap.add_argument("--fe", choices=("stage1", "case1"),
                    help="front-end constants (--frontend); default: from the meta line's frontend_case")
    ap.add_argument("--zero", metavar="FILE",
                    help="no-DUT capture: zero each ADC channel's offset from it (--frontend)")
    ap.add_argument("--verify", action="store_true", help="run calibrate->features->verify on the capture")
    args = ap.parse_args(argv)

    kw = dict(Rr=args.rr) if args.frontend else dict(loopback=args.loopback)
    if args.frontend and args.fe:
        kw["fe"] = FrontEnd.case1() if args.fe == "case1" else FrontEnd()
    if args.frontend and args.zero:
        zcap = load_capture(args.zero)
        kw["cal_a"], kw["cal_b"] = zero_cal(zcap, fe=kw.get("fe"))
        print(f"zero-cal from {args.zero}: offset A {kw['cal_a'].offset_counts:.1f}, "
              f"B {kw['cal_b'].offset_counts:.1f} counts")
    if args.port:
        raw = read_capture(args.port, n_cycles=args.cycles, frontend=args.frontend, **kw)
    else:
        cap = load_capture(args.file, max_cycles=args.cycles)
        if cap.n_bad_lines:
            print(f"skipped {cap.n_bad_lines} malformed line(s)")
        if cap.n_dup_lines:
            print(f"dropped {cap.n_dup_lines} repeated/stale row(s) (serial buffer overflow)")
        if cap.meta.get("frontend_case") is None and args.frontend and not args.fe:
            print("WARNING: no meta line in the capture -> front end unknown, using the standalone "
                  "constants (Case 1 volts will be ~2.5x too small). Pass --fe case1 or recapture.")
        info = {}
        raw = frontend_to_raw(cap, info=info, **kw) if args.frontend else capture_to_raw(cap, **kw)
        if info:
            print(f"drive phase: labels shifted {info['phase_shift_deg']:+.1f} deg to match node A")

    print(f"samples: {len(raw['v'])}   A={raw['A']:.4f} V   Rr={raw['Rr']:g} ohm")
    print(f"v range: {raw['v'].min():+.3f} .. {raw['v'].max():+.3f} V   "
          f"phase: {raw['phase'].min():.3f} .. {raw['phase'].max():.3f} rad")

    if args.verify:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "vi_ml"))
        import verify
        print(verify.verify(raw))


if __name__ == "__main__":
    main()
