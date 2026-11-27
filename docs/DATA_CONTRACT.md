# DATA_CONTRACT.md — Exact input/output formats

Keep these stable. Anything that produces or consumes pipeline data must match here.

## 1. Raw capture (input to the pipeline)

A plain dict — this is what the tracer/reader must produce and what `calibrate()` consumes:

```python
raw = {
    "v":     np.ndarray,  # raw voltage-across-DUT samples (volts), shape (M,)
    "i":     np.ndarray,  # raw current samples (amperes), shape (M,)
    "phase": np.ndarray,  # drive-signal phase for each sample (radians), shape (M,)
    "A":     float,       # drive amplitude (volts, peak) — MEASURED at the drive node, real volts
    "Rr":    float,       # sense/range resistor value (ohms) — a capture setting
}
```

- `M` (number of raw samples) may vary between captures — that's fine, calibration fixes it.
- `phase` comes from the drive signal (known from the frequency / SYNC), NOT estimated from
  the loop geometry. In synth this is `omega * t`. For the front-end boards the reader then
  shifts the labels by one constant so the measured drive node A reads `+A*sin(phase)`
  (`reader.drive_phase_shift`): the firmware's clock-based labels carry a fixed timing offset
  (~14° at 1 kHz, ~2.6° at 50 Hz, 2026-11-27), and node A is the drive itself.
- `A` and `Rr` are needed for normalization and must travel with the capture.
- `A` is the **measured** peak at the drive node, in the same real-volt units as `v` — not the
  DAC's nominal setting (the firmware's `A_nominal_v`). Since 2026-11-27 the synthetic data
  spans `A = 4–6 V` (it was a fixed 5 V); a diode/LED knee sits at a fixed absolute voltage,
  so keep real captures inside that band. Loopback has no drive-node channel yet, so it
  still falls back to the nominal value.
- synth-only extra keys (labels/metadata, ignored by calibrate/verify): `component`,
  `health`, `fault`, `F` (drive frequency the simulated auto-range picked, Hz), `value`
  (R Ω / C F / L H, diode/LED Vf, Zener Vz).

## 2. Calibrated signature (output of calibrate.py)

```python
signature = np.ndarray  # shape (360, 2), dtype float
# column 0 = normalized V, column 1 = normalized I
# normalization: v_n = v/A ; i_n = (i*Rr)/A   (common-factor, preserves V/I ratio)
```

`N_POINTS = 360` is defined in `calibrate.py`. One row per drive-phase degree, ordered
0°→359° (direction preserved).

## 3. Feature vector (output of features.py)

`extract(signature) -> np.ndarray` of shape (14,), order given by `features.FEATURE_NAMES`:

```
signed_area, abs_area, slope0, phaseVI, aspect, knee_V,
symmetry, rms_radius, n_segments, peakV, peakI, spread_ratio,
off_slope, on_res          # added 2026-11-27 (soft faults)
```

off_slope = dI/dV on the blocking side at low current (junction leakage; ~0 when healthy);
on_res = dV/dI on the conducting side past the knee (series resistance of a degraded
diode/LED). Both use the side that conducts more, so a reversed part still works.

Meaning (short): signed_area = loop area with sign (rotation ⇒ C vs L); abs_area = size;
slope0 = dI/dV at origin (conductance); phaseVI = V–I phase angle (deg); aspect = minor/major
axis (line vs ellipse); knee_V = diode knee voltage; symmetry = symmetry about origin;
rms_radius = overall size; n_segments = number of direction changes; peakV/peakI = extremes;
spread_ratio = std(I)/std(V).

## 4. Model outputs (verify.py)

```python
verify(raw) -> {
    "type":          str,    # 'R'|'C'|'L'|'D'|'LED'|'Z'  (only meaningful if verdict == 'GOOD')
    "verdict":       str,    # 'GOOD' | 'FAULTY'   ← primary output
    "confidence":    float,  # 0..1, probability of the chosen verdict
    "anomaly":       bool,   # True if the Isolation Forest flags it abnormal
    "anomaly_score": float,  # higher = more abnormal
}
```

## 5. Saved model files (models/)

`train.py` writes: `health_rf.joblib`, `type_rf.joblib`, `anomaly_if.joblib`, `meta.joblib`
(meta holds feature names, component list, n_points). `verify.py` loads these.

## 6. Component + fault vocabulary (synth.py)

Components: `R, C, L, D, LED, Z`.
Faults per component (shape-changing only): open, short (all); esr, leak (C); dcr,
shorted_turns (L); reversed, degraded (D, LED); reversed, leak (Z). (`vz_shift` was replaced
by `leak` on 2026-11-27: with Vz drawn over 2.4–5.1 V a shifted Vz looks like a good Zener of
another value, i.e. value drift — design decision #5.) ESR/leak/DCR are defined relative to
the part's own reactance at its test frequency, not in fixed ohms.

## 7. ESP32 → PC serial frame

**As built in Stage 3** (`firmware/esp32/loopback/sine_capture`, loopback milestone — see
`firmware/esp32/README.md` for the design decisions behind these choices). One reading per
line over USB serial at **921600 baud**, CSV:

```
index,t_us,phase_rad,adc_v_counts,adc_i_counts
0,0,0.0000,131,131
1,187,0.0587,148,148
...
```

Preceded once at boot by comment lines (prefixed `#`, skip when parsing) carrying capture
settings: `drive_freq_hz`, `lut_size`, `dac_center`, `dac_amplitude_counts`, `A_nominal_v`
(nominal/uncalibrated drive amplitude — see Stage 2's measured offset/gain note in
`firmware/esp32/README.md`), `Rr_ohm_placeholder` (loopback has no real sense resistor yet),
`vref`, `dac_bits`, `adc_bits`, `baud`. Case 1 firmware (`firmware/esp32/case1/case1_frontend`)
also sends `frontend_case=1` and `dac_inverted=1`; `reader.py` uses `frontend_case` to pick
`FrontEnd.case1()` (followers + 100k/22k/22k dividers, no loading term) over the Stage 1 default.

`t_us` was added on top of the originally proposed `index,adc_ch_v,adc_ch_i` shape because
Stage 3 samples free-running (no fixed-interval timer) — `phase_rad` is computed firmware-side
from each sample's *actual* elapsed time, not an assumed constant `dt`, so the timestamp (or
the already-computed `phase_rad`) has to travel with each sample rather than being inferred
from `index` alone. `adc_i_counts` currently reads the same physical pin as `adc_v_counts`
(no real sense resistor exists yet in the loopback setup) — that's expected at this stage, not
a data quality issue.

**Dual-core variant** (`firmware/esp32/dual_core/dual_core_loopback`, 2026-10-09): same five
fields, but `index` is printed modulo 10000 and `t_us` modulo 100000 µs (meta keys
`index_wrap`, `t_us_wrap`, `sample_period_us`) to keep every line ≤ 28 bytes so 921600 baud
never saturates. Nothing downstream uses either field except to spot dropped samples, which
still works on the wrapped difference. `phase_rad` is unaffected (always 0..2π).

**Burst firmware** (`case1_frontend_1k`, `case1_frontend_mf`, 2026-11-27): rows come in bursts.
Each burst starts with the meta line (`# drive_freq_hz=...`, plus `decim`, `points_per_cycle`,
`burst_cycles`, `vi_align`) and ends with `# burst=<n> lines= cycles= points= decim= resyncs=
timeouts= ovf=`. Since 2026-11-27 `case1_frontend_mf` adds `ref_counts=<x>` to that line: the mean
of ~2000 conversions of the offset-reference divider (GPIO32, a copy of the return-path dividers
with its input at GND), read right after the burst, on the same calibrated counts scale. `reader.py`
keeps it as `Capture.ref_counts`, stores it with the zero cal, and adds its move since the zero
capture to both channels' offsets (`reader.ref_corrected`).

PC side (`hardware/reader.py`, implemented) skips `#` lines, the header, and malformed rows
(e.g. a half-received first line), keeps only whole drive cycles (first phase wrap → last
phase wrap), converts counts → volts through a per-channel `ChannelCal(offset, gain)`, computes
I = V_senseR / Rr, and packs the raw dict from section 1 using the already-provided
`phase_rad` directly. The default `ChannelCal` is the *ideal* `counts * 3.3/4095` at mid-rail,
which Stage 2 showed is off on this board (`adc ≈ 16.0×dac − 231`); the loopback path
(`--loopback`) re-centres on the sine midpoint instead, and real captures need a fitted
offset/gain per channel — still TODO. Firmware may move to a compact binary block for speed once real capture
rates go up — keep the decoded result identical to section 1 either way.
