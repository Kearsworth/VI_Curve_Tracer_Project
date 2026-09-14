# DATA_CONTRACT.md — Exact input/output formats

Keep these stable. Anything that produces or consumes pipeline data must match here.

## 1. Raw capture (input to the pipeline)

A plain dict — this is what the tracer/reader must produce and what `calibrate()` consumes:

```python
raw = {
    "v":     np.ndarray,  # raw voltage-across-DUT samples (volts), shape (M,)
    "i":     np.ndarray,  # raw current samples (amperes), shape (M,)
    "phase": np.ndarray,  # drive-signal phase for each sample (radians), shape (M,)
    "A":     float,       # drive amplitude (volts, peak) — a capture setting
    "Rr":    float,       # sense/range resistor value (ohms) — a capture setting
}
```

- `M` (number of raw samples) may vary between captures — that's fine, calibration fixes it.
- `phase` comes from the drive signal (known from the frequency / SYNC), NOT estimated from
  the loop geometry. In synth this is `omega * t`.
- `A` and `Rr` are needed for normalization and must travel with the capture.

## 2. Calibrated signature (output of calibrate.py)

```python
signature = np.ndarray  # shape (360, 2), dtype float
# column 0 = normalized V, column 1 = normalized I
# normalization: v_n = v/A ; i_n = (i*Rr)/A   (common-factor, preserves V/I ratio)
```

`N_POINTS = 360` is defined in `calibrate.py`. One row per drive-phase degree, ordered
0°→359° (direction preserved).

## 3. Feature vector (output of features.py)

`extract(signature) -> np.ndarray` of shape (12,), order given by `features.FEATURE_NAMES`:

```
signed_area, abs_area, slope0, phaseVI, aspect, knee_V,
symmetry, rms_radius, n_segments, peakV, peakI, spread_ratio
```

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
shorted_turns (L); reversed, degraded (D, LED); reversed, vz_shift (Z).

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
`vref`, `dac_bits`, `adc_bits`, `baud`.

`t_us` was added on top of the originally proposed `index,adc_ch_v,adc_ch_i` shape because
Stage 3 samples free-running (no fixed-interval timer) — `phase_rad` is computed firmware-side
from each sample's *actual* elapsed time, not an assumed constant `dt`, so the timestamp (or
the already-computed `phase_rad`) has to travel with each sample rather than being inferred
from `index` alone. `adc_i_counts` currently reads the same physical pin as `adc_v_counts`
(no real sense resistor exists yet in the loopback setup) — that's expected at this stage, not
a data quality issue.

PC side (`hardware/reader.py`) converts counts → volts (needs the real, *calibrated*
offset/gain per channel — see Stage 2's finding that `adc ≈ 16.0×dac − 231`, not the ideal
`counts * 3.3/4095` — not implemented yet), computes I = V_senseR / Rr once a real sense
resistor exists, and packs the raw dict from section 1 using the already-provided
`phase_rad` directly. Firmware may move to a compact binary block for speed once real capture
rates go up — keep the decoded result identical to section 1 either way.
