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

## 7. FUTURE: ESP32 → PC serial frame (proposed, adjust when firmware is built)

One reading per line over USB serial, e.g. CSV:

```
index,adc_ch_v,adc_ch_i     # adc_* are raw ADC counts
0,2048,1990
1,2131,2050
...
```

PC side (`hardware/reader.py`) converts counts → volts (using ADC V_ref / resolution),
computes I = V_senseR / Rr, builds `phase = 2*pi*f*t`, and packs the raw dict from section 1.
Firmware may instead send a compact binary block for speed — keep the decoded result
identical to section 1 either way.
